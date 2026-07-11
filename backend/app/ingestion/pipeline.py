from app.ingestion.dispatcher import Dispatcher
from app.ingestion.chunking import Chunker
from app.ai.embeddings import BGEWrapper
from app.storage.qdrant import QdrantStorage
from app.storage.sqlite import SQLiteStorage

class IngestionPipeline:
    def __init__(self):
        self.dispatcher = Dispatcher()
        self.chunker = Chunker()
        self.tracker = SQLiteStorage()
        self.embedding_model = BGEWrapper()
        self.qdrant_db = QdrantStorage()

    def process_file(self, file_path: str):
        try:
            print(f"Starting pipeline for: {file_path}")

            # 1. Mark as processing
            self.tracker.add_or_update_document(file_path, "unknown", "processing")

            # 2. Extract content
            processor = self.dispatcher.get_processor(file_path)
            canonical_doc = processor.process(file_path)

            # Update file type in tracker
            self.tracker.add_or_update_document(file_path, canonical_doc.file_type, "processing")

            # 3. Chunk the text
            chunks = self.chunker.chunk_document(canonical_doc)

            if chunks:
                # 4. Generate Embeddings
                chunk_texts = [chunk["text"] for chunk in chunks]
                embeddings = self.embedding_model.embed_batch(chunk_texts)

                # 5. Store in Vector DB
                self.qdrant_db.store_chunks(chunks, embeddings)

            # 6. Mark as completed
            self.tracker.add_or_update_document(file_path, canonical_doc.file_type, "completed")
            print(f"Successfully processed and stored: {file_path}")

        except Exception as e:
            self.tracker.add_or_update_document(file_path, "unknown", "failed")
            print(f"Ingestion failed for {file_path}. Error: {str(e)}")

        except Exception as e:
            print(f"Ingestion failed for {file_path}. Error: {str(e)}")