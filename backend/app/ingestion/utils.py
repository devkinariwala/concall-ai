import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from tenacity import retry, stop_after_attempt, wait_exponential


TRANSCRIPT_KEYWORDS = [
    "transcript",
    "concall",
    "conference call",
    "earnings call",
    "investor call",
    "analyst call"
]

# Positive evidence is required. A generic investor meeting
# announcement is not automatically treated as a transcript.
NEGATIVE_KEYWORDS = [
    "intimation",
    "schedule",
    "outcome of meeting",
    "audio recording",
    "video recording",
    "presentation"
]


def is_concall_transcript(subject: str, description: str = "") -> bool:
    text = f"{subject} {description}".lower()

    has_transcript_evidence = any(
        keyword in text for keyword in TRANSCRIPT_KEYWORDS
    )

    # Exclude clearly non-transcript filings unless the
    # announcement explicitly identifies a transcript.
    explicit_transcript = "transcript" in text or "transcription" in text

    if not has_transcript_evidence:
        return False

    if not explicit_transcript and any(
        keyword in text for keyword in NEGATIVE_KEYWORDS
    ):
        return False

    return True


def make_fingerprint(announcement) -> str:
    """
    Exchange-independent deduplication fingerprint.
    """
    normalized = "|".join([
        announcement.symbol.upper().strip(),
        announcement.announcement_date[:10],
        re.sub(r"\s+", " ", announcement.subject.lower()).strip()
    ])

    return hashlib.sha256(normalized.encode()).hexdigest()


def create_session() -> requests.Session:
    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive"
    })

    return session


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
def download_pdf(session, url: str, destination: Path) -> Path:
    if not url or url.lower() == "nan":
        raise ValueError("Missing PDF attachment URL")

    parsed = urlparse(url)

    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Invalid or insecure attachment URL")
    
    ALLOWED_ATTACHMENT_HOSTS = {
    "nsearchives.nseindia.in",
    "nsearchives.nseindia.com",
    "www.nseindia.com",
    "www.bseindia.com",
    "api.bseindia.com",
    "bseindia.com"
}

    if parsed.hostname.lower() not in ALLOWED_ATTACHMENT_HOSTS:
      raise ValueError(
          f"Unexpected attachment host: {parsed.hostname}"
      )

    destination.parent.mkdir(parents=True, exist_ok=True)

    with session.get(
        url,
        stream=True,
        timeout=(15, 90)
    ) as response:
        response.raise_for_status()

        content_type = response.headers.get(
            "Content-Type", ""
        ).lower()

        iterator = response.iter_content(chunk_size=8192)

        first_chunk = next(iterator, b"")

        if not (
            first_chunk.startswith(b"%PDF-")
            or "pdf" in content_type
        ):
            raise ValueError("Downloaded attachment is not a PDF")

        with destination.open("wb") as file:
            file.write(first_chunk)

            for chunk in iterator:
                if chunk:
                    file.write(chunk)

    if destination.stat().st_size < 1000:
        destination.unlink(missing_ok=True)
        raise ValueError("PDF is unexpectedly small")

    return destination