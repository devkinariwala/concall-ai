import asyncio
import json
import logging
from pathlib import Path

from app.api.routes import _load_json_safe, pipeline_state
from app.core.config import settings
from app.extraction.cleaner import clean_transcript
from app.extraction.pdf_extractor import extract_pdf
from app.ingestion.watcher import ConcallWatcher
from app.services.ws_manager import ws_manager
from app.summarization.chunker import chunk_transcript
from app.summarization.gemini_client import GeminiSummarizer
from app.summarization.pipeline import (
    EXTRACTED_DIR,
    SUMMARY_JSON_DIR,
    process_one,
)

logger = logging.getLogger(__name__)

TRANSCRIPTS_DIR = Path("backend/data/transcripts")


def _run_watcher_once() -> int:
    """Run one NSE/BSE scan in a dedicated thread-local watcher instance."""
    watcher = ConcallWatcher()
    try:
        return watcher.run_once()
    finally:
        watcher.close()


def _extract_single_pdf(pdf_path: Path) -> Path:
    """Extract, clean, and chunk a single PDF into backend/data/extracted."""
    extracted = extract_pdf(str(pdf_path))
    cleaned_text = clean_transcript(extracted["pages"])
    chunks = chunk_transcript(cleaned_text)
    company = pdf_path.parent.name

    output = {
        "company": company,
        "source_file": pdf_path.name,
        "metadata": {
            "page_count": extracted["page_count"],
            "character_count": len(cleaned_text),
            "chunk_count": len(chunks),
            "extraction_method": extracted["extraction_method"],
        },
        "transcript": cleaned_text,
        "chunks": [
            {
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "start_position": chunk.start_position,
                "end_position": chunk.end_position,
            }
            for chunk in chunks
        ],
    }

    company_dir = EXTRACTED_DIR / company
    company_dir.mkdir(parents=True, exist_ok=True)
    output_path = company_dir / f"{pdf_path.stem}.json"
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path


async def run_monitor_cycle() -> None:
    """Execute one full Ingest -> Extract -> Summarize cycle with per-file error isolation."""
    if pipeline_state["is_running"]:
        logger.info("Pipeline already running; skipping scheduled monitor cycle.")
        return

    pipeline_state["is_running"] = True
    pipeline_state["last_run_status"] = "monitoring"
    pipeline_state["last_error"] = None
    had_errors = False

    try:
        # 1. Watch & Ingest (isolated so exchange errors don't block local pending files)
        try:
            downloaded = await asyncio.to_thread(_run_watcher_once)
            if downloaded > 0:
                await ws_manager.broadcast(
                    "download_completed",
                    {"downloaded_count": downloaded},
                )
        except Exception as exc:
            had_errors = True
            pipeline_state["last_error"] = f"Ingestion error: {exc}"
            logger.exception("Watcher scan failed; continuing with local files")
            await ws_manager.broadcast(
                "processing_failed",
                {"stage": "ingestion", "error": str(exc)},
            )

        # 2. Extract any PDFs that do not yet have an extracted JSON
        pdf_files = sorted(TRANSCRIPTS_DIR.rglob("*.pdf"))
        for pdf_path in pdf_files:
            expected_json = EXTRACTED_DIR / pdf_path.parent.name / f"{pdf_path.stem}.json"
            if expected_json.exists():
                continue

            try:
                logger.info("Extracting new transcript: %s", pdf_path.name)
                extracted_path = await asyncio.to_thread(_extract_single_pdf, pdf_path)
                await ws_manager.broadcast(
                    "extraction_completed",
                    {"symbol": pdf_path.parent.name, "file": extracted_path.name},
                )
            except Exception as exc:
                had_errors = True
                pipeline_state["last_error"] = f"Extraction failed for {pdf_path.name}: {exc}"
                logger.exception("Failed to extract %s; continuing", pdf_path.name)
                await ws_manager.broadcast(
                    "processing_failed",
                    {
                        "stage": "extraction",
                        "symbol": pdf_path.parent.name,
                        "file": pdf_path.name,
                        "error": str(exc),
                    },
                )

        # 3. Summarize any extracted JSONs that do not yet have a summary
        extracted_files = sorted(EXTRACTED_DIR.glob("*/*.json"))
        pending_summaries = [
            path
            for path in extracted_files
            if not (SUMMARY_JSON_DIR / f"{path.stem}.json").exists()
        ]

        if pending_summaries:
            ai = GeminiSummarizer()
            for json_path in pending_summaries:
                pipeline_state["last_processed_file"] = json_path.name
                try:
                    logger.info("Summarizing new transcript: %s", json_path.name)
                    await asyncio.to_thread(process_one, json_path, ai)

                    summary_data = _load_json_safe(SUMMARY_JSON_DIR / f"{json_path.stem}.json")
                    if summary_data:
                        await ws_manager.broadcast(
                            "summary_completed",
                            {
                                "id": json_path.stem,
                                "company": summary_data.get("company"),
                                "symbol": summary_data.get("symbol"),
                                "quarter": summary_data.get("quarter"),
                                "call_date": summary_data.get("call_date"),
                                "summary": summary_data,
                            },
                        )
                except Exception as exc:
                    had_errors = True
                    pipeline_state["last_error"] = f"Summarization failed for {json_path.name}: {exc}"
                    logger.exception("Failed to summarize %s; continuing", json_path.name)
                    await ws_manager.broadcast(
                        "processing_failed",
                        {
                            "stage": "summarization",
                            "symbol": json_path.parent.name,
                            "file": json_path.name,
                            "error": str(exc),
                        },
                    )

        pipeline_state["last_run_status"] = "completed_with_errors" if had_errors else "idle"
    finally:
        pipeline_state["is_running"] = False


async def start_background_monitor() -> None:
    """Continuously poll NSE/BSE on settings.poll_interval_seconds."""
    interval = max(30, int(settings.poll_interval_seconds))
    logger.info("Background monitor started (poll interval: %ss)", interval)

    try:
        while True:
            await asyncio.sleep(interval)
            await run_monitor_cycle()
    except asyncio.CancelledError:
        logger.info("Background monitor stopped.")
        raise