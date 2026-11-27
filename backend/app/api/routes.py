import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

from app.core.companies import COMPANIES
from app.services.ws_manager import ws_manager
from app.summarization.gemini_client import GeminiSummarizer
from app.summarization.pipeline import (
    EXTRACTED_DIR,
    SUMMARY_JSON_DIR,
    SUMMARY_MD_DIR,
    process_one,
)

logger = logging.getLogger(__name__)

router = APIRouter()

TRANSCRIPTS_DIR = Path("backend/data/transcripts")

pipeline_state: dict[str, Any] = {
    "is_running": False,
    "last_run_status": "idle",
    "last_processed_file": None,
    "last_error": None,
}


def _load_json_safe(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@router.get("/api/companies")
async def list_companies():
    """List configured companies along with downloaded transcript and summary counts."""
    results = []
    for symbol, info in COMPANIES.items():
        name = info.get("name", symbol) if isinstance(info, dict) else str(info)
        transcript_count = len(list((TRANSCRIPTS_DIR / symbol).glob("*.pdf")))
        extracted_count = len(list((EXTRACTED_DIR / symbol).glob("*.json")))
        summary_count = len(list(SUMMARY_JSON_DIR.glob(f"{symbol}_*.json")))

        results.append(
            {
                "symbol": symbol,
                "name": name,
                "transcript_count": transcript_count,
                "extracted_count": extracted_count,
                "summary_count": summary_count,
            }
        )
    return {"companies": results}


@router.get("/api/transcripts")
async def list_transcripts(symbol: str | None = Query(default=None)):
    """List extracted transcripts, optionally filtered by company symbol."""
    pattern = f"{symbol.upper()}/*.json" if symbol else "*/*.json"
    files = sorted(EXTRACTED_DIR.glob(pattern), reverse=True)

    transcripts = []
    for file_path in files:
        data = _load_json_safe(file_path)
        if not data:
            continue
        metadata = data.get("metadata", {})
        summary_exists = (SUMMARY_JSON_DIR / f"{file_path.stem}.json").exists()
        transcripts.append(
            {
                "id": file_path.stem,
                "symbol": data.get("company", file_path.parent.name),
                "source_file": data.get("source_file", file_path.name),
                "page_count": metadata.get("page_count"),
                "character_count": metadata.get("character_count"),
                "chunk_count": metadata.get("chunk_count"),
                "summarized": summary_exists,
            }
        )
    return {"count": len(transcripts), "transcripts": transcripts}


@router.get("/api/summaries")
async def list_summaries(symbol: str | None = Query(default=None)):
    """List generated summaries with metadata."""
    pattern = f"{symbol.upper()}_*.json" if symbol else "*.json"
    files = sorted(SUMMARY_JSON_DIR.glob(pattern), reverse=True)

    summaries = []
    for file_path in files:
        data = _load_json_safe(file_path)
        if not data:
            continue
        summaries.append(
            {
                "id": file_path.stem,
                "company": data.get("company"),
                "symbol": data.get("symbol"),
                "quarter": data.get("quarter"),
                "call_date": data.get("call_date"),
                "tldr_count": len(data.get("tldr", [])),
                "qa_count": len(data.get("notable_qa", [])),
                "risk_count": len(data.get("risks", [])),
            }
        )
    return {"count": len(summaries), "summaries": summaries}


@router.get("/api/summaries/{summary_id}")
async def get_summary(summary_id: str):
    """Retrieve a full structured JSON summary by ID."""
    path = SUMMARY_JSON_DIR / f"{summary_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Summary not found")

    data = _load_json_safe(path)
    if data is None:
        raise HTTPException(status_code=500, detail="Failed to read summary file")
    return data


@router.get("/api/summaries/{summary_id}/markdown", response_class=PlainTextResponse)
async def get_summary_markdown(summary_id: str):
    """Retrieve the human-readable Markdown summary by ID."""
    path = SUMMARY_MD_DIR / f"{summary_id}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Markdown summary not found")
    return path.read_text(encoding="utf-8")


@router.get("/api/status")
async def get_status():
    """Return current pipeline processing status and WebSocket client count."""
    return {
        **pipeline_state,
        "active_ws_clients": len(ws_manager.active_connections),
        "total_summaries": len(list(SUMMARY_JSON_DIR.glob("*.json"))),
    }


async def _run_summarization_job(symbol: str | None = None):
    if pipeline_state["is_running"]:
        return

    pipeline_state["is_running"] = True
    pipeline_state["last_run_status"] = "running"
    pipeline_state["last_error"] = None

    pattern = f"{symbol.upper()}/*.json" if symbol else "*/*.json"
    files = sorted(EXTRACTED_DIR.glob(pattern))

    await ws_manager.broadcast(
        "pipeline_started",
        {"symbol": symbol or "ALL", "file_count": len(files)},
    )

    try:
        ai = GeminiSummarizer()
        for file_path in files:
            pipeline_state["last_processed_file"] = file_path.name
            await asyncio.to_thread(process_one, file_path, ai)

            summary_path = SUMMARY_JSON_DIR / f"{file_path.stem}.json"
            summary_data = _load_json_safe(summary_path)
            if summary_data:
                await ws_manager.broadcast(
                    "summary_completed",
                    {
                        "id": file_path.stem,
                        "company": summary_data.get("company"),
                        "symbol": summary_data.get("symbol"),
                        "quarter": summary_data.get("quarter"),
                        "call_date": summary_data.get("call_date"),
                        "summary": summary_data,
                    },
                )

        pipeline_state["last_run_status"] = "completed"
    except Exception as exc:
        logger.exception("Background summarization job failed")
        pipeline_state["last_run_status"] = "failed"
        pipeline_state["last_error"] = str(exc)
        await ws_manager.broadcast("processing_failed", {"error": str(exc)})
    finally:
        pipeline_state["is_running"] = False


@router.post("/api/pipeline/trigger")
async def trigger_pipeline(
    background_tasks: BackgroundTasks,
    symbol: str | None = Query(default=None),
):
    """Trigger background summarization for all extracted transcripts or one company."""
    if pipeline_state["is_running"]:
        raise HTTPException(status_code=409, detail="Pipeline is already running")

    background_tasks.add_task(_run_summarization_job, symbol)
    return {
        "status": "accepted",
        "message": f"Pipeline triggered for {symbol.upper() if symbol else 'all companies'}",
    }


@router.websocket("/ws/summaries")
async def websocket_summaries(websocket: WebSocket):
    """Real-time WebSocket feed streaming pipeline and summary events."""
    await ws_manager.connect(websocket)
    try:
        await websocket.send_json(
            {
                "event": "connected",
                "data": {
                    "message": "Subscribed to ConcallAI real-time summary feed",
                    "active_clients": len(ws_manager.active_connections),
                },
            }
        )
        while True:
            # Keep connection open and handle optional client pings
            msg = await websocket.receive_text()
            if msg.strip().lower() == "ping":
                await websocket.send_json({"event": "pong", "data": {}})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)