import logging
from datetime import date, timedelta
from app.core.companies import COMPANIES

from app.ingestion.models import Announcement
from app.ingestion.utils import create_session, is_concall_transcript

logger = logging.getLogger(__name__)

BASE_URL = "https://www.nseindia.com"

ANNOUNCEMENTS_URL = (
    f"{BASE_URL}/api/corporate-announcements"
)


class NSEClient:

    def __init__(self):
        self.session = create_session()

        # Establish a session before accessing the JSON endpoint.
        self.session.get(
            BASE_URL,
            timeout=20
        ).raise_for_status()

    def matches_company(self, row: dict, symbol: str) -> bool:
      expected_name = COMPANIES[symbol]["name"].lower()

      row_symbol = str(
          row.get("symbol")
          or row.get("sym")
          or row.get("nse_symbol")
          or ""
      ).strip().upper()

      row_name = str(
          row.get("company")
          or row.get("sm_name")
          or row.get("companyName")
          or ""
      ).strip().lower()

      if row_symbol:
          return row_symbol == symbol

      if row_name:
          return (
              row_name == expected_name
              or expected_name in row_name
          )

      # Unknown company identity: reject rather than risk
      # processing another company's financial information.
      return False

    def fetch_announcements(
        self,
        symbol: str,
        days_back: int = 90
    ) -> list[Announcement]:

        today = date.today()
        start = today - timedelta(days=days_back)

        params = {
            "index": "equities",
            "from_date": start.strftime("%d-%m-%Y"),
            "to_date": today.strftime("%d-%m-%Y"),
            "symbol": symbol
        }

        response = self.session.get(
            ANNOUNCEMENTS_URL,
            params=params,
            timeout=40
        )

        response.raise_for_status()

        payload = response.json()

        if not isinstance(payload, list):
            logger.warning(
                "Unexpected NSE response for %s", symbol
            )
            return []

        announcements = []

        for row in payload:
            if not self.matches_company(row, symbol):
              logger.warning(
                  "Skipping unrelated/unknown NSE record for %s: %s",
                  symbol,
                  row
              )
              continue
            subject = str(
                row.get("desc") or row.get("subject") or ""
            )

            description = str(
                row.get("attchmntText") or ""
            )

            if not is_concall_transcript(
                subject,
                description
            ):
                continue

            attachment = str(
                row.get("attchmntFile") or ""
            ).strip()

            if not attachment:
                continue

            if attachment.startswith("/"):
                attachment = BASE_URL + attachment

            announcement_date = str(
                row.get("an_dt")
                or row.get("sort_date")
                or ""
            )

            announcement_id = str(
                row.get("seq_id")
                or row.get("id")
                or attachment
            )

            announcements.append(
                Announcement(
                    company=str(
                        row.get("company")
                        or row.get("sm_name")
                        or symbol
                    ),
                    symbol=symbol,
                    source="NSE",
                    subject=subject,
                    announcement_date=announcement_date,
                    attachment_url=attachment,
                    exchange_id=announcement_id,
                    description=description
                )
            )

        logger.info(
            "NSE %s: found %d matching transcripts",
            symbol,
            len(announcements)
        )

        return announcements