import json
import sqlite3
from pathlib import Path


class History:
    def __init__(self, path, seed_directories=()):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.database = sqlite3.connect(path)
        self.database.execute("CREATE TABLE IF NOT EXISTS completed (id TEXT PRIMARY KEY, file TEXT NOT NULL, bytes INTEGER NOT NULL, md5 TEXT NOT NULL)")
        for directory in seed_directories:
            if not directory.exists():
                continue
            for metadata in directory.glob("*.json"):
                if metadata.name.endswith(".validation.json"):
                    continue
                try:
                    saved = json.loads(metadata.read_text(encoding="utf-8-sig"))
                    if Path(saved["file"]).name != saved["file"]:
                        continue
                    media = directory / saved["file"]
                    if saved.get("size_verified") and media.is_file() and media.stat().st_size == saved["bytes"]:
                        self.record(str(saved["aweme_id"]), media, saved)
                except (OSError, ValueError, KeyError, TypeError):
                    continue

    def contains(self, work_id):
        row = self.database.execute("SELECT file, bytes FROM completed WHERE id=?", (work_id,)).fetchone()
        return bool(row and Path(row[0]).is_file() and Path(row[0]).stat().st_size == row[1])

    def record(self, work_id, path, saved):
        self.database.execute("INSERT OR REPLACE INTO completed VALUES (?, ?, ?, ?)",
                              (work_id, str(path.resolve()), saved["bytes"], saved["md5"]))
        self.database.commit()

    def close(self):
        self.database.close()
