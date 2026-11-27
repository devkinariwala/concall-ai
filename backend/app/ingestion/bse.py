import logging
from datetime import date, timedelta
from urllib.parse import urljoin

from app.core.companies import COMPANIES
from app.ingestion.models import Announcement
from app.ingestion.utils import create_session, is_concall_transcript

logger = logging.getLogger(__name__)

BSE_API = (
    "https://api.bseindia.com/"
    "BseIndiaAPI/api/AnnSubCategoryGetData/w"
)

BSE_ATTACHMENT_BASE = (
    "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
)


def pick(row: dict, *keys):
    """Read API fields without assuming capitalization."""
    normalized = {
        str(key).lower(): value
        for key, value in row.items()
    }

    for key in keys:
        value = normalized.get(key.lower())

        if value is not None and str(value).strip():
            return value

    return ""


class BSEClient:

    def __init__(self):
      self.session = create_session()

      self.session.headers.update({
          "Host": "api.bseindia.com",
          "Referer": "https://www.bseindia.com/",
          "Origin": "https://www.bseindia.com",

          "User-Agent": (
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/155.0.0.0 Safari/537.36"
          ),

          "Sec-CH-UA": (
              '"Google Chrome";v="155", '
              '"Chromium";v="155", '
              '"Not?A_Brand";v="99"'
          ),

          "Sec-CH-UA-Mobile": "?0",
          "Sec-CH-UA-Platform": '"Windows"',

          "Sec-Fetch-Dest": "empty",
          "Sec-Fetch-Mode": "cors",
          "Sec-Fetch-Site": "same-site",

          "Accept": "application/json, text/plain, */*",
          "Accept-Language": "en-US,en;q=0.9",
          "Cache-Control": "no-cache",
          "Connection": "keep-alive",
          "DNT": "1"
      })

    def fetch_announcements(
        self,
        symbol: str,
        days_back: int = 90
    ) -> list[Announcement]:

        company = COMPANIES[symbol]

        today = date.today()
        start = today - timedelta(days=days_back)

        params = {
            "pageno": 1,
            "strCat": "-1",
            "subcategory": "-1",
            "strPrevDate": start.strftime("%Y%m%d"),
            "strToDate": today.strftime("%Y%m%d"),
            "strSearch": "P",
            "strScrip": company["bse_code"],
            "strType": "C"
        }

        response = self.session.get(
            BSE_API,
            params=params,
            timeout=40
        )

        if response.status_code == 403:
            logger.error(
                "BSE denied access (403) for %s. "
                "Exchange access is currently restricted.",
                symbol
            )
            return []

        response.raise_for_status()

        payload = response.json()

        if isinstance(payload, list):
            rows = payload

        elif isinstance(payload, dict):
            rows = (
                payload.get("Table")
                or payload.get("Table1")
                or payload.get("table")
                or []
            )
        else:
            rows = []

        announcements = []

        for row in rows:
            subject = str(
                pick(
                    row,
                    "NEWSSUB",
                    "NEWS_SUB",
                    "SUBJECT",
                    "HEADLINE"
                )
            )

            description = str(
                pick(
                    row,
                    "MORE",
                    "MORETEXT",
                    "NEWS_DESC",
                    "DESCRIPTION"
                )
            )

            if not is_concall_transcript(
                subject,
                description
            ):
                continue

            attachment = str(
                pick(
                    row,
                    "ATTACHMENTNAME",
                    "ATTACHMENT",
                    "ATTACHMENT_URL",
                    "PDFLINK"
                )
            ).strip()

            if not attachment:
                continue

            if not attachment.startswith("http"):
                attachment = urljoin(
                    BSE_ATTACHMENT_BASE,
                    attachment.lstrip("/")
                )

            announcement_date = str(
                pick(
                    row,
                    "NEWS_DT",
                    "NEWS_DATE",
                    "DT",
                    "DISSEMINATIONTIME"
                )
            )

            announcement_id = str(
                pick(
                    row,
                    "NEWSID",
                    "NEWS_ID",
                    "ID"
                ) or attachment
            )

            company_name = str(
                pick(row, "SLONGNAME", "SCRIP_NAME")
                or company["name"]
            )

            announcements.append(
                Announcement(
                    company=company_name,
                    symbol=symbol,
                    source="BSE",
                    subject=subject,
                    announcement_date=announcement_date,
                    attachment_url=attachment,
                    exchange_id=announcement_id,
                    bse_code=company["bse_code"],
                    description=description
                )
            )

        logger.info(
            "BSE %s: found %d matching transcripts",
            symbol,
            len(announcements)
        )

        return announcements