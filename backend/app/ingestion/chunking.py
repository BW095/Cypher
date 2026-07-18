"""
Sentence- and paragraph-aware chunker.

The previous implementation sliced the text every N characters, which cut
words and sentences in half — hurting both embedding quality and the
readability of cited excerpts. This version accumulates whole sentences up
to a size budget, keeps a sentence-level overlap between consecutive chunks
for context continuity, and never splits inside a word.
"""

import re
from app.ingestion.canonical_document import CanonicalDocument


class Chunker:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 150):
        # Sizes are in characters (a reasonable proxy for tokens for BGE).
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    # Split on sentence boundaries (., !, ?) followed by whitespace, while
    # keeping the delimiter. Newlines also act as soft boundaries.
    _SENT_SPLIT = re.compile(r'(?<=[.!?])\s+|\n{2,}')

    def _split_sentences(self, text: str) -> list[str]:
        pieces = []
        for para in re.split(r'\n{2,}', text):
            para = para.strip()
            if not para:
                continue
            for sent in self._SENT_SPLIT.split(para):
                sent = sent.strip()
                if sent:
                    pieces.append(sent)
        return pieces

    def _hard_wrap(self, sentence: str) -> list[str]:
        """Split a single over-long sentence on word boundaries as a fallback."""
        words = sentence.split()
        out, cur = [], ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > self.chunk_size:
                out.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            out.append(cur)
        return out

    def chunk_document(self, document: CanonicalDocument) -> list:
        text = document.text or ""
        if not text.strip():
            return []

        # Build the sentence list, hard-wrapping any sentence that alone
        # exceeds the budget (e.g. a giant table row or URL).
        sentences = []
        for s in self._split_sentences(text):
            sentences.extend(self._hard_wrap(s) if len(s) > self.chunk_size else [s])

        chunks = []
        cur: list[str] = []
        cur_len = 0

        def flush():
            if cur:
                chunks.append(" ".join(cur).strip())

        for sent in sentences:
            add_len = len(sent) + (1 if cur else 0)
            if cur and cur_len + add_len > self.chunk_size:
                flush()
                # Start the next chunk with a tail overlap for continuity.
                overlap, o_len = [], 0
                for prev in reversed(cur):
                    if o_len + len(prev) > self.chunk_overlap:
                        break
                    overlap.insert(0, prev)
                    o_len += len(prev) + 1
                cur = overlap[:]
                cur_len = sum(len(x) + 1 for x in cur)
            cur.append(sent)
            cur_len += add_len
        flush()

        base_meta = {
            "source": document.file_path,
            "file_type": document.file_type,
            **document.metadata,
        }
        return [
            {
                "text": ctext,
                "metadata": {**base_meta, "chunk_index": i},
            }
            for i, ctext in enumerate(chunks)
            if ctext.strip()
        ]
