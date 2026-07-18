from neo4j import GraphDatabase
import logging
from app.ingestion.canonical_document import CanonicalDocument


class Neo4jStorage:
    def __init__(self, uri: str = "neo4j://localhost:7687", user: str = "neo4j", password: str = "password",
                 database: str = "neo4j"):
        # Create a Driver object that holds the details required to establish connections
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

        # Verify immediately that the driver can connect to the database
        try:
            self.driver.verify_connectivity()
            print("Successfully connected to Neo4j.")
        except Exception as e:
            logging.error(f"Failed to connect to Neo4j: {e}")

    def close(self):
        # Always close the driver connection when the application shuts down
        self.driver.close()

    def store_graph(self, document: CanonicalDocument):
        """
        Takes the entities and relationships from the processed document and stores them in Neo4j.
        """
        # Always record the document itself, even when extraction found nothing —
        # an empty graph should still show which files were ingested.
        self._merge_document(document)

        if not document.entities and not document.relationships:
            print(f"[Neo4j] No entities/relationships for {document.file_path} "
                  f"(entity extraction returned nothing) — stored Document node only.")
            return

        print(f"Storing {len(document.entities)} entities and {len(document.relationships)} relationships in Neo4j...")

        # 1. Store Entities (Nodes)
        for entity in document.entities:
            self._merge_entity(entity)

        # 2. Store Relationships (Edges)
        for rel in document.relationships:
            self._merge_relationship(rel)

        # 3. Link everything back to the source document
        self._link_document_to_entities(document)

    def _merge_entity(self, entity: dict):
        # Using execute_query with the explicit database_ parameter
        query = """
        MERGE (e:Entity {id: $entity_id})
        SET e.name = $name, 
            e.type = $type,
            e.description = $description
        """
        try:
            self.driver.execute_query(
                query,
                entity_id=entity.get("id"),
                name=entity.get("name"),
                type=entity.get("type", "Unknown"),
                description=entity.get("description", ""),
                database_=self.database
            )
        except Exception as e:
            logging.error(f"Error merging entity {entity.get('name')}: {e}")

    def _merge_relationship(self, rel: dict):
        # Uses MERGE to ensure we don't create duplicate relationships between the same nodes
        query = """
        MATCH (source:Entity {id: $source_id})
        MATCH (target:Entity {id: $target_id})
        MERGE (source)-[r:RELATED_TO {type: $rel_type}]->(target)
        """
        try:
            self.driver.execute_query(
                query,
                source_id=rel.get("source_id"),
                target_id=rel.get("target_id"),
                rel_type=rel.get("type", "RELATES_TO"),
                database_=self.database
            )
        except Exception as e:
            logging.error(f"Error merging relationship: {e}")

    def delete_document(self, file_path: str):
        """Remove a document's node and detach its links, for clean re-ingestion.

        Entities are shared across documents (canonical ids), so we only remove
        this document's MENTIONS edges and the Document node itself — never the
        entities, which other documents may still reference. Entities that end
        up orphaned (mentioned by no document) are then pruned.
        """
        try:
            self.driver.execute_query(
                "MATCH (d:Document {path: $file_path}) DETACH DELETE d",
                file_path=file_path, database_=self.database,
            )
            # Prune entities no longer mentioned by any document.
            self.driver.execute_query(
                """
                MATCH (e:Entity)
                WHERE NOT (:Document)-[:MENTIONS]->(e)
                DETACH DELETE e
                """,
                database_=self.database,
            )
        except Exception as e:
            logging.error(f"Error deleting document {file_path} from graph: {e}")

    def _merge_document(self, document: CanonicalDocument):
        # Create/update the node for the document itself
        doc_query = """
        MERGE (d:Document {path: $file_path})
        SET d.type = $file_type
        """
        try:
            self.driver.execute_query(
                doc_query,
                file_path=document.file_path,
                file_type=document.file_type,
                database_=self.database
            )
        except Exception as e:
            logging.error(f"Error merging document node {document.file_path}: {e}")

    def _link_document_to_entities(self, document: CanonicalDocument):
        # Link the document node to the extracted entities
        link_query = """
        MATCH (d:Document {path: $file_path})
        MATCH (e:Entity {id: $entity_id})
        MERGE (d)-[:MENTIONS]->(e)
        """
        for entity in document.entities:
            try:
                self.driver.execute_query(
                    link_query,
                    file_path=document.file_path,
                    entity_id=entity.get("id"),
                    database_=self.database
                )
            except Exception as e:
                logging.error(f"Error linking document to entity: {e}")

    # ------------------------------------------------------------------
    # Retrieval / Query methods
    # ------------------------------------------------------------------

    # Cache of (names, timestamp) so graph retrieval can match query terms
    # against real entity names without hitting Neo4j on every keystroke.
    _entity_name_cache = None
    _entity_name_cache_ts = 0.0
    _ENTITY_NAME_TTL = 60.0  # seconds

    def get_all_entity_names(self) -> list[dict]:
        """Return [{name, id, type}, ...] for every entity, cached briefly.

        Used by the graph retriever to detect which entities a free-text
        query actually refers to, instead of guessing from raw keywords.
        """
        import time
        now = time.time()
        cls = type(self)
        if cls._entity_name_cache is not None and \
                now - cls._entity_name_cache_ts < cls._ENTITY_NAME_TTL:
            return cls._entity_name_cache
        try:
            records, _, _ = self.driver.execute_query(
                "MATCH (e:Entity) RETURN e.id AS id, e.name AS name, e.type AS type",
                database_=self.database,
            )
            names = [{"id": r["id"], "name": r["name"], "type": r["type"]}
                     for r in records if r.get("name")]
        except Exception as e:
            logging.error(f"Error fetching entity names: {e}")
            names = cls._entity_name_cache or []
        cls._entity_name_cache = names
        cls._entity_name_cache_ts = now
        return names

    def invalidate_entity_cache(self):
        """Drop the entity-name cache (call after ingesting new documents)."""
        cls = type(self)
        cls._entity_name_cache = None
        cls._entity_name_cache_ts = 0.0

    def search_entities(self, query_text: str, limit: int = 10) -> list[dict]:
        """Fuzzy search for entities whose name or description contains the query text."""
        query = """
        MATCH (e:Entity)
        WHERE toLower(e.name) CONTAINS toLower($query)
           OR toLower(e.description) CONTAINS toLower($query)
        RETURN e.id AS id, e.name AS name, e.type AS type, e.description AS description
        LIMIT $limit
        """
        try:
            records, _, _ = self.driver.execute_query(
                query, query=query_text, limit=limit, database_=self.database
            )
            return [dict(r) for r in records]
        except Exception as e:
            logging.error(f"Error searching entities: {e}")
            return []

    def get_entities_by_type(self, entity_type: str, limit: int = 200) -> list[dict]:
        """Return all entities of a given type (e.g. 'REGULATION')."""
        query = """
        MATCH (e:Entity)
        WHERE toUpper(e.type) = toUpper($etype)
        RETURN e.id AS id, e.name AS name, e.type AS type, e.description AS description
        LIMIT $limit
        """
        try:
            records, _, _ = self.driver.execute_query(
                query, etype=entity_type, limit=limit, database_=self.database
            )
            return [dict(r) for r in records]
        except Exception as e:
            logging.error(f"Error fetching entities of type {entity_type}: {e}")
            return []

    def get_entity_neighborhood(self, entity_id: str) -> dict:
        """Return the directly-connected entities and documents for one entity id.

        Used by compliance analysis to see what procedures/equipment/evidence a
        regulation is linked to. Returns {neighbors: [...], documents: [...]}.
        """
        try:
            neighbor_records, _, _ = self.driver.execute_query(
                """
                MATCH (e:Entity {id: $id})-[r]-(n:Entity)
                RETURN DISTINCT n.id AS id, n.name AS name, n.type AS type,
                       n.description AS description, type(r) AS rel
                """,
                id=entity_id, database_=self.database,
            )
            doc_records, _, _ = self.driver.execute_query(
                """
                MATCH (d:Document)-[:MENTIONS]->(e:Entity {id: $id})
                RETURN DISTINCT d.path AS path
                """,
                id=entity_id, database_=self.database,
            )
            neighbors = [{
                "id": r["id"], "name": r["name"],
                "type": r["type"] or "Unknown",
                "description": r["description"] or "",
                "rel": r["rel"],
            } for r in neighbor_records]
            documents = [r["path"] for r in doc_records if r.get("path")]
            return {"neighbors": neighbors, "documents": documents}
        except Exception as e:
            logging.error(f"Error fetching neighborhood for {entity_id}: {e}")
            return {"neighbors": [], "documents": []}

    def find_related_entities(self, entity_name: str, depth: int = 2) -> dict:
        """Find an entity by name and traverse up to `depth` hops.

        Returns {nodes: [...], edges: [...], source_documents: [...]}.
        """
        query = """
        MATCH (start:Entity)
        WHERE toLower(start.name) = toLower($name)
        CALL apoc.path.subgraphAll(start, {maxLevel: $depth}) YIELD nodes, relationships
        RETURN nodes, relationships
        """
        # Fallback query if APOC is not installed
        fallback_query = """
        MATCH (start:Entity)
        WHERE toLower(start.name) = toLower($name)
        OPTIONAL MATCH path = (start)-[*1..%d]-(connected:Entity)
        WITH start, collect(DISTINCT connected) AS neighbors,
             collect(DISTINCT relationships(path)) AS all_rels
        RETURN start, neighbors, all_rels
        """ % depth

        try:
            return self._execute_traversal(entity_name, query, fallback_query, depth)
        except Exception as e:
            logging.error(f"Error finding related entities for '{entity_name}': {e}")
            return {"nodes": [], "edges": [], "source_documents": []}

    def _execute_traversal(self, entity_name: str, apoc_query: str,
                           fallback_query: str, depth: int) -> dict:
        """Try APOC traversal first, fall back to vanilla Cypher."""
        nodes = []
        edges = []
        seen_node_ids = set()

        try:
            records, _, _ = self.driver.execute_query(
                apoc_query, name=entity_name, depth=depth, database_=self.database
            )
            for record in records:
                for node in record["nodes"]:
                    nid = node.get("id", "")
                    if nid not in seen_node_ids:
                        seen_node_ids.add(nid)
                        nodes.append({
                            "id": nid,
                            "name": node.get("name", ""),
                            "type": node.get("type", "Unknown"),
                            "description": node.get("description", ""),
                        })
                for rel in record["relationships"]:
                    edges.append({
                        "source": rel.start_node.get("id", ""),
                        "target": rel.end_node.get("id", ""),
                        "type": rel.get("type", rel.type),
                    })
        except Exception:
            # APOC not available — use fallback
            records, _, _ = self.driver.execute_query(
                fallback_query, name=entity_name, database_=self.database
            )
            for record in records:
                start = record["start"]
                nid = start.get("id", "")
                if nid not in seen_node_ids:
                    seen_node_ids.add(nid)
                    nodes.append({
                        "id": nid,
                        "name": start.get("name", ""),
                        "type": start.get("type", "Unknown"),
                        "description": start.get("description", ""),
                    })
                for neighbor in record.get("neighbors", []):
                    if neighbor is None:
                        continue
                    nid = neighbor.get("id", "")
                    if nid not in seen_node_ids:
                        seen_node_ids.add(nid)
                        nodes.append({
                            "id": nid,
                            "name": neighbor.get("name", ""),
                            "type": neighbor.get("type", "Unknown"),
                            "description": neighbor.get("description", ""),
                        })
                for rel_list in record.get("all_rels", []):
                    if rel_list is None:
                        continue
                    for rel in rel_list:
                        edges.append({
                            "source": rel.start_node.get("id", ""),
                            "target": rel.end_node.get("id", ""),
                            "type": rel.get("type", rel.type),
                        })

        # Find source documents for these entities
        source_documents = self._find_documents_for_entities(list(seen_node_ids))
        return {"nodes": nodes, "edges": edges, "source_documents": source_documents}

    def _find_documents_for_entities(self, entity_ids: list[str]) -> list[str]:
        """Find all documents that mention any of the given entities."""
        if not entity_ids:
            return []
        query = """
        MATCH (d:Document)-[:MENTIONS]->(e:Entity)
        WHERE e.id IN $entity_ids
        RETURN DISTINCT d.path AS path
        """
        try:
            records, _, _ = self.driver.execute_query(
                query, entity_ids=entity_ids, database_=self.database
            )
            return [r["path"] for r in records if r.get("path")]
        except Exception as e:
            logging.error(f"Error finding documents for entities: {e}")
            return []

    def find_documents_for_entity(self, entity_name: str) -> list[str]:
        """Find all documents mentioning a specific entity by name."""
        query = """
        MATCH (d:Document)-[:MENTIONS]->(e:Entity)
        WHERE toLower(e.name) = toLower($name)
        RETURN DISTINCT d.path AS path
        """
        try:
            records, _, _ = self.driver.execute_query(
                query, name=entity_name, database_=self.database
            )
            return [r["path"] for r in records if r.get("path")]
        except Exception as e:
            logging.error(f"Error finding documents for entity '{entity_name}': {e}")
            return []

    def get_full_graph(self, limit: int = 400) -> dict:
        """Return the whole entity graph (capped) for visualization.

        Guarantees referential integrity: every returned edge's endpoints are
        in the returned node set — react-force-graph throws otherwise. We cap
        the node count and only include edges between surviving nodes.
        """
        try:
            node_records, _, _ = self.driver.execute_query(
                """
                MATCH (e:Entity)
                OPTIONAL MATCH (e)-[r:RELATED_TO]-()
                WITH e, count(r) AS degree
                RETURN e.id AS id, e.name AS name, e.type AS type,
                       e.description AS description, degree
                ORDER BY degree DESC
                LIMIT $limit
                """,
                limit=limit, database_=self.database,
            )
            nodes = [{
                "id": r["id"], "name": r["name"],
                "type": r["type"] or "Unknown",
                "description": r["description"] or "",
                "degree": r["degree"],
            } for r in node_records if r.get("id")]

            node_ids = {n["id"] for n in nodes}
            if not node_ids:
                return {"nodes": [], "edges": []}

            edge_records, _, _ = self.driver.execute_query(
                """
                MATCH (a:Entity)-[r:RELATED_TO]->(b:Entity)
                WHERE a.id IN $ids AND b.id IN $ids
                RETURN a.id AS source, b.id AS target, r.type AS type
                """,
                ids=list(node_ids), database_=self.database,
            )
            edges = [{
                "source": r["source"], "target": r["target"],
                "type": r["type"] or "RELATED_TO",
            } for r in edge_records
                if r["source"] in node_ids and r["target"] in node_ids]

            return {"nodes": nodes, "edges": edges}
        except Exception as e:
            logging.error(f"Error building full graph: {e}")
            return {"nodes": [], "edges": []}

    def get_graph_stats(self) -> dict:
        """Return high-level graph statistics."""
        try:
            entity_records, _, _ = self.driver.execute_query(
                "MATCH (e:Entity) RETURN e.type AS type, count(*) AS count",
                database_=self.database,
            )
            rel_records, _, _ = self.driver.execute_query(
                "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count",
                database_=self.database,
            )
            doc_records, _, _ = self.driver.execute_query(
                "MATCH (d:Document) RETURN count(d) AS count",
                database_=self.database,
            )

            entity_types = {r["type"]: r["count"] for r in entity_records}
            total_entities = sum(entity_types.values())
            total_rels = sum(r["count"] for r in rel_records)
            total_docs = doc_records[0]["count"] if doc_records else 0

            return {
                "total_entities": total_entities,
                "total_relationships": total_rels,
                "total_documents": total_docs,
                "entity_types": entity_types,
            }
        except Exception as e:
            logging.error(f"Error getting graph stats: {e}")
            return {
                "total_entities": 0,
                "total_relationships": 0,
                "total_documents": 0,
                "entity_types": {},
            }