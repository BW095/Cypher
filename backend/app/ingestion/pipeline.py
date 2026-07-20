# backend/app/ingestion/pipeline.py
import os
import sys
import hashlib
import traceback
from app.ingestion.dispatcher import Dispatcher
from app.ingestion.chunking import Chunker
from app.ai.embeddings import BGEWrapper
from app.storage.qdrant import QdrantStorage
from app.storage.sqlite import SQLiteStorage
from app.storage.neo4j import Neo4jStorage  # Ensure this is imported
from app.ai.entity_extractor import EntityExtractor


# Hard ceiling on chunks per document (embedding is CPU-bound and serial).
_MAX_CHUNKS_PER_DOC = int(os.getenv("MAX_CHUNKS_PER_DOC", "500"))


def _hash_file(file_path: str) -> str:
    """Content hash used to skip re-ingesting unchanged files."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class IngestionPipeline:
    def __init__(self):
        self.dispatcher = Dispatcher()
        self.chunker = Chunker()
        self.tracker = SQLiteStorage()
        self.embedding_model = BGEWrapper()
        self.qdrant_db = QdrantStorage()
        self.neo4j_db = Neo4jStorage()
        self.entity_extractor = EntityExtractor()
    def process_file(self, file_path: str):
        try:
            print(f"Starting pipeline for: {file_path}")
            sys.stdout.flush()

            # 0. Skip unchanged files. The watcher fires on_modified for many
            #    non-content events (metadata, access time); re-embedding an
            #    unchanged file wastes minutes of model time for nothing.
            try:
                content_hash = _hash_file(file_path)
            except OSError as e:
                print(f"  Could not read {file_path} ({e}) — skipping.")
                return
            if self.tracker.get_document_status(file_path) == "completed" \
                    and self.tracker.get_document_hash(file_path) == content_hash:
                print(f"  Unchanged since last ingest — skipping: {file_path}")
                return

            # 1. Mark as processing
            self.tracker.add_or_update_document(file_path, "unknown", "processing")

            # 1b. Clear any prior data for this file so re-ingestion doesn't
            #     leave duplicate chunks in Qdrant or stale links in Neo4j.
            try:
                self.qdrant_db.delete_by_source(file_path)
                self.neo4j_db.delete_document(file_path)
            except Exception as e:
                print(f"  Warning: could not clear previous data for {file_path}: {e}")

            # 2. Extract content
            processor = self.dispatcher.get_processor(file_path)
            canonical_doc = processor.process(file_path)

            # Update file type in tracker
            self.tracker.add_or_update_document(file_path, canonical_doc.file_type, "processing")

            # 3. Chunk the text
            chunks = self.chunker.chunk_document(canonical_doc)

            # Safety net: no single document should produce thousands of chunks
            # (a huge table or dump would otherwise stall the whole queue on the
            # CPU embed step). Processors like Excel summarize large data, but
            # cap here too so any pathological file stays bounded.
            if len(chunks) > _MAX_CHUNKS_PER_DOC:
                print(f"  Capping {len(chunks)} chunks -> {_MAX_CHUNKS_PER_DOC} "
                      f"for {file_path} (very large document).")
                chunks = chunks[:_MAX_CHUNKS_PER_DOC]

            if chunks:
                # 4. Generate Embeddings
                chunk_texts = [chunk["text"] for chunk in chunks]
                embeddings = self.embedding_model.embed_batch(chunk_texts)

                # 5. Store in Vector DB
                self.qdrant_db.store_chunks(chunks, embeddings)
                canonical_doc = self.entity_extractor.process_document(canonical_doc)

            # 6. FIX: Store Entities and Relationships in Neo4j Graph
            self.neo4j_db.store_graph(canonical_doc)
            # New entities were added — drop the graph retriever's name cache
            # so they're searchable on the very next query.
            try:
                self.neo4j_db.invalidate_entity_cache()
            except Exception:
                pass

            # 7. Mark as completed and record the content hash for change detection
            self.tracker.add_or_update_document(file_path, canonical_doc.file_type, "completed")
            self.tracker.set_document_hash(file_path, content_hash)
            print(f"Successfully processed and stored: {file_path}")
            sys.stdout.flush()

        except Exception as e:
            self.tracker.add_or_update_document(file_path, "unknown", "failed")
            print(f"Ingestion failed for {file_path}. Error: {str(e)}")
            traceback.print_exc()

    def delete_file(self, file_path: str):
        """Remove a file's data from every store after it's deleted from disk.

        Clears vector chunks (Qdrant), the Document node and its links plus any
        now-orphaned entities (Neo4j), and the tracking row (SQLite), then
        invalidates the entity-name cache. Safe to call for files that were
        never fully ingested.
        """
        print(f"Removing deleted file from all stores: {file_path}")
        sys.stdout.flush()
        try:
            self.qdrant_db.delete_by_source(file_path)
        except Exception as e:
            print(f"  Qdrant cleanup failed for {file_path}: {e}")
        try:
            self.neo4j_db.delete_document(file_path)
            self.neo4j_db.invalidate_entity_cache()
        except Exception as e:
            print(f"  Neo4j cleanup failed for {file_path}: {e}")
        try:
            self.tracker.remove_document(file_path)
        except Exception as e:
            print(f"  SQLite cleanup failed for {file_path}: {e}")