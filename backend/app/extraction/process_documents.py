import json
import logging
from pathlib import Path

from app.extraction.pdf_extractor import extract_pdf
from app.extraction.cleaner import clean_transcript
from app.summarization.chunker import chunk_transcript


INPUT_DIR = Path("backend/data/transcripts")
OUTPUT_DIR = Path("backend/data/extracted")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


def process_all_documents():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    pdf_files = list(INPUT_DIR.rglob("*.pdf"))

    logger.info(
        "Found %d PDF documents",
        len(pdf_files)
    )

    for pdf_path in pdf_files:

        try:
            logger.info("Processing %s", pdf_path.name)

            extracted = extract_pdf(str(pdf_path))

            cleaned_text = clean_transcript(
                extracted["pages"]
            )

            chunks = chunk_transcript(cleaned_text)

            company = pdf_path.parent.name

            output = {
                "company": company,
                "source_file": pdf_path.name,
                "metadata": {
                    "page_count": extracted["page_count"],
                    "character_count": len(cleaned_text),
                    "chunk_count": len(chunks),
                    "extraction_method": extracted[
                        "extraction_method"
                    ]
                },
                "transcript": cleaned_text,
                "chunks": [
                    {
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                        "start_position": chunk.start_position,
                        "end_position": chunk.end_position
                    }
                    for chunk in chunks
                ]
            }

            company_dir = OUTPUT_DIR / company
            company_dir.mkdir(
                parents=True,
                exist_ok=True
            )

            output_path = (
                company_dir /
                f"{pdf_path.stem}.json"
            )

            with output_path.open(
                "w",
                encoding="utf-8"
            ) as file:
                json.dump(
                    output,
                    file,
                    indent=2,
                    ensure_ascii=False
                )

            logger.info(
                "Successfully processed %s | Pages: %d | Chunks: %d",
                pdf_path.name,
                extracted["page_count"],
                len(chunks)
            )

        except Exception:
            logger.exception(
                "Failed to process %s",
                pdf_path.name
            )


if __name__ == "__main__":
    process_all_documents()