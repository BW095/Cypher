import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.queue import IngestionQueue


class DocumentHandler(FileSystemEventHandler):
    def __init__(self, pipeline: IngestionPipeline, queue: IngestionQueue):
        self.pipeline = pipeline
        self.queue = queue

    def _tracked(self, path: str) -> bool:
        _, ext = os.path.splitext(path)
        return ext.lower() in self.pipeline.dispatcher.processors

    def on_created(self, event):
        if not event.is_directory and self._tracked(event.src_path):
            print(f"New file detected via watch: {event.src_path}")
            self.queue.submit(event.src_path, "process")

    def on_modified(self, event):
        if not event.is_directory and self._tracked(event.src_path):
            print(f"File modified via watch: {event.src_path}")
            self.queue.submit(event.src_path, "process")

    def on_deleted(self, event):
        if not event.is_directory and self._tracked(event.src_path):
            print(f"File deleted via watch: {event.src_path}")
            # Purge its chunks, graph node/links, and tracking row so the AI
            # can no longer retrieve or cite a document that no longer exists.
            self.queue.submit(event.src_path, "delete")

    def on_moved(self, event):
        # A rename/move is a delete of the old path + create of the new one.
        if not event.is_directory:
            print(f"File moved via watch: {event.src_path} -> {event.dest_path}")
            if self._tracked(event.src_path):
                self.queue.submit(event.src_path, "delete")
            if self._tracked(event.dest_path):
                self.queue.submit(event.dest_path, "process")


class DirectoryWatcher:
    def __init__(self, directory_to_watch: str, pipeline: IngestionPipeline):
        self.directory = directory_to_watch
        self.pipeline = pipeline
        self.observer = Observer()
        # One serial, debounced worker in front of the pipeline.
        self.queue = IngestionQueue(pipeline)
        self._stop = False

    def _discover_and_sync_existing_files(self):
        """Crawls the folder on startup to catch files added while offline."""
        print("🔍 Scanning directory for existing or missed files...")
        valid_extensions = set(self.pipeline.dispatcher.processors.keys())

        for root, _, files in os.walk(self.directory):
            for file in files:
                _, ext = os.path.splitext(file)
                if ext.lower() in valid_extensions:
                    # Queue it; the pipeline's content-hash check skips files
                    # already ingested and unchanged.
                    self.queue.submit(os.path.join(root, file), "process")

    def start(self):
        # 1. Catch up on historical files first (queued, non-blocking)
        self._discover_and_sync_existing_files()

        # 2. Start live watching
        event_handler = DocumentHandler(self.pipeline, self.queue)
        self.observer.schedule(event_handler, self.directory, recursive=True)
        self.observer.start()
        print(f"✨ Live-watching directory for new changes: {self.directory}")

        try:
            while not self._stop:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.observer.stop()
            self.queue.stop()
        self.observer.join()

    def stop(self):
        """Signal the watch loop to exit (used by the /api/ingest/stop route)."""
        self._stop = True
        try:
            self.observer.stop()
            self.queue.stop()
        except Exception:
            pass