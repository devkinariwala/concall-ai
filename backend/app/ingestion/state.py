import sqlite3
from pathlib import Path

DB_PATH = Path("backend/data/ingestion_state.db")


class IngestionState:

    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(DB_PATH)

        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS processed (
                fingerprint TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                source TEXT NOT NULL,
                subject TEXT NOT NULL,
                file_path TEXT NOT NULL,
                source_url TEXT DEFAULT '',
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Safely migrate existing DBs that predate the source_url column
        cols = {
            row[1]
            for row in self.connection.execute("PRAGMA table_info(processed)").fetchall()
        }
        if "source_url" not in cols:
            self.connection.execute(
                "ALTER TABLE processed ADD COLUMN source_url TEXT DEFAULT ''"
            )

        self.connection.commit()

    def exists(self, fingerprint: str) -> bool:
        result = self.connection.execute(
            "SELECT 1 FROM processed WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        return result is not None

    def save(self, fingerprint: str, announcement, file_path: str):
        self.connection.execute(
            """
            INSERT OR IGNORE INTO processed
            (fingerprint, symbol, source, subject, file_path, source_url)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                fingerprint,
                announcement.symbol,
                announcement.source,
                announcement.subject,
                file_path,
                getattr(announcement, "attachment_url", ""),
            ),
        )
        self.connection.commit()

    def get_source_metadata(self, file_stem: str) -> dict[str, str]:
        row = self.connection.execute(
            "SELECT source, source_url FROM processed WHERE file_path LIKE ? LIMIT 1",
            (f"%{file_stem}%",),
        ).fetchone()
        if not row:
            return {"source": "NSE", "source_url": ""}
        return {"source": row[0] or "NSE", "source_url": row[1] or ""}

    def close(self):
        self.connection.close()