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
        if not document.entities and not document.relationships:
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

    def _link_document_to_entities(self, document: CanonicalDocument):
        # Create a node for the document itself and link it to the extracted entities
        doc_query = """
        MERGE (d:Document {path: $file_path})
        SET d.type = $file_type
        """
        self.driver.execute_query(
            doc_query,
            file_path=document.file_path,
            file_type=document.file_type,
            database_=self.database
        )

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