from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Announcement:
    company: str
    symbol: str
    source: str
    subject: str
    announcement_date: str
    attachment_url: str
    exchange_id: str
    bse_code: Optional[str] = None
    description: Optional[str] = None

    def to_dict(self):
        return asdict(self)