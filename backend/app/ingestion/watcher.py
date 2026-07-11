import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from app.ingestion.pipeline import IngestionPipeline


class DocumentHandler(FileSystemEventHandler):
    def __init__(self, pipeline: IngestionPipeline):
        self.pipeline = pipeline

    def on_created(self, event):
        if not event.is_directory:
            print(f"New file detected: {event.src_path}")
            self.pipeline.process_file(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            print(f"File modified: {event.src_path}")
            self.pipeline.process_file(event.src_path)


class DirectoryWatcher:
    def __init__(self, directory_to_watch: str, pipeline: IngestionPipeline):
        self.directory = directory_to_watch
        self.pipeline = pipeline
        self.observer = Observer()

    def start(self):
        event_handler = DocumentHandler(self.pipeline)
        self.observer.schedule(event_handler, self.directory, recursive=True)
        self.observer.start()
        print(f"Watching directory for changes: {self.directory}")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.observer.stop()
        self.observer.join()