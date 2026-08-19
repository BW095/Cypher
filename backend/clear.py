"""
Full reset — wipe every persistent store so the next run starts completely fresh.

Clears: all SQLite tables (chat history, documents, tracked folders) and their
AUTOINCREMENT counters, the local temp cache, the Qdrant vector collection, and
the entire Neo4j graph.

It preserves the SQLite *schema* and recreates an empty Qdrant collection, so a
running backend keeps working (dropping them made the API 500 / ingestion FAIL
until restart). It does NOT delete downloaded models (GGUF / HuggingFace cache).

Connection details come from config (env-overridable), so this also works inside
Docker. Run from the backend/ directory:  python clear.py
"""

import os
import shutil
import sqlite3

from qdrant_client import QdrantClient
from neo4j import GraphDatabase

from app.config import QdrantConfig, Neo4jConfig


def _clear_sqlite():
    """Empty every table (schema kept) and reset id counters."""
    from app.storage.sqlite import SQLiteStorage

    store = SQLiteStorage()          # ensures the schema exists; resolves the real path
    db_path = store.db_path
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            tables = [
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            for t in tables:
                conn.execute(f'DELETE FROM "{t}"')
            # Reset AUTOINCREMENT so ids start from 1 again (truly fresh).
            try:
                conn.execute("DELETE FROM sqlite_sequence")
            except sqlite3.OperationalError:
                pass  # no AUTOINCREMENT tables yet
            conn.commit()
            conn.execute("VACUUM")
        print(f"  ✅ SQLite cleared: {', '.join(tables) or '(no tables)'} (schema preserved).")
    except Exception as e:
        print(f"  ❌ Failed to clear SQLite: {e}")
        return

    # Clear the transient processing cache next to the DB (never the DB itself).
    temp_dir = os.path.join(os.path.dirname(db_path), "temp")
    if os.path.isdir(temp_dir):
        for name in os.listdir(temp_dir):
            p = os.path.join(temp_dir, name)
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
        print("  ✅ Cleared data/temp cache.")


def _clear_qdrant():
    """Delete and recreate an empty collection (keeps a live backend valid)."""
    try:
        client = QdrantClient(host=QdrantConfig.HOST, port=QdrantConfig.PORT)
        name = QdrantConfig.COLLECTION_NAME
        if any(c.name == name for c in client.get_collections().collections):
            client.delete_collection(collection_name=name)
            print(f"  ✅ Qdrant collection '{name}' deleted.")
        # Recreate empty with the right vector config so ingestion works at once.
        from app.storage.qdrant import QdrantStorage
        QdrantStorage(host=QdrantConfig.HOST, port=QdrantConfig.PORT, collection_name=name)
        print(f"  ✅ Qdrant collection '{name}' recreated empty.")
    except Exception as e:
        print(f"  ❌ Failed to clear Qdrant: {e}")


def _clear_neo4j():
    """Delete every node and relationship."""
    try:
        driver = GraphDatabase.driver(
            Neo4jConfig.URI, auth=(Neo4jConfig.USER, Neo4jConfig.PASSWORD)
        )
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            session.run("MATCH (n) DETACH DELETE n")
        driver.close()
        print("  ✅ Neo4j graph completely wiped clean.")
    except Exception as e:
        print(f"  ❌ Failed to clear Neo4j: {e}")


def _clear_uploads():
    """Delete every file uploaded through the chat/upload API.

    Uploaded documents are saved under data/uploads/ and ingested into the
    stores above. Wiping only the databases leaves these source files on
    disk, so a 'reset' still shows uploaded files sitting in the folder.
    """
    from app.api.upload import UPLOAD_DIR

    if not os.path.isdir(UPLOAD_DIR):
        return
    removed = 0
    for name in os.listdir(UPLOAD_DIR):
        p = os.path.join(UPLOAD_DIR, name)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
            removed += 1
        except OSError as e:
            print(f"  ⚠️  Could not remove {p}: {e}")
    print(f"  ✅ Cleared uploads directory ({removed} item(s) removed).")


def _flush_backend_caches():
    """Best-effort: tell a running backend to drop its in-memory caches.

    The graph retriever caches entity names / document paths for ~60s. Since
    this script wipes the databases from a separate process, those caches keep
    the just-deleted files 'alive' until the TTL lapses — the chat then still
    references documents that no longer exist. Hitting this endpoint clears the
    caches immediately, so no backend restart is needed. Silently ignored if
    the backend isn't running.
    """
    import json
    import urllib.request
    from app.config import ServerConfig

    host = os.getenv("SERVER_HOST", "127.0.0.1")
    if host in ("0.0.0.0", ""):
        host = "127.0.0.1"
    url = f"http://{host}:{ServerConfig.PORT}/api/ingest/flush-caches"
    try:
        req = urllib.request.Request(url, data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=3) as resp:
            json.loads(resp.read() or b"{}")
        print("  ✅ Flushed running backend's in-memory caches.")
    except Exception:
        print("  ℹ️  Backend not reachable — restart it to clear in-memory caches.")


def purge_databases():
    print("🧹 Full reset — wiping all databases and caches for a fresh start...")
    _clear_sqlite()
    _clear_qdrant()
    _clear_neo4j()
    _clear_uploads()
    _flush_backend_caches()
    print("--------------------------------------------------")
    print("✨ Reset complete.")


if __name__ == "__main__":
    purge_databases()
