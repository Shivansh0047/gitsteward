# A hardcoded file to test our changes are correctly reflected, only for Demo Rag file repo

import fnmatch

# Maps a glob pattern (matched against changed file paths) to the list of
# README section anchors that file change likely affects.
# Order doesn't matter — we check every pattern against every changed file.
RULES: list[tuple[str, list[str]]] = [
    ("app/routes/chat.py", ["post-chat"]),
    ("app/routes/ingest.py", ["post-ingestnote", "post-ingestupload"]),
    ("app/rag/llm.py", ["stack", "post-chat"]),
    ("app/rag/chain.py", ["stack", "post-chat"]),
    ("app/rag/embeddings.py", ["stack"]),
    ("app/rag/vectorstore.py", ["stack", "adding-a-new-project"]),
    ("app/config.py", ["required-environment-variables"]),
    ("app/auth.py", ["authentication"]),
    ("scripts/backfill_from_mongo.py", ["seeding-the-knowledge-base-one-time"]),
    ("requirements.txt", ["stack", "local-setup"]),
]

# Notes.md must never trigger anything and never be a target — hard exclude.
EXCLUDED_FILES = {"Notes.md"}


def match_anchors(changed_files: list[str]) -> dict[str, list[str]]:
    """
    Given a list of changed file paths, return a dict of
    { changed_file_path: [matching README anchors] } for every file that
    matched at least one rule. Files with no match, or in EXCLUDED_FILES,
    are simply not included in the result.
    """
    results: dict[str, list[str]] = {}

    for path in changed_files:
        if path in EXCLUDED_FILES:
            continue

        matched_anchors: list[str] = []
        for pattern, anchors in RULES:
            if fnmatch.fnmatch(path, pattern):
                matched_anchors.extend(anchors)

        if matched_anchors:
            results[path] = matched_anchors

    return results