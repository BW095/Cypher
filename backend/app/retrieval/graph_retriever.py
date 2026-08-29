"""
Graph Retriever — entity-based retrieval from the Neo4j knowledge graph.

Extracts candidate entity names from the user query, matches them against
the graph, and traverses relationships to gather contextual knowledge
that pure vector search would miss.
"""

import sys
import re
from app.storage.neo4j import Neo4jStorage
from app.config import RetrievalConfig


class GraphRetriever:
    def __init__(self, neo4j_db: Neo4jStorage = None):
        self.neo4j_db = neo4j_db or Neo4jStorage()

    def retrieve(self, query: str, depth: int | None = None) -> dict:
        """Retrieve graph context relevant to a user query.

        Returns a dict:
            {
                entities: [{id, name, type, description}, ...],
                relationships: [{source, target, type}, ...],
                source_documents: [file_path, ...]
            }
        """
        depth = depth or RetrievalConfig.GRAPH_SEARCH_DEPTH

        print(f"[GraphRetriever] Extracting entity candidates from query...")
        sys.stdout.flush()

        # 1. Extract candidate entity names from the query, preferring names
        #    that actually exist in the graph over raw keywords.
        candidates = self._extract_candidates(query)

        if not candidates:
            print("[GraphRetriever] No entity candidates found in query.")
            return {"entities": [], "relationships": [], "source_documents": []}

        print(f"[GraphRetriever] Searching graph for candidates: {candidates}")
        sys.stdout.flush()

        # 2. Search the graph for each candidate
        all_nodes = []
        all_edges = []
        all_docs = []
        seen_node_ids = set()
        seen_edge_keys = set()

        for candidate in candidates:
            # Try exact entity match + traversal
            graph_data = self.neo4j_db.find_related_entities(candidate, depth=depth)

            for node in graph_data.get("nodes", []):
                nid = node.get("id", "")
                if nid not in seen_node_ids:
                    seen_node_ids.add(nid)
                    all_nodes.append(node)

            for edge in graph_data.get("edges", []):
                edge_key = (edge.get("source", ""), edge.get("target", ""), edge.get("type", ""))
                if edge_key not in seen_edge_keys:
                    seen_edge_keys.add(edge_key)
                    all_edges.append(edge)

            for doc in graph_data.get("source_documents", []):
                if doc not in all_docs:
                    all_docs.append(doc)

        # 3. If direct traversal found nothing, try fuzzy search
        if not all_nodes:
            print("[GraphRetriever] No direct matches — trying fuzzy entity search...")
            for candidate in candidates:
                fuzzy_hits = self.neo4j_db.search_entities(candidate, limit=5)
                for entity in fuzzy_hits:
                    nid = entity.get("id", "")
                    if nid not in seen_node_ids:
                        seen_node_ids.add(nid)
                        all_nodes.append(entity)
                    # Also get docs for this entity
                    docs = self.neo4j_db.find_documents_for_entity(entity.get("name", ""))
                    for doc in docs:
                        if doc not in all_docs:
                            all_docs.append(doc)

        result = {
            "entities": all_nodes,
            "relationships": all_edges,
            "source_documents": all_docs,
        }

        print(f"[GraphRetriever] Found {len(all_nodes)} entities, {len(all_edges)} relationships, {len(all_docs)} source docs")
        sys.stdout.flush()

        return result

    _STOPWORDS = {
        "what", "how", "why", "when", "where", "which", "the", "is", "are",
        "was", "were", "has", "have", "had", "can", "could", "should", "would",
        "will", "do", "does", "a", "an", "and", "or", "but", "for", "to", "of",
        "in", "on", "at", "with", "from", "by", "about", "between", "this",
        "that", "these", "those", "it", "its", "i", "me", "my", "we", "our",
        "you", "your", "tell", "give", "need", "needed", "required", "any",
        "all", "some", "list", "show", "find", "get", "files", "file",
        "document", "documents", "report", "reports", "there", "their",
    }

    def _extract_candidates(self, query: str) -> list[str]:
        """Extract entity-name candidates from the query.

        Strategy (best first):
        1. Match the query text against actual entity names in the graph — the
           most reliable signal, since it can only produce names that exist.
        2. Add explicit equipment codes (P-101, B-201) as high-value fallbacks.
        3. Only if nothing matched, fall back to significant keywords so an
           empty graph or a novel term still gets a fuzzy search.
        """
        query_lower = query.lower()
        candidates = []
        seen = set()

        def add(c):
            key = c.lower()
            if c and key not in seen:
                seen.add(key)
                candidates.append(c)

        # 1. Real entity names that appear in the query (longest first so
        #    "Pump P-101" wins over "Pump").
        try:
            known = self.neo4j_db.get_all_entity_names()
        except Exception:
            known = []
        for ent in sorted(known, key=lambda e: len(e.get("name", "")), reverse=True):
            name = (ent.get("name") or "").strip()
            if len(name) >= 3 and name.lower() in query_lower:
                add(name)

        # 2. Equipment codes like P-101, B-201, V-001 (verbatim from the query).
        for code in re.findall(r'\b[A-Za-z]{1,3}[-_]?\d{2,4}\b', query):
            add(code)

        # 3. Fallback: significant keywords, only if we found no graph matches.
        if not candidates:
            words = re.findall(r'\b\w{3,}\b', query)
            for w in words:
                if w.lower() not in self._STOPWORDS:
                    add(w)

        return candidates[:10]
