from bisect import bisect_right
import re

from app.summarization.schemas import EvidenceClaim, QAItem, RiskItem

MIN_QUOTE_LENGTH = 15
PAGE_MARKER_PATTERN = re.compile(r"\[page\s+(\d+)\]")


def normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _index_page_markers(normalized_source: str) -> tuple[list[int], list[int]]:
    positions: list[int] = []
    pages: list[int] = []
    for match in PAGE_MARKER_PATTERN.finditer(normalized_source):
        positions.append(match.start())
        pages.append(int(match.group(1)))
    return positions, pages


def _find_quote_pages(
    quote: str,
    normalized_source: str,
    marker_positions: list[int],
    marker_pages: list[int],
) -> set[int]:
    """Return all page numbers on which the normalized quote appears."""
    norm_quote = normalize_for_match(quote)
    if len(norm_quote) < MIN_QUOTE_LENGTH or not marker_positions:
        return set()

    found_pages: set[int] = set()
    start = 0

    while True:
        pos = normalized_source.find(norm_quote, start)
        if pos == -1:
            break

        idx = bisect_right(marker_positions, pos) - 1
        if idx >= 0:
            found_pages.add(marker_pages[idx])

        start = pos + 1

    return found_pages


def validate_claims(
    claims: list[EvidenceClaim], source_text: str
) -> tuple[list[EvidenceClaim], list[EvidenceClaim]]:
    """Keep claims whose quote occurs in source_text on the reported page."""
    normalized_source = normalize_for_match(source_text)
    marker_positions, marker_pages = _index_page_markers(normalized_source)

    valid: list[EvidenceClaim] = []
    rejected: list[EvidenceClaim] = []

    for claim in claims:
        found_pages = _find_quote_pages(
            claim.quote, normalized_source, marker_positions, marker_pages
        )
        if claim.page in found_pages:
            valid.append(claim)
        else:
            rejected.append(claim)

    return valid, rejected


def validate_risks(
    risks: list[RiskItem], source_text: str
) -> tuple[list[RiskItem], list[RiskItem]]:
    """Keep risk items whose quote occurs in source_text on the reported page."""
    normalized_source = normalize_for_match(source_text)
    marker_positions, marker_pages = _index_page_markers(normalized_source)

    valid: list[RiskItem] = []
    rejected: list[RiskItem] = []

    for risk in risks:
        found_pages = _find_quote_pages(
            risk.quote, normalized_source, marker_positions, marker_pages
        )
        if risk.page in found_pages:
            valid.append(risk)
        else:
            rejected.append(risk)

    return valid, rejected


def validate_qa_items(
    qa_items: list[QAItem], source_text: str
) -> tuple[list[QAItem], list[QAItem]]:
    """
    Keep Q&A items that have at least one verified quote on qa.page.
    Additional supporting quotes may appear on qa.page through qa.page + 2
    to accommodate exchanges that cross a page boundary. Unverified quotes
    are stripped from retained items.
    """
    normalized_source = normalize_for_match(source_text)
    marker_positions, marker_pages = _index_page_markers(normalized_source)

    valid: list[QAItem] = []
    rejected: list[QAItem] = []

    for qa in qa_items:
        allowed_pages = {qa.page, qa.page + 1, qa.page + 2}
        verified_quotes: list[str] = []
        has_primary_page_quote = False

        for quote in qa.supporting_quotes:
            found_pages = _find_quote_pages(
                quote, normalized_source, marker_positions, marker_pages
            )
            if found_pages & allowed_pages:
                verified_quotes.append(quote)
                if qa.page in found_pages:
                    has_primary_page_quote = True

        if verified_quotes and has_primary_page_quote:
            valid.append(
                qa.model_copy(update={"supporting_quotes": verified_quotes})
            )
        else:
            rejected.append(qa)

    return valid, rejected