import os
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
import numpy as np

QDRANT_DATA_DIR = Path(__file__).parent.parent / "data" / "qdrant_db"
COLLECTION_NAME = "video_frames"
VECTOR_SIZE = 512  # CLIP ViT-B/32 generates 512-dimensional embeddings

class QdrantStore:
    """
    Manages local vector store using Qdrant for semantic video frame embeddings (CLIP).
    """

    def __init__(self):
        # Initialize Qdrant Client: Use Host/Port if in Cloud/Docker, otherwise Local Path
        import time
        
        qdrant_host = os.getenv("QDRANT_HOST")
        if qdrant_host:
            # Cloud/Container mode
            print(f"DEBUG: Qdrant connecting via host: {qdrant_host}")
            
            max_retries = 5
            retry_delay = 2
            
            for attempt in range(max_retries):
                try:
                    self.client = QdrantClient(host=qdrant_host, port=6333, timeout=10)
                    # Force a connection check
                    self.client.get_collections()
                    print(f"DEBUG: Qdrant connected successfully on attempt {attempt + 1}")
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        print(f"ERROR: Could not connect to Qdrant at {qdrant_host}:6333 after {max_retries} attempts.")
                        raise e
                    print(f"DEBUG: Qdrant not ready (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
        else:
            # Local persistent mode
            QDRANT_DATA_DIR.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(QDRANT_DATA_DIR))
        self._ensure_collection()


    def _ensure_collection(self):
        """Creates the collection if it doesn't exist."""
        collections = self.client.get_collections().collections
        if not any(c.name == COLLECTION_NAME for c in collections):
            self.client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

    def insert_hashes(self, clip_name: str, frame_embeddings: dict[str, np.ndarray]):
        """
        Insert frame embeddings for a specific clip into Qdrant.
        `frame_embeddings` should map timestamp (str) to vector (numpy array).
        """
        # Using a deterministic hash to prevent duplicates or allow overwriting if same clip & ts
        import hashlib
        
        points = []
        for ts_str, embedding in frame_embeddings.items():
            # Create a unique integer ID or UUID for the point
            point_id = hashlib.md5(f"{clip_name}_{ts_str}".encode()).hexdigest()
            # Qdrant client allows string UUIDs as IDs
            
            points.append(
                PointStruct(
                    id=point_id,
                    vector=embedding.tolist(),
                    payload={
                        "clip_name": clip_name,
                        "timestamp": float(ts_str)
                    }
                )
            )

        if points:
            # Batch upsert
            self.client.upsert(
                collection_name=COLLECTION_NAME,
                points=points
            )

    def search_frame(self, suspect_embedding: np.ndarray, limit: int = 1) -> list[dict]:
        """
        Search for the most similar frames in the entire DB.
        Returns a list of payloads with their scores.
        """
        # qdrant-client 1.17+ unified API: use query_points instead of search
        response = self.client.query_points(
            collection_name=COLLECTION_NAME,
            query=suspect_embedding.tolist(),
            limit=limit,
        )
        
        matches = []
        for point in response.points:
            match = point.payload.copy()
            match["score"] = point.score  # Cosine similarity (1.0 = identical)
            matches.append(match)
            
        return matches

    def get_clip_timestamps(self, clip_name: str) -> list[tuple[float, np.ndarray]]:
        """
        Fetches all timestamps and vectors for a specific clip.
        Used for speed-invariant scanning where we need consecutive frames of a best-matched clip.
        """
        # We can simulate this with scroll/query with filter
        from qdrant_client.http.models import Filter, FieldCondition, MatchValue
        
        records, _ = self.client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="clip_name",
                        match=MatchValue(value=clip_name)
                    )
                ]
            ),
            with_vectors=True,
            limit=10000
        )
        
        return [(r.payload["timestamp"], np.array(r.vector)) for r in records]

    def count_frames(self) -> int:
        """Returns the total number of ingested frames."""
        try:
            return self.client.count(collection_name=COLLECTION_NAME).count
        except Exception:
            return 0
