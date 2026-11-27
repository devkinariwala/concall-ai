import re
from collections import Counter


def remove_repeated_headers_and_footers(
    pages: list[dict],
    threshold: float = 0.60
) -> list[dict]:
    """
    Identify repeated first/last lines across pages.

    Only removes lines occurring at page boundaries.
    """

    if len(pages) < 3:
        return pages

    boundary_lines = []

    for page in pages:
        lines = [
            line.strip()
            for line in page["text"].splitlines()
            if line.strip()
        ]

        if lines:
            boundary_lines.extend(lines[:2])
            boundary_lines.extend(lines[-2:])

    counts = Counter(
        line.lower() for line in boundary_lines
    )

    minimum_occurrences = max(
        3,
        int(len(pages) * threshold)
    )

    repeated = {
        line for line, count in counts.items()
        if count >= minimum_occurrences
        and len(line) < 150
    }

    cleaned_pages = []

    for page in pages:
        lines = page["text"].splitlines()
        filtered = []

        for index, line in enumerate(lines):
            normalized = line.strip().lower()

            is_boundary = (
                index < 2
                or index >= len(lines) - 2
            )

            if is_boundary and normalized in repeated:
                continue

            filtered.append(line)

        cleaned_pages.append({
            **page,
            "text": "\n".join(filtered).strip()
        })

    return cleaned_pages


def clean_transcript(pages: list[dict]) -> str:
    cleaned_pages = remove_repeated_headers_and_footers(pages)

    output = []

    for page in cleaned_pages:
        output.append(
            f"[PAGE {page['page']}]\n{page['text']}"
        )

    return "\n\n".join(output).strip()