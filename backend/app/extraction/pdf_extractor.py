import logging
import re
from pathlib import Path

import fitz

logger = logging.getLogger(__name__)


class PDFExtractionError(Exception):
    pass


def normalize_text(text: str) -> str:
    """Normalize extracted text without destroying transcript structure."""

    text = text.replace("\x00", " ")
    text = text.replace("\u00a0", " ")

    # Repair common PDF line-break hyphenation.
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)

    # Normalize whitespace.
    text = re.sub(r"[ \t]+", " ", text)

    # Remove excessive blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def extract_pdf(pdf_path: str) -> dict:
    """
    Extract text page-by-page and retain page boundaries.

    Returns document metadata and extracted text.
    """

    path = Path(pdf_path)

    if not path.exists():
        raise PDFExtractionError(
            f"PDF does not exist: {path}"
        )

    if path.stat().st_size == 0:
        raise PDFExtractionError("PDF is empty")

    pages = []

    try:
        with fitz.open(path) as document:

            if document.is_encrypted:
                raise PDFExtractionError(
                    "Encrypted PDFs are not supported"
                )

            metadata = document.metadata or {}

            for page_number, page in enumerate(document, start=1):
                page_text = normalize_text(
                    page.get_text("text", sort=True)
                )

                if page_text:
                    pages.append({
                        "page": page_number,
                        "text": page_text
                    })

            full_text = "\n\n".join(
                f"[PAGE {page['page']}]\n{page['text']}"
                for page in pages
            )

            if len(full_text.strip()) < 200:
                raise PDFExtractionError(
                    "Insufficient text extracted. "
                    "The document may be scanned or image-based."
                )

            result = {
                "file_name": path.name,
                "page_count": len(document),
                "extracted_pages": len(pages),
                "title": metadata.get("title"),
                "author": metadata.get("author"),
                "text": full_text,
                "pages": pages,
                "character_count": len(full_text),
                "extraction_method": "pymupdf"
            }

            logger.info(
                "Extracted %d characters from %s",
                len(full_text),
                path.name
            )

            return result

    except PDFExtractionError:
        raise

    except Exception as exc:
        raise PDFExtractionError(
            f"PDF extraction failed: {exc}"
        ) from exc