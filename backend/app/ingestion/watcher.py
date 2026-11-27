import logging
import re
import time
from pathlib import Path

from app.core.companies import COMPANIES
from app.core.config import settings

from app.ingestion.nse import NSEClient
from app.ingestion.bse import BSEClient
from app.ingestion.state import IngestionState

from app.ingestion.utils import (
    download_pdf,
    make_fingerprint
)

logger = logging.getLogger(__name__)


DATA_DIR = Path("backend/data/transcripts")


def safe_filename(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]", "_", value)
    return value[:100]


class ConcallWatcher:

    def __init__(self):
        self.nse = NSEClient() if settings.nse_enabled else None
        self.bse = BSEClient() if settings.bse_enabled else None
        self.state = IngestionState()

    def collect(self):
        discovered = []

        for symbol in COMPANIES:
            if self.nse:
                try:
                    discovered.extend(
                        self.nse.fetch_announcements(symbol)
                    )
                except Exception:
                    logger.exception(
                        "NSE collection failed for %s",
                        symbol
                    )

            if self.bse:
                try:
                    discovered.extend(
                        self.bse.fetch_announcements(symbol)
                    )
                except Exception:
                    logger.exception(
                        "BSE collection failed for %s",
                        symbol
                    )

            # Be respectful to the exchanges.
            time.sleep(1.5)

        return discovered

    def run_once(self):
        announcements = self.collect()

        logger.info(
            "Total matching announcements: %d",
            len(announcements)
        )

        downloaded = 0

        for announcement in announcements:
            fingerprint = make_fingerprint(announcement)

            if self.state.exists(fingerprint):
                continue

            filename = (
                f"{announcement.symbol}_"
                f"{safe_filename(announcement.announcement_date)}_"
                f"{fingerprint[:10]}.pdf"
            )

            destination = DATA_DIR / announcement.symbol / filename

            session = (
                self.nse.session
                if announcement.source == "NSE" and self.nse
                else self.bse.session
            )

            if announcement.source == "NSE":
                session.headers.update({
                    "Referer": "https://www.nseindia.com/",
                    "Accept": "application/pdf,*/*"
                })

            elif announcement.source == "BSE":
                session.headers.update({
                    "Referer": "https://www.bseindia.com/",
                    "Accept": "application/pdf,*/*"
                })

            try:
                download_pdf(
                    session,
                    announcement.attachment_url,
                    destination
                )

                self.state.save(
                    fingerprint,
                    announcement,
                    str(destination)
                )

                logger.info(
                    "Downloaded %s from %s: %s",
                    announcement.symbol,
                    announcement.source,
                    destination
                )

                downloaded += 1

            except Exception:
                logger.exception(
                    "Download failed: %s",
                    announcement.attachment_url
                )

        return downloaded

    def close(self):
        self.state.close()


def main():
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    watcher = ConcallWatcher()

    try:
        while True:
            try:
                count = watcher.run_once()

                logger.info(
                    "Watcher cycle complete. Downloaded: %d",
                    count
                )

            except Exception:
                logger.exception("Watcher cycle failed")

            time.sleep(settings.poll_interval_seconds)

    except KeyboardInterrupt:
        logger.info("Watcher stopped by user")

    finally:
        watcher.close()


if __name__ == "__main__":
    main()