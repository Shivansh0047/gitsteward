import json

from langchain_groq import ChatGroq

from config import settings
from rag.vectorstore import retrieve_relevant_sections, get_current_content  # replaces rag.embeddings + github_app's old tier lookup

_llm: ChatGroq | None = None

def _get_llm() -> ChatGroq:
    global _llm
    if _llm is None:
        _llm = ChatGroq(model="openai/gpt-oss-120b", api_key=settings.groq_api_key, temperature=0)
    return _llm

LOCATE_PROMPT = """You are reviewing a code change to decide which sections of a README are now stale.

Code diff (file: {file_path}):
{diff}

Candidate README sections (semantically related, may or may not actually be affected):
{candidates}

For each candidate section, decide if the diff makes it stale. Respond ONLY with a JSON array, no other text:
[
  {{"anchor": "...", "heading": "...", "is_stale": true/false, "reason": "one sentence, only if is_stale is true"}}
]
"""

REWRITE_PROMPT = """You are updating documentation to represent the CURRENT state of the code after the provided change.

Section: {heading}
Why it's stale: {reason}

Current section text:
{original_content}

Code diff that caused this (file: {file_path}):
{diff}

Rewrite the ENTIRE section body so that it best represents the CURRENT state of the code.

You have full freedom to:
- keep information that is still correct,
- modify information that is partially outdated,
- replace information that is now incorrect,
- remove information that is no longer relevant,
- add information that is necessary to accurately represent the current code.

Do NOT preserve old documentation merely because it existed before.
Do NOT write a history of the change.
The output should describe the current codebase as it exists AFTER the change.

Use the existing section's structure, tone, formatting style, and level of detail where they remain appropriate, but prioritize factual correctness over preserving the original wording.

Do not repeat the heading itself.
Respond with the complete rewritten section body only.
No preamble, no explanation, no markdown code fences.
"""

def locate_stale_sections(repo_full_name: str, installation_id: int, file_path: str, diff: str, has_open_branch: bool = False) -> list[dict]:
    candidates = retrieve_relevant_sections(repo_full_name, installation_id, diff, k=6)

    for c in candidates:
        existing = get_current_content(repo_full_name, c["anchor"], has_open_branch)  # tier 1/2 lookup, pgvector-backed
        if existing:
            c["content"] = existing  # prefer tier 1/2 over the raw README section

    # keep full candidate objects around, keyed by anchor — rewrite_section needs original_content later
    candidates_by_anchor = {c["anchor"]: c for c in candidates} # mapping anchor → full candidate object

    candidates_text = "\n\n".join(f"### {c['anchor']}\n{c['content']}" for c in candidates)
    prompt = LOCATE_PROMPT.format(file_path=file_path, diff=diff, candidates=candidates_text)
    response = _get_llm().invoke(prompt)

    try:
        verdicts = json.loads(response.content)
    except json.JSONDecodeError:
        return []  # LLM didn't follow the format — fail safe, flag nothing rather than crash

    stale = []
    for v in verdicts:
        if not v.get("is_stale"):
            continue
        candidate = candidates_by_anchor.get(v.get("anchor"))
        if not candidate:
            continue  # LLM hallucinated an anchor that wasn't actually a candidate — skip it
        stale.append({
            "anchor": v["anchor"],
            "heading": candidate["heading"],
            "original_content": candidate["content"],
            "reason": v.get("reason", ""),
        })
    return stale


#takes one flagged section (from locate_stale_sections()'s output) plus the diff, and asks the LLM to draft only the replacement body text
def rewrite_section(file_path: str, diff: str, stale_section: dict) -> str:
    prompt = REWRITE_PROMPT.format(
        file_path=file_path,
        diff=diff,
        heading=stale_section["heading"],
        reason=stale_section["reason"],
        original_content=stale_section["original_content"],
    )
    response = _get_llm().invoke(prompt)
    return response.content.strip()

def analyze_push_diffs(repo_full_name: str, installation_id: int, diffs: dict[str, str], has_open_branch: bool = False) -> dict[str, dict]:
    """
    Runs locate_stale_sections() once per changed file, then merges
    results by anchor — if two files both flag the same section, we
    combine their reasons instead of one write silently overwriting
    the other. Returns {anchor: {heading, original_content, reasons, diffs}}.
    """
    merged: dict[str, dict] = {}

    for file_path, diff in diffs.items():
        for section in locate_stale_sections(repo_full_name, installation_id, file_path, diff, has_open_branch=has_open_branch):  # repo/installation/has_open_branch threaded through
            anchor = section["anchor"]
            if anchor not in merged:
                merged[anchor] = {
                    "heading": section["heading"],
                    "original_content": section["original_content"],
                    "reasons": [],
                    "diffs": {},
                }
            merged[anchor]["reasons"].append(f"{file_path}: {section['reason']}")
            merged[anchor]["diffs"][file_path] = diff

    return merged


def rewrite_merged_section(merged_section: dict) -> str:
    """Rewrites one section using ALL contributing diffs, not just one file's."""
    combined_diff = "\n\n".join(
        f"--- {file_path} ---\n{diff}" for file_path, diff in merged_section["diffs"].items()
    )
    stale_section = {
        "heading": merged_section["heading"],
        "original_content": merged_section["original_content"],
        "reason": "; ".join(merged_section["reasons"]),
    }
    return rewrite_section("multiple files", combined_diff, stale_section)