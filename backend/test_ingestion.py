import os
import sys
import time

# Ensure the backend directory is in your Python path so imports work smoothly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.watcher import DirectoryWatcher


def main():
    # 1. Update this path to point exactly to your external test folder
    TEST_DIR = "/home/bw/CODES/test"

    if not os.path.exists(TEST_DIR):
        print(f"❌ Error: The directory '{TEST_DIR}' does not exist.")
        print("Please provide a valid path to your test folder.")
        return

    print("==================================================")
    print("🚀 Initializing Industrial AI Brain Ingestion Test")
    print("==================================================")

    try:
        # 2. Instantiate the pipeline (this will connect to Qdrant, Neo4j, and SQLite)
        pipeline = IngestionPipeline()

        # 3. Instantiate the watcher with your pipeline
        watcher = DirectoryWatcher(directory_to_watch=TEST_DIR, pipeline=pipeline)

        print("\n✅ All storage and AI layers initialized successfully!")
        print(f"Monitoring folder: {TEST_DIR}")
        print("Drop a new file into that folder or edit an existing one to trigger the pipeline...")
        print("Press Ctrl+C to stop the test.")
        print("--------------------------------------------------\n")

        # 4. Start the blocking watch loop
        watcher.start()

    except Exception as e:
        print(f"\n❌ Initialization Failed: {str(e)}")
        print("Make sure Qdrant, Neo4j, and SQLite are running locally and accessible.")


if __name__ == "__main__":
    main()