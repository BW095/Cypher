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