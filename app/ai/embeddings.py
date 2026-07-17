"""
Embedding generation using Sentence Transformers.

Why Sentence Transformers (local, free) over OpenAI's embeddings API:
- No API key required, no per-request cost, no network dependency at runtime
  — important for a portfolio project other people need to clone and run
- all-MiniLM-L6-v2 is small (~80MB), fast on CPU, and good enough quality
  for semantic similarity at this scale
- Named tradeoff: OpenAI's embedding models generally produce higher-quality
  results for large-scale production search. Swapping the backend later is
  a contained change — nothing outside this module needs to know which
  embedding provider is in use.
"""

from functools import lru_cache

from sentence_transformers import SentenceTransformer


@lru_cache
def _get_model() -> SentenceTransformer:
    """
    Loaded once per process (lru_cache), not per-request — model loading
    is relatively expensive (~1-2s); embedding a single text after that is fast.
    """
    return SentenceTransformer("all-MiniLM-L6-v2")


def generate_embedding(text: str) -> list[float]:
    """
    Convert text into a normalized embedding vector.

    Normalization matters: comparing un-normalized vectors biases similarity
    scores toward longer documents. Normalized vectors make cosine similarity
    (used by our vector store) behave correctly.
    """
    model = _get_model()
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()
