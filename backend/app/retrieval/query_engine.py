"""
Query Engine — the main orchestrator for the retrieval pipeline.

Ties together vector retrieval, graph retrieval, context building,
and LLM generation into a single query() call.

This is the primary interface used by the API routes.
"""

import os
import re
import sys
from app.retrieval.vector_retriever import VectorRetriever
from app.retrieval.graph_retriever import GraphRetriever
from app.retrieval.context_builder import ContextBuilder
from app.ai.llm import LLMWrapper
from app.ai.embeddings import BGEWrapper
from app.storage.qdrant import QdrantStorage
from app.storage.neo4j import Neo4jStorage
from app.config import RetrievalConfig, LLMConfig


# System prompt for the industrial AI assistant
_SYSTEM_PROMPT = """You are Cypher, an expert AI knowledge copilot for an industrial company. You answer operational, maintenance, engineering, and compliance questions using the company's internal documents (manuals, work orders, inspection records, P&IDs, regulatory documents) provided as context.

CITATION RULES (mandatory):
- You MUST explicitly name the source files in your text.
- Every factual claim MUST cite the source document it came from, inline, using the exact file name in square brackets, e.g.: The pump showed abnormal vibration [pump_maintenance_log.pdf].
- Use the file names exactly as shown in the context labels — never invent, shorten, or rename them.
- If several documents support a claim, cite each: [report_a.pdf][manual_b.docx].
- End your response with a "**Sources:**" section that lists each unique file cited as a bullet point.

ANSWER RULES:
- Use ONLY the provided context. Never make up facts, values, tag numbers, or dates.
- Be precise with technical details: equipment tags, parameter values, units, standard/regulation numbers must be copied exactly.
- If the context is insufficient or conflicting, say exactly what is missing or conflicting — do not guess. Provide a confidence assessment when appropriate.
- When relevant, add a short "**Recommendation:**" with concrete next actions (inspection, maintenance, compliance step).
- For safety- or compliance-critical topics (regulations, failure risks, hazardous procedures), explicitly identify **Compliance Gaps** if current procedures or states violate stated norms.
- Structure longer answers with short markdown headings or bullet points; keep simple answers to a short paragraph."""


class QueryEngine:
    """Main query engine that orchestrates the full retrieval + generation pipeline."""

    def __init__(
        self,
        embedding_model: BGEWrapper = None,
        qdrant_db: QdrantStorage = None,
        neo4j_db: Neo4jStorage = None,
        llm: LLMWrapper = None,
    ):
        # Shared instances — should be injected from main.py for singleton behavior
        self.embedding_model = embedding_model or BGEWrapper()
        self.qdrant_db = qdrant_db or QdrantStorage()
        self.neo4j_db = neo4j_db or Neo4jStorage()
        self.llm = llm or LLMWrapper()

        # Sub-components
        self.vector_retriever = VectorRetriever(self.embedding_model, self.qdrant_db)
        self.graph_retriever = GraphRetriever(self.neo4j_db)
        self.context_builder = ContextBuilder()

    def query(self, user_message: str, chat_history: list[dict] | None = None) -> dict:
        """Process a user query through the full pipeline.

        Args:
            user_message: The user's question.
            chat_history: Previous messages as [{role, content}, ...] for context.

        Returns:
            {
                answer: str,
                sources: [{file_path, file_type, chunk_text, relevance_score}],
                entities_referenced: [str, ...]
            }
        """
        print(f"\n{'='*60}")
        print(f"[QueryEngine] Processing query: '{user_message[:100]}...'")
        print(f"{'='*60}")
        sys.stdout.flush()

        # 1. Vector retrieval — semantic search
        print("\n[QueryEngine] Step 1: Vector retrieval...")
        sys.stdout.flush()
        vector_chunks = self.vector_retriever.retrieve(user_message)

        # 2. Graph retrieval — entity-based search
        print("\n[QueryEngine] Step 2: Graph retrieval...")
        sys.stdout.flush()
        graph_context = self.graph_retriever.retrieve(user_message)

        # 3. Build context
        print("\n[QueryEngine] Step 3: Building context...")
        sys.stdout.flush()
        context = self.context_builder.build(vector_chunks, graph_context)

        # 4. Build the full message list for the LLM
        messages = self._build_messages(user_message, context, chat_history)

        # 5. Generate answer
        print("\n[QueryEngine] Step 4: Generating answer with LLM...")
        sys.stdout.flush()
        raw_answer = self.llm.generate_with_history(
            messages=messages,
            max_tokens=LLMConfig.MAX_TOKENS,
        )

        # 6. Clean the answer (strip thinking tags if present)
        answer = self._clean_answer(raw_answer)

        if not answer:
            answer = "I'm sorry, I wasn't able to generate a response. Please try rephrasing your question."

        # 7. Extract source references and entity names
        sources = self.context_builder.extract_source_references(vector_chunks, graph_context)
        self._mark_cited_sources(answer, sources)
        entities_referenced = [e.get("name", "") for e in graph_context.get("entities", [])]

        print(f"\n[QueryEngine] Done. Answer length: {len(answer)} chars, {len(sources)} sources cited.")
        sys.stdout.flush()

        return {
            "answer": answer,
            "sources": sources,
            "entities_referenced": entities_referenced,
        }

    def _build_messages(
        self,
        user_message: str,
        context: str,
        chat_history: list[dict] | None,
    ) -> list[dict]:
        """Assemble the full message list for the LLM.

        Structure:
            [system prompt] → [recent chat history] → [context + question]
        """
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]

        # Add recent chat history (trimmed to last N turns)
        if chat_history:
            max_turns = RetrievalConfig.MAX_HISTORY_TURNS * 2  # Each turn = user + assistant
            recent = chat_history[-max_turns:]
            for msg in recent:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                })

        # Add the current question with context
        user_content = f"""Based on the following context from the company's knowledge base, answer the user's question.
Remember: cite the exact file name in square brackets after every claim, and finish with a **Sources:** line.

{context}

--- USER QUESTION ---
{user_message}"""

        messages.append({"role": "user", "content": user_content})

        return messages

    @staticmethod
    def _mark_cited_sources(answer: str, sources: list[dict]):
        """Flag each source with whether the answer actually references it.

        The UI uses this to visually separate documents the model cited
        from documents that were merely retrieved.
        """
        answer_lower = answer.lower()
        for s in sources:
            base = os.path.basename(s.get("file_path", ""))
            stem = os.path.splitext(base)[0]
            s["cited"] = bool(base) and (
                base.lower() in answer_lower or
                (len(stem) > 3 and stem.lower() in answer_lower)
            )

    def _clean_answer(self, raw: str) -> str:
        """Strip Qwen3's <think>...</think> tags and clean up the response."""
        if not raw:
            return ""

        # Remove thinking blocks
        cleaned = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()

        return cleaned
