import os
import sys
import time
import sqlite3
from qdrant_client import QdrantClient
from neo4j import GraphDatabase

# Ensure the backend directory is in the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.watcher import DirectoryWatcher


def purge_databases():
    print("🧹 Starting database purge for a clean test run...")

    # 1. Clear SQLite Trackers
    db_path = "./data/app.db"
    if os.path.exists(db_path):
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DROP TABLE IF EXISTS documents")
                conn.commit()
            print("  ✅ SQLite 'documents' table cleared.")
        except Exception as e:
            print(f"  ❌ Failed to clear SQLite: {e}")
    else:
        print("  ℹ️ SQLite file not found, skipping.")

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


def main():
    # Target testing folder configuration
    TEST_DIR = "/home/bw/CODES/test"

    if not os.path.exists(TEST_DIR):
        print(f"❌ Error: Target testing directory '{TEST_DIR}' does not exist.")
        return

    print("==================================================")
    print("🚀 Initializing Fresh Industrial AI Brain Test Run")
    print("==================================================")

    # Execute database cleanup routine
    purge_databases()

    try:
        print("🔧 Initializing storage layers and processing pipeline...")
        pipeline = IngestionPipeline()

        print("👀 Initializing folder scanner and live directory watcher...")
        watcher = DirectoryWatcher(directory_to_watch=TEST_DIR, pipeline=pipeline)

        print("\n✅ All layers successfully initialized!")
        print(f"Now processing existing files and live monitoring: {TEST_DIR}")
        print("Press Ctrl+C to terminate the test run.")
        print("==================================================\n")

        # Fires off discovery of existing files, then hangs to watch live events
        watcher.start()

    except Exception as e:
        print(f"\n❌ Pipeline Execution Failed: {str(e)}")
        print("Ensure local Docker containers (Qdrant, Neo4j) are up and running.")


if __name__ == "__main__":
    main()