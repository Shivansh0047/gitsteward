"""Tracks every repo GitSteward has ever received a webhook from, and which
installation authenticates it. Auto-populated — never manually edited."""
import psycopg
from config import settings


def _get_conn():
    return psycopg.connect(settings.database_url, autocommit=True)


def ensure_table() -> None:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS repos (
                repo_full_name TEXT PRIMARY KEY,
                installation_id BIGINT NOT NULL,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)


def register_repo(repo_full_name: str, installation_id: int) -> None:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO repos (repo_full_name, installation_id)
            VALUES (%s, %s)
            ON CONFLICT (repo_full_name) DO UPDATE SET installation_id = EXCLUDED.installation_id;
            """,
            (repo_full_name, installation_id),
        )


def get_installation_id_for_repo(repo_full_name: str) -> int | None:
    """For offline use (test.py) — look up a repo we've already seen live."""
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT installation_id FROM repos WHERE repo_full_name = %s;", (repo_full_name,))
        row = cur.fetchone()
        return row[0] if row else None