import sqlite3
import os
from datetime import datetime

class SQLiteStorage:
    def __init__(self, db_path: str = "./data/app.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
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