"""
Ingestion queue — a single-worker, debounced work queue in front of the pipeline.

The watcher used to call pipeline.process_file() directly on its own thread.
That blocked the watcher during the (slow) embed+extract work, and a text
editor's multi-write save fired several on_modified events that each kicked off
a full re-ingest.

This queue fixes both:
  * submit() returns immediately (watcher never blocks),
  * rapid re-submits of the same path collapse into one run (debounce),
  * a single worker processes files serially, so the shared embedding/LLM
    models are never driven concurrently.
"""

import time
import threading


class IngestionQueue:
    def __init__(self, pipeline, debounce_seconds: float = 1.0):
        self._pipeline = pipeline
        self._debounce = debounce_seconds
        # path -> (action, due_time). A dict means repeat submits coalesce.
        self._pending: dict[str, tuple[str, float]] = {}
        self._cv = threading.Condition()
        self._stopped = False
        self._worker = threading.Thread(target=self._run, daemon=True,
                                        name="ingestion-queue")
        self._worker.start()

    def submit(self, path: str, action: str = "process"):
        """Queue a path for processing or deletion. Non-blocking.

        A later submit for the same path overrides the action and pushes the
        debounce window out, so a burst of edits results in one final run.
        """
        with self._cv:
            self._pending[path] = (action, time.time() + self._debounce)
            self._cv.notify()

    def stop(self):
        with self._cv:
            self._stopped = True
            self._cv.notify_all()

    def _next_due(self):
        """Return (path, action) for the earliest due item, or (None, None)."""
        now = time.time()
        ready = [(due, p, act) for p, (act, due) in self._pending.items() if due <= now]
        if not ready:
            return None, None
        ready.sort()
        _, path, action = ready[0]
        del self._pending[path]
        return path, action

    def _seconds_until_next(self):
        if not self._pending:
            return None
        return max(0.0, min(due for _, due in self._pending.values()) - time.time())

    def _run(self):
        while True:
            with self._cv:
                while not self._stopped:
                    path, action = self._next_due()
                    if path is not None:
                        break
                    wait = self._seconds_until_next()
                    self._cv.wait(timeout=wait if wait is not None else None)
                if self._stopped:
                    return
            # Execute outside the lock so submit() never blocks on processing.
            try:
                if action == "delete":
                    self._pipeline.delete_file(path)
                else:
                    self._pipeline.process_file(path)
            except Exception as e:
                print(f"[IngestionQueue] Error handling {action} for {path}: {e}")
