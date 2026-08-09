# GitSteward

GitSteward is a GitHub App-based AI agent that watches a repository's commits, detects when code changes make `README.md` documentation stale, and proposes fixes as reviewable Pull Requests — with a human always in the loop. It never edits a repository's real documentation directly, and it never merges its own suggestions.

Built with **FastAPI**, **LangGraph**, **LangChain**, **Groq** (`llama-3.3-70b-versatile`), **Google Gemini** (`gemini-embedding-001`), **Chroma**, and **Postgres**.

> Demo repository used throughout development: [`Shivansh0047/RAG-Chatbot-Service`](https://github.com/Shivansh0047/RAG-Chatbot-Service) — a separate, unrelated FastAPI/RAG project used purely as a real-world test subject.

---

## What it does

1. A push lands on a watched repo's `main` branch.
2. GitSteward fetches the real code diff and retrieves the README sections most semantically related to that change (RAG over the actual README, not a hardcoded rule table).
3. An LLM judges which of those candidate sections are genuinely now inaccurate, and drafts a rewrite for each one.
4. The proposed rewrites are committed — as a **single commit** — to a reusable review branch, and opened as a Pull Request in an **isolated `gitsteward-docs/` folder**. The repository's real `README.md` is never touched.
5. The pipeline **pauses** at this point and waits, indefinitely, for a human to merge or close the PR on GitHub.
6. Once the human decides, GitSteward resumes automatically and records the outcome.

---

## Why it's built this way

**Human review is non-negotiable, not a nice-to-have.** GitSteward's write access is scoped so it can only ever create a throwaway branch, write files under `gitsteward-docs/`, and open a PR. It has no code path that calls a merge endpoint. This isn't just a convention — the LangGraph pipeline literally halts execution (via `interrupt()`) at the review gate and cannot proceed until a real GitHub event (a PR being closed) resumes it.

**Suggestions live in an isolated folder, not in the real docs.** Every proposal is written to `gitsteward-docs/<anchor>.md`, plus a full rebuilt-README preview (`gitsteward-docs/modified_gitsteward_readme.md`) and a running summary index (`gitsteward-docs/README.md`). Merging a GitSteward PR only merges these files — a human still chooses when and how to apply an accepted suggestion to the real `README.md`.

**A GitHub App, not a personal access token.** GitSteward authenticates as its own bot identity with least-privilege permissions (`Contents: read/write`, `Pull requests: read/write` — nothing else), so every action it takes is attributable to it specifically, not to a personal account.

**Section-level reasoning, not file-level.** Because most repositories document themselves in one `README.md` rather than a `docs/` folder, GitSteward reasons about individual `##`/`###` sections, each tagged with a GitHub-style anchor slug, and can propose a targeted fix to one section without touching the rest of the document.

**No local ML models.** Every LLM and embedding call goes through an API (Groq, Gemini) — chosen specifically to avoid loading large models into memory, since the target deployment (Render's free tier) has limited RAM.

---

## Architecture

```
gitsteward/
  bootstrap.py         # forces a safe native-library import order (Windows crash workaround)
  main.py              # FastAPI entrypoint, builds the vectorstore + graph at startup
  config.py            # all secrets/settings, loaded from .env
  webhooks.py           # receives + verifies GitHub webhooks, starts/resumes graph runs
  observability.py      # GET /runs/{run_id}/state and /timeline
  github_app.py         # all GitHub API interaction (auth, branches, commits, PRs)

  rag/
    readme_source.py    # fetches + chunks README.md, rebuilds the full-preview file
    embeddings.py        # in-memory Chroma vectorstore over the README, built at startup
    llm.py                # LLM reasoning: locate stale sections, rewrite them

  graph/
    state.py             # WorkflowState — the shared schema every node reads/writes
    build.py              # the LangGraph nodes and edges
    runtime.py            # compiles the graph with Postgres checkpointing; start_run() / resume_run()
    pr_tracking.py         # a small Postgres table mapping PR number -> waiting run(s)
```

### The pipeline, as a graph

```
resolve_branch → analyze → commit_and_pr → await_review → finalize
```

- **`resolve_branch`** — finds or creates the reusable review branch, and determines whether a PR already exists on it. Runs *before* analysis so later steps know what to compare against.
- **`analyze`** — for each changed file, retrieves candidate README sections, resolves the most current known text for each one (see below), and asks the LLM which are stale and how to rewrite them.
- **`commit_and_pr`** — writes every proposed file in a single batched commit (via GitHub's Git Data API — blob → tree → commit — not one commit per file), then opens or updates the PR.
- **`await_review`** — calls `interrupt()`. Execution genuinely halts here; the current state is checkpointed to Postgres and the graph waits, potentially for days, across server restarts, until a `pull_request: closed` webhook resumes it with the human's decision.
- **`finalize`** — marks every proposed section `updated` (if merged) or `skipped` (if closed without merging), and marks the run `done`.

### Resolving "what does this section currently say?"

Because GitSteward never edits `README.md`, a naive implementation would always compare against the original, unchanging README text — which breaks the moment more than one push happens before a PR is reviewed. GitSteward resolves each candidate section's current text in three tiers, in order:

1. **The currently open review branch's version**, if one exists (a prior, still-unmerged proposal for this exact section).
2. **`main`'s already-merged version**, if no open branch has one (a previously accepted proposal).
3. **The raw `README.md` section**, if neither of the above exists.

This means two independent pushes — say, one reverting an LLM choice and a later one reverting an embeddings choice — correctly accumulate into one coherent proposal on the same PR, instead of the second silently overwriting the first's work.

### Preventing self-triggering loops

GitSteward's own writes are themselves commits, which themselves fire `push` webhooks. Two separate guards prevent these from re-triggering analysis:
- Pushes to anything other than `refs/heads/main` are ignored outright (catches direct pushes to the review branch).
- Any changed file under `gitsteward-docs/` is filtered out of a push's file list before deciding whether to analyze anything (catches the merge commit itself, which — landing on `main` — would otherwise pass the first guard).

---

## Setup

### 1. Create the GitHub App
- Repository permissions: `Contents: Read and write`, `Pull requests: Read and write`.
- Subscribe to `push` and `pull_request` events.
- Generate a private key, install the App on the target repository, and note the App ID and Installation ID.

### 2. Environment
```
GITHUB_APP_ID=...
GITHUB_APP_PRIVATE_KEY_PATH=./github-app-private-key.pem
GITHUB_WEBHOOK_SECRET=...
GITHUB_INSTALLATION_ID=...
DEMO_REPO_OWNER=...
DEMO_REPO_NAME=...
GROQ_API_KEY=...
GOOGLE_API_KEY=...
DATABASE_URL=postgresql://...   # a free Neon or Supabase instance works
```

### 3. Install and run
```bash
pip install -r requirements.txt
uvicorn main:app --reload
```
For local development, GitHub can't reach `localhost` directly — use [smee.io](https://smee.io) as a relay:
```bash
smee --url https://smee.io/<your-channel> --target http://localhost:8000/webhook/github
```

---

## Observability

- `GET /runs/{run_id}/state` — the current, live state of any run, read directly from the Postgres checkpoint (no re-execution).
- `GET /runs/{run_id}/timeline` — every checkpoint the run has passed through, in order.
- `GET /health` — liveness check.

A run's state is durable across a full server restart, mid-`waiting_approval` — this has been verified directly: a run left paused, with the server killed and restarted, returns identical state from `/state` afterward.

---

## Known limitations / deliberate scope boundaries

- **Single repository per deployment**, currently. Multi-repo support is a planned but not-yet-built extension — it requires threading a `repo` parameter through every GitHub API call (currently hardcoded to one repo via `.env`) and resolving the correct installation ID per repo dynamically.
- **Accepting a suggestion does not apply it to `README.md`.** Merging a GitSteward PR merges `gitsteward-docs/`'s content into `main`; a human still copies the accepted text into the real README manually. This is a deliberate boundary, not an oversight — it keeps GitSteward's write surface minimal and reviewable.
- **The in-memory vector store is rebuilt from scratch at every server startup**, rather than persisted — a deliberate choice given Render's free-tier ephemeral disk, acceptable because it's only ever indexing one file.
- **`bootstrap.py`** works around a native-library import-order crash reproduced on Windows; it has not yet been confirmed necessary (or unnecessary) on the Linux environment used for deployment.

---

## Status

- **Phase 0 — Foundations**: complete. GitHub App auth, signature-verified webhook receiver.
- **Phase 1 — Mechanical pipeline**: complete (superseded by Phase 2's real reasoning; the original hardcoded lookup table, `doc_rules.py`, has been removed).
- **Phase 2 — LLM + RAG**: complete. Verified against multiple real semantic changes to the demo repository.
- **Phase 3 — LangGraph + Postgres persistence**: complete. Human-in-the-loop pause/resume verified for both approval and rejection paths, and across a real server restart.
- **Phase 4 — Test branch** (sandboxed test execution via GitHub Actions, triggered on `pull_request` events): deferred, not started.
- **Phase 5 — Deployment**: in progress.