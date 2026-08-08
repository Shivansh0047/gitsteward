import psycopg
from config import settings


def _get_conn():
    return psycopg.connect(settings.database_url, autocommit=True)


def ensure_table() -> None:
    """One-time table creation"""
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pr_runs (
                repo TEXT NOT NULL,
                pr_number INTEGER NOT NULL,
                run_id TEXT NOT NULL,
                PRIMARY KEY (repo, pr_number, run_id)
            );
        """)


def record_pr_run(repo: str, pr_number: int, run_id: str) -> None:
    """Called once a run knows its real PR number — links this run to that PR."""
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO pr_runs (repo, pr_number, run_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING;",
            (repo, pr_number, run_id),
        )


def get_runs_for_pr(repo: str, pr_number: int) -> list[str]:
    """Called when a PR closes — which run_id(s) were waiting on it?"""
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT run_id FROM pr_runs WHERE repo = %s AND pr_number = %s;", (repo, pr_number))
        return [row[0] for row in cur.fetchall()]