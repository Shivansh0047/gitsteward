from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from config import settings
from rag.readme_source import chunk_readme

_vectorstore: Chroma | None = None  # lives in memory for the life of this process

def _get_embeddings_client(task_type: str) -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=settings.google_api_key,
        task_type=task_type,
    )

def build_vectorstore() -> Chroma:
    """Fetch + chunk the README, embed every section, hold it in memory.
        used once, at server startup — not per-request."""
    global _vectorstore
    chunks = chunk_readme()
    texts = [c["content"] for c in chunks]
    metadatas = [{"anchor": c["anchor"], "heading": c["heading"]} for c in chunks]

    _vectorstore = Chroma.from_texts(
        texts=texts,
        embedding=_get_embeddings_client("RETRIEVAL_DOCUMENT"),  # README chunks = documents being searched
        metadatas=metadatas,
    )
    return _vectorstore

def get_vectorstore() -> Chroma:
    if _vectorstore is None:
        raise RuntimeError("Vectorstore not built yet — call build_vectorstore() first.")
    return _vectorstore

def retrieve_relevant_sections(query: str, k: int = 6) -> list[dict]:
    """Given a query (e.g. a description of a code change), return the
    top-k most semantically relevant README chunks."""
    vectorstore = get_vectorstore()
    query_embedder = _get_embeddings_client("RETRIEVAL_QUERY")  # the search query itself
    query_vector = query_embedder.embed_query(query)
    results = vectorstore.similarity_search_by_vector(query_vector, k=k)
    return [
        {"anchor": doc.metadata["anchor"], "heading": doc.metadata["heading"], "content": doc.page_content}
        for doc in results
    ]