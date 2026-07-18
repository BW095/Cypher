import os
import sqlite3
from qdrant_client import QdrantClient
from neo4j import GraphDatabase

def purge_databases():
    print("🧹 Starting database purge for a clean test run...")

    # 1. Clear SQLite document tracker.
    #    IMPORTANT: clear the ROWS, don't DROP the table. Dropping it left the
    #    schema missing, so a running backend 500'd with "no such table:
    #    documents" until restart. Ensuring the schema first (via SQLiteStorage)
    #    then DELETE keeps the DB valid for a live backend.
    db_path = "./data/app.db"
    try:
        from app.storage.sqlite import SQLiteStorage
        SQLiteStorage(db_path)  # _init_db creates any missing tables (IF NOT EXISTS)
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM documents")
            conn.commit()
        print("  ✅ SQLite 'documents' rows cleared (schema preserved).")
    except Exception as e:
        print(f"  ❌ Failed to clear SQLite: {e}")

    # 2. Clear Qdrant Collection
    try:
        qdrant_client = QdrantClient(host="localhost", port=6333)
        collection_name = "industrial_knowledge"
        collections = qdrant_client.get_collections().collections
        if any(c.name == collection_name for c in collections):
            qdrant_client.delete_collection(collection_name=collection_name)
            print(f"  ✅ Qdrant collection '{collection_name}' deleted.")
        else:
            print("  ℹ️ Qdrant collection did not exist, skipping deletion.")
    except Exception as e:
        print(f"  ❌ Failed to clear Qdrant: {e}")

    # 3. Clear Neo4j Graph
    try:
        # Match credentials from your Neo4jStorage initialization defaults
        driver = GraphDatabase.driver("neo4j://localhost:7687", auth=("neo4j", "password"))
        with driver.session(database="neo4j") as session:
            # Wipe all nodes and their connecting relationships completely
            session.run("MATCH (n) DETACH DELETE n")
        driver.close()
        print("  ✅ Neo4j database completely wiped clean.")
    except Exception as e:
        print(f"  ❌ Failed to clear Neo4j: {e}")

    print("--------------------------------------------------\n")
    print("✨ Database purge complete!")

if __name__ == "__main__":
    purge_databases()
