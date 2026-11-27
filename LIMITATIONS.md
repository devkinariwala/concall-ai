# Known Limitations & Trade-offs

## 1. Exchange Scraping & BSE HTTP 403 Restrictions
- **NSE** corporate announcement endpoints and PDF attachments work reliably using session cookies, browser-like headers, and a 1.5s inter-company delay.
- **BSE** announcement metadata is retrievable, but direct PDF attachment downloads intermittently return `HTTP 403 Forbidden` due to strict exchange anti-bot controls. Rather than relying on fragile headless-browser workarounds, blocked BSE downloads are logged and skipped while NSE + fingerprint deduplication handle ingestion.

## 2. Scanned / Image-Only PDFs (No OCR Fallback Yet)
- Text extraction uses PyMuPDF to preserve layout and `[PAGE N]` markers.
- Scanned or image-only PDFs without an embedded text layer are rejected by the minimum-text guard rather than processed via OCR.

## 3. Audio-Only Filings & XBRL Metadata
- Announcements that link only to an audio/video recording (before a written transcript PDF is filed) are skipped by the transcript filter.
- Quarter and call date are extracted from the transcript text itself rather than parsing attached XBRL XML files.

## 4. Long-Transcript Chunk Boundaries
- Transcripts are split into ~12,000-character chunks with a 1,000-character overlap.
- If a multi-turn analyst Q&A spans a chunk boundary, the exchange may be split. Validation mitigates this by checking quotes against the full original transcript and allowing Q&A supporting quotes to span up to two subsequent pages.

## 5. Strict Evidence Validation Trade-off
- Every claim, Q&A item, and risk must include a verbatim quote (>=15 characters) matching the original transcript on the exact reported page.
- This prevents hallucinations, but occasionally rejects valid paraphrased or slightly mis-cited extractions from the LLM. Rejection counts are logged transparently in each summary's `limitations` field.
