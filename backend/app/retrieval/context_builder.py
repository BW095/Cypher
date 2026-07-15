"""
Context Builder — fuses vector search results and graph context into
a single, LLM-ready context string.

Handles deduplication, ranking, and context window management so the
LLM receives the most relevant information within its token budget.
"""

import os
from app.config import RetrievalConfig


class ContextBuilder:
    def __init__(self, max_context_chars: int | None = None):
        self.max_context_chars = max_context_chars or RetrievalConfig.MAX_CONTEXT_CHARS

    def build(
        self,
        vector_chunks: list[dict],
        graph_context: dict,
    ) -> str:
        """Combine vector chunks and graph context into a formatted context string.

        Args:
            vector_chunks: list of {text, score, source, file_type, metadata}
            graph_context: {entities: [...], relationships: [...], source_documents: [...]}

        Returns:
            A formatted context string ready for the LLM prompt.
        """
        sections = []

        # --- Section 1: Relevant Document Chunks (from vector search) ---
        if vector_chunks:
            chunk_section = self._format_vector_chunks(vector_chunks)
            sections.append(chunk_section)

        # --- Section 2: Knowledge Graph Context ---
        if graph_context and graph_context.get("entities"):
            graph_section = self._format_graph_context(graph_context)
            sections.append(graph_section)

        if not sections:
            return "No relevant context was found in the knowledge base."

        combined = "\n\n".join(sections)

        # Truncate to fit context window budget
        if len(combined) > self.max_context_chars:
            combined = combined[:self.max_context_chars]
            # Try to cut at the last complete line
            last_newline = combined.rfind("\n")
            if last_newline > self.max_context_chars * 0.5:
                combined = combined[:last_newline]
            combined += "\n[... context truncated for length ...]"

        return combined

    def _format_vector_chunks(self, chunks: list[dict]) -> str:
        """Format vector search results as a numbered context block."""
        lines = ["=== RELEVANT DOCUMENT EXCERPTS ==="]

        # Deduplicate by source + rough text overlap
        seen_sources = {}
        deduped = []
        for chunk in chunks:
            source = chunk.get("source", "unknown")
            text = chunk.get("text", "").strip()

            # Skip near-duplicate chunks from the same source
            if source in seen_sources:
                prev_text = seen_sources[source]
                # Simple overlap check: if >60% of the shorter text appears in the longer
                shorter = min(prev_text, text, key=len)
                longer = max(prev_text, text, key=len)
                if shorter and shorter in longer:
                    continue

            seen_sources[source] = text
            deduped.append(chunk)

        for i, chunk in enumerate(deduped, 1):
            source = chunk.get("source", "unknown")
            file_type = chunk.get("file_type", "")
            score = chunk.get("score", 0.0)
            text = chunk.get("text", "").strip()

            source_label = os.path.basename(source)
            if file_type:
                source_label += f" ({file_type})"

            lines.append(f"\n[Source {i}: {source_label} | relevance: {score:.2f}]")
            lines.append(text)

        return "\n".join(lines)

    def _format_graph_context(self, graph_context: dict) -> str:
        """Format knowledge graph entities and relationships as context."""
        lines = ["=== KNOWLEDGE GRAPH CONTEXT ==="]

        entities = graph_context.get("entities", [])
        relationships = graph_context.get("relationships", [])
        source_docs = graph_context.get("source_documents", [])

        # Build a lookup for entity names by ID
        entity_names = {e.get("id", ""): e.get("name", "") for e in entities}

        # Format entities
        for entity in entities:
            name = entity.get("name", "")
            etype = entity.get("type", "Unknown")
            desc = entity.get("description", "")
            line = f"Entity: {name} ({etype})"
            if desc:
                line += f" — {desc}"
            lines.append(line)

        # Format relationships as readable sentences
        if relationships:
            lines.append("\nRelationships:")
            for rel in relationships:
                src = entity_names.get(rel.get("source", ""), rel.get("source", "?"))
                tgt = entity_names.get(rel.get("target", ""), rel.get("target", "?"))
                rtype = rel.get("type", "RELATED_TO")
                lines.append(f"  {src} --[{rtype}]--> {tgt}")

        # Mention source documents
        if source_docs:
            doc_names = [os.path.basename(d) for d in source_docs]
            lines.append(f"\nMentioned in: {', '.join(doc_names)}")

        return "\n".join(lines)

    def extract_source_references(self, vector_chunks: list[dict]) -> list[dict]:
        """Extract deduplicated source references for API response."""
        sources = []
        seen = set()

        for chunk in vector_chunks:
            source = chunk.get("source", "unknown")
            if source not in seen:
                seen.add(source)
                sources.append({
                    "file_path": source,
                    "file_type": chunk.get("file_type", ""),
                    "chunk_text": chunk.get("text", "")[:200],  # Preview
                    "relevance_score": chunk.get("score", 0.0),
                })

        return sources
