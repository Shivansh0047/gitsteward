from langchain_postgres import PGVector
from langchain_google_genai import GoogleGenerativeAIEmbeddings
import time
from config import settings
from rag.readme_source import chunk_readme


def _get_embeddings_client(task_type: str) -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=settings.google_api_key,
        task_type=task_type,
    )


def _collection_name(repo_full_name: str, kind: str) -> str:
    # kind: "readme" | "docs-main" | "docs-branch" — one Postgres collection per repo per kind
    return f"{repo_full_name}::{kind}"

def _pgvector_connection_string() -> str:
    # SQLAlchemy defaults "postgresql://" to psycopg2, which we haven't
    # installed (we use psycopg v3 everywhere else) — explicitly tell it
    # to use psycopg v3 instead, by prefixing the scheme.
    url = settings.database_url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url

def _get_store(repo_full_name: str, kind: str) -> PGVector:
    last_error = None
    for attempt in range(3):
        try:
            return PGVector(
                embeddings=_get_embeddings_client("RETRIEVAL_DOCUMENT"),
                collection_name=_collection_name(repo_full_name, kind),
                connection=_pgvector_connection_string(), # changed — was settings.database_url directly
                use_jsonb=True,
            )
        except Exception as e:
            last_error = e
            time.sleep(2)  # give Neon a moment to finish waking up from auto-suspend
    raise last_error


def _store_has_data(repo_full_name: str, kind: str) -> bool:
    store = _get_store(repo_full_name, kind)
    # a real placeholder query, not empty — Gemini's embedding API rejects
    # empty strings outright; we only care whether ANYTHING comes back
    return len(store.similarity_search("placeholder", k=1)) > 0


def _replace_store_contents(repo_full_name: str, kind: str, entries: list[dict]) -> None:
    """entries: [{"anchor", "heading", "content"}, ...]. Wipes and
    rewrites — simplest way to guarantee the store matches reality."""
    store = _get_store(repo_full_name, kind)

    if kind == "docs-branch":
        existing_entries = []

        try:
            results = store.similarity_search("placeholder", k=1000)
            for result in results:
                existing_entries.append({
                    "anchor": result.metadata["anchor"],
                    "heading": result.metadata["heading"],
                    "content": result.page_content.split("\n\n", 1)[-1],
                })
        except Exception:
            existing_entries = []

        existing_by_anchor = {
            e["anchor"]: e for e in existing_entries
        }

        for entry in entries:
            existing_by_anchor[entry["anchor"]] = entry

        entries = list(existing_by_anchor.values())

    store.delete_collection()  # drop everything currently stored under this collection
    if not entries:
        return
    store = _get_store(repo_full_name, kind)  # collection was dropped, get a fresh handle
    texts = [f"{e['heading']}\n\n{e['content']}" for e in entries]
    metadatas = [{"anchor": e["anchor"], "heading": e["heading"]} for e in entries]
    store.add_texts(texts, metadatas=metadatas)


def get_or_build_readme_store(repo_full_name: str, installation_id: int) -> None:
    """only build if this repo's store doesn't already have data, not on every run."""
    if _store_has_data(repo_full_name, "readme"):
        return
    chunks = chunk_readme(repo_full_name, installation_id)
    entries = [{"anchor": c["anchor"], "heading": c["heading"], "content": c["content"]} for c in chunks]
    _replace_store_contents(repo_full_name, "readme", entries)


def refresh_docs_store(repo_full_name: str, kind: str, anchor_to_entry: dict[str, dict]) -> None:
    """kind='docs-branch': call right after writing suggestion files to a
    branch. kind='docs-main': call right after a merge lands them on main."""
    entries = [{"anchor": a, **v} for a, v in anchor_to_entry.items()]
    _replace_store_contents(repo_full_name, kind, entries)


def retrieve_relevant_sections(repo_full_name: str, installation_id: int, query: str, k: int = 6) -> list[dict]:
    get_or_build_readme_store(repo_full_name, installation_id)  # lazy build, per repo, on first use
    store = _get_store(repo_full_name, "readme")
    query_vector = _get_embeddings_client("RETRIEVAL_QUERY").embed_query(query)
    results = store.similarity_search_by_vector(query_vector, k=k)
    return [
        {"anchor": d.metadata["anchor"], "heading": d.metadata["heading"], "content": d.page_content.split("\n\n", 1)[-1]}
        for d in results
    ]


def get_current_content(repo_full_name: str, anchor: str, has_open_branch: bool) -> str | None:
    """The three-tier lookup, exact anchor match. Returns None if neither
    tier has anything — caller keeps the raw README content instead."""
    tiers = (["docs-branch"] if has_open_branch else []) + ["docs-main"]
    for kind in tiers:
        store = _get_store(repo_full_name, kind)
        results = store.similarity_search("placeholder", k=1, filter={"anchor": anchor})  # "placeholder" not "" — same fix as _store_has_data
        if results:
            return results[0].page_content.split("\n\n", 1)[-1]
    return None