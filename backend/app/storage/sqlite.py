import sqlite3
import os
import json
import uuid
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

            # Table to track file ingestion status (existing)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE,
                    file_type TEXT,
                    status TEXT, 
                    ingested_at TIMESTAMP
                )
            """)

            # Chat sessions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    last_message_at TIMESTAMP NOT NULL
                )
            """)

            # Chat messages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sources TEXT DEFAULT '[]',
                    timestamp TIMESTAMP NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
                )
            """)

            # Tracked folders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tracked_folders (
                    path TEXT PRIMARY KEY,
                    added_at TIMESTAMP NOT NULL,
                    is_active INTEGER DEFAULT 1
                )
            """)

            conn.commit()

    # ------------------------------------------------------------------
    # Document tracking (existing, enhanced)
    # ------------------------------------------------------------------

    def add_or_update_document(self, file_path: str, file_type: str, status: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO documents (file_path, file_type, status, ingested_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET 
                    file_type=excluded.file_type,
                    status=excluded.status, 
                    ingested_at=excluded.ingested_at
            """, (file_path, file_type, status, datetime.now()))
            conn.commit()

    def get_all_documents(self) -> list[dict]:
        """Return all tracked documents."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, file_path, file_type, status, ingested_at FROM documents ORDER BY ingested_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_document_status(self, file_path: str) -> str | None:
        """Get the ingestion status of a specific file."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM documents WHERE file_path = ?", (file_path,))
            row = cursor.fetchone()
            return row[0] if row else None

    def get_ingestion_stats(self) -> dict:
        """Return aggregate ingestion statistics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) as processing,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
                FROM documents
            """)
            row = cursor.fetchone()
            return {
                "total": row[0] or 0,
                "completed": row[1] or 0,
                "processing": row[2] or 0,
                "failed": row[3] or 0,
            }

    # ------------------------------------------------------------------
    # Chat session management
    # ------------------------------------------------------------------

    def create_session(self, title: str = "New Chat") -> str:
        """Create a new chat session and return its ID."""
        session_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO chat_sessions (id, title, created_at, last_message_at) VALUES (?, ?, ?, ?)",
                (session_id, title, now, now),
            )
            conn.commit()
        return session_id

    def add_message(self, session_id: str, role: str, content: str, sources: list | None = None):
        """Add a message to a chat session."""
        now = datetime.now().isoformat()
        sources_json = json.dumps(sources or [])
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO chat_messages (session_id, role, content, sources, timestamp) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, sources_json, now),
            )
            # Update the session's last_message_at
            cursor.execute(
                "UPDATE chat_sessions SET last_message_at = ? WHERE id = ?",
                (now, session_id),
            )
            # Auto-title: set title from first user message
            cursor.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE session_id = ?", (session_id,)
            )
            msg_count = cursor.fetchone()[0]
            if msg_count == 1 and role == "user":
                # Use the first ~80 chars of the user's first message as the title
                short_title = content[:80].strip()
                if len(content) > 80:
                    short_title += "…"
                cursor.execute(
                    "UPDATE chat_sessions SET title = ? WHERE id = ?",
                    (short_title, session_id),
                )
            conn.commit()

    def get_session_messages(self, session_id: str) -> list[dict]:
        """Get all messages in a session, ordered chronologically."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT role, content, sources, timestamp FROM chat_messages WHERE session_id = ? ORDER BY timestamp ASC",
                (session_id,),
            )
            messages = []
            for row in cursor.fetchall():
                msg = dict(row)
                msg["sources"] = json.loads(msg.get("sources", "[]"))
                messages.append(msg)
            return messages

    def list_sessions(self) -> list[dict]:
        """List all chat sessions, most recent first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, s.title, s.created_at, s.last_message_at,
                       (SELECT COUNT(*) FROM chat_messages WHERE session_id = s.id) AS message_count
                FROM chat_sessions s
                ORDER BY s.last_message_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def delete_session(self, session_id: str):
        """Delete a chat session and all its messages."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
            conn.commit()

    def session_exists(self, session_id: str) -> bool:
        """Check if a session exists."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM chat_sessions WHERE id = ?", (session_id,))
            return cursor.fetchone() is not None

    # ------------------------------------------------------------------
    # Tracked folders
    # ------------------------------------------------------------------

    def add_folder(self, path: str):
        """Register a folder for tracking."""
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO tracked_folders (path, added_at, is_active) VALUES (?, ?, 1)",
                (path, now),
            )
            conn.commit()

    def list_folders(self) -> list[dict]:
        """List all tracked folders."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT path, added_at, is_active FROM tracked_folders ORDER BY added_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def deactivate_folder(self, path: str):
        """Mark a folder as inactive (stop watching)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE tracked_folders SET is_active = 0 WHERE path = ?", (path,))
            conn.commit()

    def remove_folder(self, path: str):
        """Remove a folder from tracking entirely."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tracked_folders WHERE path = ?", (path,))
            conn.commit()