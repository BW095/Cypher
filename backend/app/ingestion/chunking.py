from app.ingestion.canonical_document import CanonicalDocument


class Chunker:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 150):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_document(self, document: CanonicalDocument) -> list:
        text = document.text
        chunks = []

        # Basic character-level chunking
        for i in range(0, len(text), self.chunk_size - self.chunk_overlap):
            chunk_text = text[i:i + self.chunk_size]

            chunks.append({
                "text": chunk_text,
                "metadata": {
                    "source": document.file_path,
                    "file_type": document.file_type,
                    **document.metadata
                }
            })

        return chunks