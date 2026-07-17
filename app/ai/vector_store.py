"""
ChromaDB client wrapper — vector storage and similarity search for
semantic candidate-job matching.

Runs as a separate service (not embedded in the app process) so the heavy
ML/vector-index lifecycle is isolated from the main API process — mirrors
how you'd deploy this in production, where the app talks to a dedicated
vector DB over the network.
"""

import chromadb

from app.core.config import settings

_client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)

# hnsw:space="cosine" makes the similarity metric explicit rather than
# relying on Chroma's default — cosine similarity is the standard choice
# for comparing normalized text embeddings.
_candidate_collection = _client.get_or_create_collection(
    name="candidate_resumes", metadata={"hnsw:space": "cosine"}
)


def upsert_candidate_embedding(candidate_user_id: str, embedding: list[float], resume_text: str) -> None:
    """
    Store (or replace) a candidate's resume embedding.

    upsert, not insert — re-uploading a resume should replace the previous
    embedding, not create a duplicate entry for the same candidate.
    """
    _candidate_collection.upsert(
        ids=[candidate_user_id],
        embeddings=[embedding],
        documents=[resume_text[:2000]],  # capped snippet, useful for debugging/inspection
    )


def query_similar_candidates(job_embedding: list[float], top_k: int = 10) -> list[dict]:
    """
    Find the top_k candidates whose resume embeddings are most similar to
    the given job embedding. Returns (candidate_user_id, distance) pairs —
    lower distance means more similar.
    """
    results = _candidate_collection.query(query_embeddings=[job_embedding], n_results=top_k)
    ids = results["ids"][0]
    distances = results["distances"][0]
    return [
        {"candidate_user_id": candidate_id, "distance": distance}
        for candidate_id, distance in zip(ids, distances)
    ]
