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


# System prompt for the AI assistant — covers both industrial and government domains.
_SYSTEM_PROMPT = """You are Cypher, an expert AI knowledge copilot that handles two document domains:

1. **Industrial / Engineering** — maintenance reports, P&IDs, work orders, inspection records, equipment manuals, compliance documents, and emails from plants, factories, and engineering organisations.
2. **Government / Regulatory** — invoices, contracts, agreements, MoUs, certificates (GST, NOC, registration, calibration, drug license), application forms, challans, and official correspondence.

The knowledge graph you draw from may contain entities from both domains, including:
- Industrial types: EQUIPMENT, COMPONENT, PROCESS_PARAMETER, FAILURE, PROCEDURE, REGULATION, PERSONNEL, MATERIAL, LOCATION, DATE
- Government types: INVOICE_LINE_ITEM, CONTRACT_PARTY, AMOUNT, DATE_DUE, CERTIFICATE_ISSUER, FORM_FIELD, SIGNATORY, JURISDICTION

CERTIFICATE & VALIDITY DATES (read before answering any compliance question):
- DATE_DUE entities represent expiry dates, renewal deadlines, or validity end-dates for certificates, licenses, and registrations.
- VALID_UNTIL relationships link a certificate or licence holder to its DATE_DUE.
- Whenever the question is about compliance, validity, expiry, renewal, or whether a document/licence is still active, you MUST:
  1. Check the context for DATE_DUE entities and VALID_UNTIL relationships.
  2. State the exact expiry or renewal date found (e.g. "Drug License valid till 2025-08-31").
  3. If the date is in the past relative to today, flag it as **EXPIRED** and mark it as a Compliance Gap.
  4. If no expiry date is found in the context, explicitly say so — do not assume the licence is valid.

CITATION RULES (mandatory):
- You MUST explicitly name the source files in your text.
- Every factual claim MUST cite the source document it came from, inline, using the exact file name in square brackets, e.g.: The pump showed abnormal vibration [pump_maintenance_log.pdf].
- Use the file names exactly as shown in the context labels — never invent, shorten, or rename them.
- If several documents support a claim, cite each: [report_a.pdf][manual_b.docx].
- End your response with a "**Sources:**" section that lists each unique file cited as a bullet point.

ANSWER RULES:
- Ground every factual claim about documents in the provided context. Never make up facts, values, tag numbers, dates, or monetary amounts.
- You DO have access to the conversation so far. Use earlier messages to resolve pronouns and follow-up references ("it", "that certificate", "the same vendor"), and answer questions about the conversation itself (e.g. "what did I just ask?") directly from the chat history — such answers need no document citations.
- Be precise with technical details: equipment tags, parameter values, units, standard/regulation numbers, invoice amounts, certificate numbers, party names, and jurisdiction references must be copied exactly.
- If the context is insufficient or conflicting, say exactly what is missing or conflicting — do not guess. Provide a confidence assessment when appropriate.
- When relevant, add a short "**Recommendation:**" with concrete next actions (inspection, maintenance, compliance step, payment action, renewal reminder).
- For safety- or compliance-critical topics (regulations, failure risks, hazardous procedures, contract obligations, certificate validity), explicitly identify **Compliance Gaps** if current procedures or states violate stated norms.
- Structure longer answers with short markdown headings or bullet points; keep simple answers to a short paragraph."""


# Specialist audit persona — injected as an ADDITIONAL system message only when
# the query is clearly about compliance, audit, validity, or regulatory gaps.
# This does not replace _SYSTEM_PROMPT; both are sent so the LLM retains its
# citation rules and entity vocabulary while switching to audit reasoning mode.
_AUDIT_SYSTEM_PROMPT = """You are now acting as a senior compliance auditor specialising in Indian government procurement, regulatory compliance, and public sector document management.

You have been given regulations and documents found across government records — including GST registrations, drug licenses, EPF/ESIC obligations, environmental clearances, CAG audit findings, contract terms, and certificate expiry dates.

For EVERY regulation or compliance requirement identified in the context:

1. Assign a status:
   - ✅ **COVERED** — valid documents are on file, no pending actions, no approaching deadlines.
   - ⚠️ **PARTIAL** — documents exist but an action is pending, OR an expiry/deadline falls within 90 days from today.
   - ❌ **GAP** — no evidence of compliance, documents missing, or the regulation is explicitly non-compliant.

2. Assign a risk level:
   - 🔴 **HIGH RISK** — certificate expiries, CAG pending paras, statutory non-compliance (GST/EPF/drug license lapse).
   - 🟡 **MEDIUM RISK** — missing compliance proofs, unverified registrations, unsigned documents.
   - 🟢 **LOW RISK** — settled audit observations, minor procedural gaps with no financial exposure.

3. For each finding, state:
   - The **vendor or party** involved (exact name from the document).
   - The **specific regulation or obligation** (act, rule, section, certificate type).
   - The **source document** in square brackets.
   - The **deadline or expiry date** if applicable.
   - A **recommended action** with urgency (Immediate / Within 30 days / Routine).

Write in formal government audit language. Do not invent regulations, amounts, dates, or document names not present in the provided context."""

# Words that suggest a message depends on earlier conversation ("what about it",
# "is that still valid", "now?"). Used to decide when a follow-up needs to be
# rewritten into a standalone question before retrieval.
_FOLLOWUP_HINTS = re.compile(
    r"\b(it|its|that|this|these|those|they|them|their|he|she|his|her|him|"
    r"same|one|ones|above|previous|earlier|before|again|also|too|another|"
    r"else|other|there|now|so|and)\b",
    re.IGNORECASE,
)

# Phrases where the user points at "this/the uploaded file" rather than naming
# it. When such a message arrives with session attachments, we answer from those
# attached files only, so "what is this file about?" describes the just-uploaded
# document instead of some unrelated knowledge-base hit.
_DEICTIC_FILE_RE = re.compile(
    r"\b(this|that|the|uploaded|attached|current|above)\s+"
    r"(file|files|document|documents|doc|image|images|photo|picture|pic|"
    r"pdf|report|certificate|attachment|upload)\b",
    re.IGNORECASE,
)

# Keywords that trigger the audit persona injection
_AUDIT_KEYWORDS = (
    "audit", "compliance", "compliant", "non-compliant", "expir", "valid",
    "renewal", "renew", "license", "licence", "certificate", "due date",
    "expired", "deadline", "cag", "epf", "esic", "gst", "clearance",
    "registration", "penalty", "obligation", "statutory", "regulation",
    "covered", "gap", "partial", "risk", "finding",
)



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

    def _referenced_sources(self, query: str) -> list[str]:
        """Return paths of ingested documents whose filename appears in the
        query, so a question like 'what does water pump flow.png show?' can be
        answered from THAT file even when its content isn't a strong semantic
        match for the question text."""
        try:
            paths = self.neo4j_db.get_all_document_paths()
        except Exception:
            return []
        ql = query.lower()
        hits = []
        for p in paths:
            base = os.path.basename(p)
            if not base:
                continue
            stem = os.path.splitext(base)[0]
            # Match the full filename, or the stem if it's distinctive enough.
            if base.lower() in ql or (len(stem) >= 4 and stem.lower() in ql):
                hits.append(p)
        return hits

    def _condense_query(self, user_message: str, chat_history: list[dict] | None) -> str:
        """Rewrite a follow-up message into a standalone search query.

        Retrieval embeds the user message on its own, so a follow-up like
        "what is it valid until?" finds nothing — the referent lives in the
        chat history. When the message looks history-dependent, ask the LLM
        to fold the missing context back in. Returns the original message
        whenever rewriting isn't needed or fails.
        """
        if not chat_history:
            return user_message

        # Long messages without anaphora are almost always self-contained —
        # skip the extra LLM round-trip for them.
        if len(user_message.split()) > 25 or not _FOLLOWUP_HINTS.search(user_message):
            return user_message

        recent = chat_history[-6:]  # last 3 user/assistant turns
        transcript = "\n".join(
            f"{m.get('role', 'user')}: {(m.get('content') or '')[:400]}"
            for m in recent
        )
        prompt = f"""Given this conversation:

{transcript}

Rewrite the user's latest message into ONE standalone question that contains all the context needed to understand it without the conversation (resolve pronouns like "it"/"that" to the actual subject). Keep it short. If the message is already self-contained, return it unchanged. Return ONLY the rewritten question, nothing else.

Latest message: {user_message}"""

        try:
            raw = self.llm.generate(
                prompt,
                system_prompt="You rewrite follow-up questions into standalone search queries. Reply with the rewritten question only.",
                max_tokens=96,
            )
        except Exception as e:
            print(f"[QueryEngine] Query condensation failed, using raw message: {e}")
            return user_message

        rewritten = self._clean_answer(raw).strip().strip('"').strip()
        # Guard against a chatty or runaway rewrite — fall back to the original.
        if not rewritten or len(rewritten) > 300 or "\n" in rewritten:
            return user_message
        if rewritten.lower() != user_message.lower():
            print(f"[QueryEngine] Condensed follow-up for retrieval: '{rewritten}'")
        return rewritten

    def _vector_retrieve(self, user_message: str,
                         attachments: list[str] | None = None) -> list[dict]:
        """Vector retrieval, prioritising files the user is asking about.

        Priority order for pinned context:
          1. `attachments` — files uploaded in this chat session.
          2. Any file whose name literally appears in the query text.

        When the message just points at "this/the uploaded file" and there are
        attachments, retrieval is *scoped* to those files only, so a deictic
        question resolves to the attachment instead of an unrelated KB hit.
        """
        attachments = [a for a in (attachments or []) if a]

        # Deictic + attachments → answer from the attached file(s) alone.
        if attachments and _DEICTIC_FILE_RE.search(user_message):
            scoped: list[dict] = []
            seen: set = set()
            for src in attachments[:3]:
                for c in self.vector_retriever.retrieve(
                        user_message, top_k=8, source_path=src):
                    key = (c.get("source"), (c.get("text") or "")[:80])
                    if key not in seen:
                        seen.add(key)
                        scoped.append(c)
            if scoped:
                print(f"[QueryEngine] Attachment-scoped retrieval to "
                      f"{[os.path.basename(a) for a in attachments[:3]]} "
                      f"({len(scoped)} chunk(s)).")
                return scoped
            # Nothing indexed yet (ingestion may still be running) — fall through
            # to normal retrieval + pinning below.

        chunks = self.vector_retriever.retrieve(user_message)

        # Pin attachments first, then any explicitly-named files.
        refs = list(dict.fromkeys(attachments + self._referenced_sources(user_message)))
        if not refs:
            return chunks

        seen = {(c.get("source"), (c.get("text") or "")[:80]) for c in chunks}
        pinned = []
        for src in refs[:3]:  # cap in case a query name matches many files
            top_k = 6 if src in attachments else 3  # give attachments more room
            for c in self.vector_retriever.retrieve(user_message, top_k=top_k, source_path=src):
                key = (c.get("source"), (c.get("text") or "")[:80])
                if key not in seen:
                    seen.add(key)
                    pinned.append(c)
        if pinned:
            print(f"[QueryEngine] Pinned {len(pinned)} chunk(s) from "
                  f"{[os.path.basename(s) for s in refs[:3]]}.")
            return pinned + chunks  # referenced-file content first
        return chunks

    def query(self, user_message: str, chat_history: list[dict] | None = None,
              attachments: list[str] | None = None) -> dict:
        """Process a user query through the full pipeline.

        Args:
            user_message: The user's question.
            chat_history: Previous messages as [{role, content}, ...] for context.
            attachments: Paths of files uploaded in this session to prioritise.

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

        # 0. Fold chat history into follow-up questions so retrieval works.
        #    Deictic-with-attachments questions ("what is this file about?")
        #    stay verbatim — condensing would strip the "this file" cue the
        #    attachment-scoped retrieval keys on.
        if attachments and _DEICTIC_FILE_RE.search(user_message):
            search_query = user_message
        else:
            search_query = self._condense_query(user_message, chat_history)

        # 1. Vector retrieval — semantic search
        print("\n[QueryEngine] Step 1: Vector retrieval...")
        sys.stdout.flush()
        vector_chunks = self._vector_retrieve(search_query, attachments=attachments)

        # 2. Graph retrieval — entity-based search
        print("\n[QueryEngine] Step 2: Graph retrieval...")
        sys.stdout.flush()
        graph_context = self.graph_retriever.retrieve(search_query)

        # 3. Build context
        print("\n[QueryEngine] Step 3: Building context...")
        sys.stdout.flush()
        context = self.context_builder.build(vector_chunks, graph_context)

        # 4. Build the full message list for the LLM
        messages = self._build_messages(user_message, context, chat_history, attachments)

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

        # 8. Estimate answer confidence from retrieval + citation signals
        confidence = self._compute_confidence(answer, vector_chunks, sources, graph_context)

        print(f"\n[QueryEngine] Done. Answer length: {len(answer)} chars, "
              f"{len(sources)} sources, confidence: {confidence['label']} ({confidence['score']}).")
        sys.stdout.flush()

        return {
            "answer": answer,
            "sources": sources,
            "entities_referenced": entities_referenced,
            "confidence": confidence,
        }

    def query_stream(self, user_message: str, chat_history: list[dict] | None = None,
                     attachments: list[str] | None = None):
        """Streaming version of query().

        Runs retrieval + context building the same way, then streams the LLM
        answer token-by-token. Yields event dicts:
            {"type": "token", "text": "..."}          (repeated)
            {"type": "done", "answer", "sources",       (once, at the end)
             "entities_referenced", "confidence"}

        The final `answer` is the cleaned full text (thinking tags stripped),
        so the client should replace the streamed text with it on "done".
        """
        print(f"\n[QueryEngine] Streaming query: '{user_message[:100]}...'")
        sys.stdout.flush()

        # 1-3. Retrieval + context (identical to query())
        if attachments and _DEICTIC_FILE_RE.search(user_message):
            search_query = user_message
        else:
            search_query = self._condense_query(user_message, chat_history)
        vector_chunks = self._vector_retrieve(search_query, attachments=attachments)
        graph_context = self.graph_retriever.retrieve(search_query)
        context = self.context_builder.build(vector_chunks, graph_context)
        messages = self._build_messages(user_message, context, chat_history, attachments)

        # 4. Stream the answer, accumulating the raw text.
        print("[QueryEngine] Streaming answer with LLM...")
        sys.stdout.flush()
        parts: list[str] = []
        for token in self.llm.generate_with_history_stream(
            messages=messages, max_tokens=LLMConfig.MAX_TOKENS,
        ):
            parts.append(token)
            yield {"type": "token", "text": token}

        raw_answer = "".join(parts)
        answer = self._clean_answer(raw_answer)
        if not answer:
            answer = "I'm sorry, I wasn't able to generate a response. Please try rephrasing your question."

        # 5. Post-process: sources, citations, entities, confidence.
        sources = self.context_builder.extract_source_references(vector_chunks, graph_context)
        self._mark_cited_sources(answer, sources)
        entities_referenced = [e.get("name", "") for e in graph_context.get("entities", [])]
        confidence = self._compute_confidence(answer, vector_chunks, sources, graph_context)

        print(f"[QueryEngine] Stream done. {len(answer)} chars, {len(sources)} sources, "
              f"confidence: {confidence['label']} ({confidence['score']}).")
        sys.stdout.flush()

        yield {
            "type": "done",
            "answer": answer,
            "sources": sources,
            "entities_referenced": entities_referenced,
            "confidence": confidence,
        }

    @staticmethod
    def _compute_confidence(answer: str, vector_chunks: list[dict],
                            sources: list[dict], graph_context: dict) -> dict:
        """Estimate how much to trust the answer, from honest signals only.

        Combines: strength of the best vector match, whether the answer
        actually cited its sources, graph corroboration, and whether the model
        itself signalled that context was insufficient. Returns
        {score: 0..1, label: 'High'|'Medium'|'Low', reasons: [...]}.
        """
        reasons = []

        # Signal 1: best retrieval relevance (cosine, ~0.3 weak .. ~0.7 strong)
        top_score = max((c.get("score", 0.0) for c in vector_chunks), default=0.0)
        retrieval = max(0.0, min(1.0, (top_score - 0.30) / 0.40))
        if top_score:
            reasons.append(f"top match {top_score:.2f}")

        # Signal 2: did the answer cite any retrieved source?
        cited = [s for s in sources if s.get("cited")]
        citation = min(1.0, len(cited) / 2.0) if cited else 0.0
        if cited:
            reasons.append(f"{len(cited)} source(s) cited")
        elif sources:
            reasons.append("no sources cited in answer")

        # Signal 3: graph corroboration
        graph_hit = 0.0
        if graph_context and graph_context.get("entities"):
            graph_hit = 1.0
            reasons.append("graph corroborated")

        # Signal 4: explicit "not enough info" admission from the model
        low_markers = ("i don't have", "not enough information", "no relevant",
                       "isn't enough", "cannot answer", "couldn't find",
                       "wasn't able", "does not contain", "no information")
        answer_lower = (answer or "").lower()
        insufficient = any(m in answer_lower for m in low_markers)
        if insufficient:
            reasons.append("model reported insufficient context")

        score = 0.55 * retrieval + 0.30 * citation + 0.15 * graph_hit
        if insufficient:
            score = min(score, 0.35)
        if not sources:
            score = min(score, 0.20)
        score = round(max(0.0, min(1.0, score)), 2)

        label = "High" if score >= 0.66 else "Medium" if score >= 0.4 else "Low"
        return {"score": score, "label": label, "reasons": reasons}

    def _build_messages(
        self,
        user_message: str,
        context: str,
        chat_history: list[dict] | None,
        attachments: list[str] | None = None,
    ) -> list[dict]:
        """Assemble the full message list for the LLM.

        Structure for general questions:
            [system prompt] → [recent chat history] → [context + question]

        Structure for compliance/audit questions:
            [system prompt] → [audit system prompt] → [recent chat history] → [context + question]
        """
        q_lower = user_message.lower()
        is_audit_q = any(kw in q_lower for kw in _AUDIT_KEYWORDS)

        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]

        # Inject the specialist audit persona as a second system message so the
        # LLM switches into structured COVERED/PARTIAL/GAP reasoning mode.
        if is_audit_q:
            messages.append({"role": "system", "content": _AUDIT_SYSTEM_PROMPT})
            print("[QueryEngine] Audit persona injected for compliance question.")

        # Add recent chat history (trimmed to last N turns)
        if chat_history:
            max_turns = RetrievalConfig.MAX_HISTORY_TURNS * 2  # Each turn = user + assistant
            recent = chat_history[-max_turns:]
            for msg in recent:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                })

        # Add the current question with context.
        # For compliance questions, also inject the expiry-date scan hint inline.
        expiry_hint = ""
        if is_audit_q:
            expiry_hint = (
                "\n⚠️ This question relates to compliance or validity. "
                "Before answering, scan the context for:\n"
                "  • DATE_DUE entities (expiry dates, renewal deadlines)\n"
                "  • VALID_UNTIL relationships linking certificates to their expiry dates\n"
                "  • Any phrases like 'valid till', 'expiry date', 'renewal due', 'expires on'\n"
                "State every expiry date you find, flag any that are past as EXPIRED, "
                "and explicitly note if no expiry date was found in the context.\n"
            )

        # When files are attached to this chat, tell the model that deictic
        # references ("this file", "the document") mean those files, so it
        # answers about the upload rather than an unrelated knowledge-base hit.
        attach_hint = ""
        attach_names = [os.path.basename(a) for a in (attachments or []) if a]
        if attach_names:
            attach_hint = (
                "\n📎 The user has attached the following file(s) to this chat: "
                f"{', '.join(attach_names)}. When they say \"this file\", \"the "
                "document\", \"the image\", or similar, they mean these attached "
                "file(s) — answer about them and cite them by name.\n"
            )

        user_content = f"""Based on the following context from the company's knowledge base, answer the user's question.
If the question refers back to something discussed earlier in this conversation, use the conversation history above to interpret it.
Remember: cite the exact file name in square brackets after every claim, and finish with a **Sources:** line.{attach_hint}{expiry_hint}

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
