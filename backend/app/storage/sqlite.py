import sqlite3
import os
from datetime import datetime

# Resolve the backend directory (two levels up from this file: storage/ -> app/ -> backend/)
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_DB_PATH = os.path.join(_BACKEND_DIR, "data", "app.db")


class SQLiteStorage:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or _DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Table to track file ingestion status
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE,
                    file_type TEXT,
                    status TEXT, 
                    ingested_at TIMESTAMP
                )
            """)
            conn.commit()

    def add_or_update_document(self, file_path: str, file_type: str, status: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO documents (file_path, file_type, status, ingested_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET 
                    file_type=excluded.file_type, -- FIX: Update file_type here
                    status=excluded.status, 
                    ingested_at=excluded.ingested_at
            """, (file_path, file_type, status, datetime.now()))
            conn.commit()