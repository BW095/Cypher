import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from app.ingestion.pipeline import IngestionPipeline


class DocumentHandler(FileSystemEventHandler):
    def __init__(self, pipeline: IngestionPipeline):
        self.pipeline = pipeline

    def on_created(self, event):
        if not event.is_directory:
            print(f"New file detected via watch: {event.src_path}")
            self.pipeline.process_file(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            print(f"File modified via watch: {event.src_path}")
            self.pipeline.process_file(event.src_path)


class DirectoryWatcher:
    def __init__(self, directory_to_watch: str, pipeline: IngestionPipeline):
        self.directory = directory_to_watch
        self.pipeline = pipeline
        self.observer = Observer()

    def _discover_and_sync_existing_files(self):
        """Crawls the folder on startup to catch files added while offline."""
        print("🔍 Scanning directory for existing or missed files...")
        valid_extensions = set(self.pipeline.dispatcher.processors.keys())

        for root, _, files in os.walk(self.directory):
            for file in files:
                _, ext = os.path.splitext(file)
                if ext.lower() in valid_extensions:
                    full_path = os.path.join(root, file)

                    # Optional: Query SQLite tracker here to skip if already 'completed'
                    # For now, let's pass it to the pipeline to safely process/update
                    try:
                        self.pipeline.process_file(full_path)
                    except Exception as e:
                        print(f"Skipping startup file {full_path}: {e}")

    def start(self):
        # 1. Catch up on historical files first
        self._discover_and_sync_existing_files()

        # 2. Start live watching
        event_handler = DocumentHandler(self.pipeline)
        self.observer.schedule(event_handler, self.directory, recursive=True)
        self.observer.start()
        print(f"✨ Live-watching directory for new changes: {self.directory}")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.observer.stop()
        self.observer.join()