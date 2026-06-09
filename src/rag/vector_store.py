from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb
from rag.parser import parse_policy_markdown


class ChromaPolicyStore:
    """Student scaffold for the real Chroma-backed policy index."""

    def __init__(
        self,
        persist_directory: Path,
        embedding_model: Any,
        collection_name: str = "policy_chunks",
    ) -> None:
        self.persist_directory = persist_directory
        self.embedding_model = embedding_model
        self.collection_name = collection_name
        
        # Initialize Chroma PersistentClient
        self.client = chromadb.PersistentClient(path=str(persist_directory))
        
        # Get or create the collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
        )

    def ensure_index(self, markdown_path: Path) -> None:
        # If collection is empty, rebuild from markdown
        if self.collection.count() == 0:
            self.rebuild(markdown_path)

    def rebuild(self, markdown_path: Path) -> None:
        # Delete and recreate the collection to clear existing data
        try:
            self.client.delete_collection(self.collection_name)
        except Exception:
            pass
            
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
        )
        
        # Parse the policy markdown
        try:
            content = markdown_path.read_text(encoding="utf-8")
        except Exception as e:
            raise RuntimeError(f"Failed to read policy markdown file from {markdown_path}: {e}")
            
        chunks = parse_policy_markdown(content)
        if not chunks:
            return
            
        # Embed documents using the embedding model
        documents = [c["rendered_text"] for c in chunks]
        embeddings = self.embedding_model.embed_documents(documents)
        
        # Prepare IDs and Metadata
        ids = [f"chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "citation": c["citation"],
                "section_h2": c["section_h2"],
                "section_h3": c["section_h3"] or ""
            }
            for c in chunks
        ]
        
        # Add items to Chroma collection
        self.collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas
        )

    def search(self, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        if not query.strip():
            return []
            
        # Embed query
        query_vector = self.embedding_model.embed_query(query)
        
        # Query Chroma collection
        results = self.collection.query(
            query_embeddings=[query_vector],
            n_results=top_k
        )
        
        hits = []
        if results and "documents" in results and results["documents"]:
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            dists = results["distances"][0]
            
            for doc, meta, dist in zip(docs, metas, dists):
                hits.append({
                    "citation": meta.get("citation", ""),
                    "content": doc,
                    "distance": dist
                })
                
        return hits
