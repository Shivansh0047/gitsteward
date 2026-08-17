# GitSteward

**GitSteward is a GitHub App-based AI agent that keeps repository documentation aligned with code changes.**

It watches pushes to `main`, retrieves the README sections most relevant to a code change, uses an LLM to determine whether those sections have become stale, and proposes documentation updates through a human-reviewed Pull Request.

GitSteward **never edits the real `README.md` directly and never merges its own Pull Requests**.

Built with **FastAPI, LangGraph, LangChain, Groq GPT-OSS 120B, Google Gemini embeddings, PostgreSQL + pgvector, and GitHub Apps**.

> Primary development/demo repository: [`Shivansh0047/RAG-Chatbot-Service`](https://github.com/Shivansh0047/RAG-Chatbot-Service)

---

## What It Does

When code changes, documentation can silently become incorrect.

GitSteward automates the detection and proposal part of that workflow:

```text
Code push to main
       │
       ▼
GitHub App webhook
       │
       ▼
Fetch real code diff
       │
       ▼
Retrieve relevant README sections
       │
       ▼
LLM decides which sections are stale
       │
       ▼
LLM rewrites stale sections
       │
       ▼
Commit proposals to gitsteward-docs/
       │
       ▼
Open / update review PR
       │
       ▼
       interrupt()
       │
       ▼
Human reviews PR
       │
       ├──────────────┐
       │              │
     Merge           Close
       │              │
       ▼              ▼
    Resume           Resume
       │              │
       └───────┬──────┘
               ▼
          Finalize run
```

The real repository README remains untouched throughout the process.

---

## Core Design Principles

### Human approval is mandatory

GitSteward does not have a code path that merges its own Pull Requests.

The LangGraph workflow literally stops at the review gate using `interrupt()`. The run is checkpointed to PostgreSQL and remains paused until GitHub sends a `pull_request: closed` event.

A human therefore remains the final authority over every documentation suggestion.

### Suggestions are isolated from the real README

GitSteward writes its suggestions under:

```text
gitsteward-docs/
```

A review branch can contain:

```text
gitsteward-docs/
├── <anchor>.md
├── modified_gitsteward_readme.md
└── README.md
```

The actual repository `README.md` is never modified by GitSteward.

A GitSteward PR therefore contains proposed documentation, not an automatic modification of the repository's real documentation.

### GitHub App authentication

GitSteward authenticates as its own GitHub App identity rather than using a personal access token.

The App uses the repository permissions it needs:

- Contents: Read and write
- Pull requests: Read and write

Installation-specific access is handled dynamically from the GitHub webhook's `installation.id`.

### Section-level reasoning

GitSteward does not assume that documentation exists in a separate `docs/` directory.

Instead, it parses the real `README.md` into sections and reasons using GitHub-style anchors such as:

```text
#stack
#project-structure
#required-environment-variables
```

This allows GitSteward to identify and propose a targeted change to an individual section.

### API-based AI models

No local LLM or embedding model is loaded.

GitSteward currently uses:

- **Groq `openai/gpt-oss-120b`** for LLM reasoning and rewriting
- **Google Gemini `gemini-embedding-001`** for embeddings

This keeps the application lightweight enough for the intended free-tier deployment environment.

---

# Architecture

```text
gitsteward/
│
├── bootstrap.py
├── main.py
├── config.py
├── webhooks.py
├── observability.py
├── github_app.py
│
├── rag/
│   ├── readme_source.py
│   ├── vectorstore.py
│   └── llm.py
│
└── graph/
    ├── state.py
    ├── build.py
    ├── runtime.py
    ├── pr_tracking.py
    └── repo_registry.py
```

### `main.py`

FastAPI application entrypoint.

At startup it:

- compiles the LangGraph workflow
- initializes the PostgreSQL checkpointer
- ensures required metadata tables exist
- mounts webhook and observability routes

Vectorstores are **not** built at startup. They are created lazily when a repository is first used.

### `config.py`

Loads application configuration and secrets from environment variables using the project's settings configuration.

Important runtime configuration includes:

```text
GITHUB_APP_ID
GITHUB_APP_PRIVATE_KEY_PATH
GITHUB_WEBHOOK_SECRET
GROQ_API_KEY
GOOGLE_API_KEY
DATABASE_URL
```

Repository-specific installation information is obtained from webhook events in the live path.

### `github_app.py`

Contains GitHub API functionality:

- GitHub App authentication
- installation token exchange
- repository access
- retrieving commit diffs
- branch creation/reuse
- batched file commits
- Pull Request creation
- commit comments
- tracking-index generation

GitSteward uses the Git Data API to build a single commit containing all generated suggestion files.

### `webhooks.py`

Receives GitHub webhook deliveries and verifies the `X-Hub-Signature-256` HMAC signature.

It handles:

```text
push
pull_request
```

For push events it:

1. verifies the branch is `main`
2. extracts the repository and installation ID
3. registers the repository
4. separates GitSteward-generated documentation files from real code changes
5. handles merge-only `gitsteward-docs/` pushes
6. retrieves commit diffs
7. starts a LangGraph run

For Pull Request events it resumes the runs associated with a closed GitSteward PR.

### `observability.py`

Provides lightweight inspection endpoints:

```text
GET /health
GET /runs/{run_id}/state?repo=<repo>
GET /runs/{run_id}/timeline?repo=<repo>
```

These read persisted LangGraph state rather than re-executing the workflow.

### `rag/readme_source.py`

Responsible for README handling.

It:

- fetches `README.md`
- splits it into sections
- derives GitHub-style anchors
- provides the section data to the retrieval system
- rebuilds the full README preview with generated replacements

If a repository has no `README.md`, GitSteward now exits cleanly without starting an analysis run.

### `rag/vectorstore.py`

Provides the persistent pgvector-backed RAG layer.

GitSteward maintains three logical stores per repository:

```text
<repo>::readme
<repo>::docs-branch
<repo>::docs-main
```

#### `readme`

Contains the actual README sections.

Used for semantic candidate retrieval.

#### `docs-branch`

Contains the current proposals on the active GitSteward review branch.

This is the highest-priority source when an open review branch exists.

#### `docs-main`

Contains documentation proposals that have already been merged into `main`.

This provides durable memory after previous review cycles.

All three stores are isolated by repository name, allowing the same GitSteward installation to work across multiple repositories.

Vectorstores are created lazily on first use for each repository.

### `rag/llm.py`

Contains the AI reasoning layer.

The workflow has two main LLM operations.

#### Locate stale sections

For each changed file, GitSteward:

1. retrieves semantically related README sections
2. resolves the current content for each candidate using the tiered system
3. asks the LLM which candidates are actually stale

The LLM returns structured JSON describing stale sections and reasons.

Hallucinated anchors are ignored, and malformed JSON fails safely rather than crashing the run.

#### Rewrite stale sections

For each stale section, the LLM receives the relevant current section text and code diff and generates a complete replacement body.

The LLM is responsible for deciding what information should be:

- retained
- modified
- replaced
- removed
- added

The application does not attempt to perform semantic merging of documentation itself.

### `graph/state.py`

Defines the shared `WorkflowState` used by all LangGraph nodes.

Important state includes:

```text
repo
installation_id
run_id
sha
changed_files
diffs
branch
is_new_branch
pr_number
section_results
merged_result
status
```

Any value needed by a later node must exist in the workflow state so it survives checkpoints and resumes.

### `graph/build.py`

Defines the LangGraph workflow:

```text
resolve_branch
      ↓
analyze
      ↓
commit_and_pr
      ↓
await_review
      ↓
finalize
```

#### `resolve_branch`

Finds an existing open GitSteward PR or creates a new reusable review branch.

#### `analyze`

Runs retrieval, stale-section detection, and rewriting.

#### `commit_and_pr`

Writes generated suggestion files, updates the tracking index, commits everything together, and creates or updates the review PR.

#### `await_review`

Calls:

```python
interrupt(...)
```

and persists the workflow state.

#### `finalize`

Runs after the Pull Request closes and records whether the human accepted or rejected the suggestions.

### `graph/runtime.py`

Compiles the graph with PostgreSQL-backed LangGraph checkpointing.

It provides:

```text
start_run()
resume_run()
get_run_state()
get_run_timeline()
```

The checkpoint allows an analysis to pause for an arbitrary amount of time and resume later, including across process restarts.

### `graph/pr_tracking.py`

Maintains the mapping between:

```text
(repo, PR number)
        ↓
run IDs waiting for that PR
```

This allows one reusable GitSteward PR to be associated with multiple sequential analysis runs.

### `graph/repo_registry.py`

Maintains the repository registry:

```text
repo_full_name
installation_id
first_seen_at
```

Repositories are registered automatically when GitSteward receives their webhook events.

---

# Three-Tier Documentation Resolution

A major design problem appears when multiple pushes occur before a GitSteward PR is reviewed.

Suppose:

```text
Push 1 → proposes documentation change A

Push 2 → arrives before PR 1 is merged
```

If Push 2 always compared against the original README, the second proposal could overwrite or contradict the first.

GitSteward therefore resolves the current content of each candidate section in three tiers:

```text
                 Candidate Anchor
                        │
                        ▼
              ┌─────────────────┐
              │  docs-branch    │
              │  open proposal  │
              └────────┬────────┘
                       │ no match
                       ▼
              ┌─────────────────┐
              │   docs-main     │
              │ merged proposal │
              └────────┬────────┘
                       │ no match
                       ▼
              ┌─────────────────┐
              │     README      │
              │ raw main text   │
              └─────────────────┘
```

This means sequential pushes can reason from the most current known documentation state instead of always reverting to the stale README.

This behavior has been tested with multiple sequential pushes and an open review PR.

---

# Multi-Repository Support

GitSteward is repository-aware.

The live webhook path obtains:

```python
repo_full_name
installation_id
```

directly from GitHub.

The same GitHub App can therefore be installed on multiple repositories without creating a separate GitSteward server for each one.

Each repository receives independent vectorstore collections:

```text
Shivansh0047/RAG-Chatbot-Service::readme
Shivansh0047/RAG-Chatbot-Service::docs-main
Shivansh0047/RAG-Chatbot-Service::docs-branch

Shivansh0047/gitsteward::readme
Shivansh0047/gitsteward::docs-main
Shivansh0047/gitsteward::docs-branch
```

Repository-specific installation IDs and state are carried through the workflow.

Multi-repository behavior has been tested with multiple real repositories, including GitSteward analyzing its own repository.

---

# Preventing Self-Trigger Loops

GitSteward's own commits generate GitHub push events, so loop protection is necessary.

Two guards are used.

### Guard 1 — only analyze `main`

Pushes to:

```text
refs/heads/main
```

are eligible for analysis.

For example:

```text
refs/heads/gitsteward/doc-suggestions
```

is ignored.

### Guard 2 — merge-only GitSteward pushes

When a GitSteward PR is merged, the resulting push to `main` may contain only:

```text
gitsteward-docs/*
```

Such pushes are not treated as new documentation-analysis runs.

Instead GitSteward:

```text
reads the merged suggestion files
        ↓
rebuilds docs-main
```

This prevents GitSteward from reacting to its own merged output.

---

# Generated Pull Request Structure

A typical GitSteward review branch looks like:

```text
gitsteward-docs/
├── project-structure.md
├── stack.md
├── required-environment-variables.md
├── how-it-works.md
├── modified_gitsteward_readme.md
└── README.md
```

### Individual suggestion file

Each section proposal contains metadata such as:

```yaml
---
source_anchor: "README.md#stack"
source_commit: "<run-id>"
status: "updated"
---
```

followed by:

```text
Why flagged:
<reason>

<proposed section body>
```

### `modified_gitsteward_readme.md`

A complete preview of the README with the generated section replacements applied.

This allows a reviewer to see what the resulting README would look like without modifying the actual README.

### `gitsteward-docs/README.md`

A lightweight tracking index containing the latest status for every flagged README section.

It is a **latest-status index**, not a full historical log.

---

# Local Setup

## Prerequisites

You need:

- Python 3.10+
- a GitHub App
- a Groq API key
- a Google Gemini API key
- a PostgreSQL database with pgvector
- a GitHub repository where the App is installed

Neon is suitable for the PostgreSQL/pgvector database.

## 1. Clone

```bash
git clone https://github.com/Shivansh0047/gitsteward.git
cd gitsteward
```

## 2. Create a virtual environment

Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

Linux/macOS:

```bash
python -m venv venv
source venv/bin/activate
```

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

## 4. Configure environment variables

Create a `.env` file containing the required credentials.

Typical configuration:

```env
GITHUB_APP_ID=...
GITHUB_APP_PRIVATE_KEY_PATH=./github-app-private-key.pem
GITHUB_WEBHOOK_SECRET=...

GROQ_API_KEY=...
GOOGLE_API_KEY=...

DATABASE_URL=postgresql://...
```

Keep private keys, API keys, and `.env` files out of source control.

## 5. Configure the GitHub App

The GitHub App needs:

```text
Repository permissions
├── Contents: Read and write
└── Pull requests: Read and write
```

Subscribe to:

```text
push
pull_request
```

Install the App on the repositories GitSteward should watch.

The live application obtains the repository's installation ID from each webhook event; you do not need to hardcode a single repository for the production path.

## 6. Run locally

```bash
uvicorn main:app --reload
```

For local webhook testing, use a public webhook relay such as smee.io:

```bash
smee --url https://smee.io/<your-channel> --target http://localhost:8000/webhook/github
```

Then point the GitHub App webhook URL at the relay.

---

# Testing

GitSteward has been tested against multiple real repositories.

Important tested behaviors include:

- GitHub App authentication
- webhook HMAC verification
- README retrieval
- section-level RAG retrieval
- GPT-OSS 120B reasoning
- stale-section detection
- documentation rewriting
- review branch creation
- Pull Request creation
- reuse of an existing open GitSteward PR
- multiple sequential pushes before review
- human approval/rejection through the PR
- LangGraph `interrupt()` and resume
- Postgres-backed workflow durability
- merge-only self-trigger protection
- `docs-main` synchronization
- multi-repository state isolation
- repositories without a README
- GitSteward analyzing its own repository

A large architectural commit can produce very large LLM prompts and hit the Groq Free Plan's token-per-minute limit. This is currently an accepted limitation of the development/free-tier setup rather than a target for high-scale production handling.

---

# Observability

The application exposes:

```text
GET /health
```

Returns a basic liveness response.

For a specific run:

```text
GET /runs/{run_id}/state?repo=<repo>
```

returns the current persisted workflow state.

And:

```text
GET /runs/{run_id}/timeline?repo=<repo>
```

returns the checkpoint history of the run.

These endpoints are intended primarily for development and demonstration.

---

# Deliberate Scope Boundaries

GitSteward is designed as a **portfolio/interview project**, not as a high-scale production service.

The current target is a small number of repositories, such as 2–3 repositories, rather than hundreds of concurrent installations.

The project intentionally does not currently include:

- background job queues
- distributed workers
- horizontal scaling
- enterprise-grade concurrency handling
- automatic application of accepted documentation into the real `README.md`
- automated merging of GitSteward PRs
- the planned automated code-test branch

These can be explored later if the project grows.

---

# Current Model Stack

### LLM

```text
Groq
openai/gpt-oss-120b
```

Used for:

- stale-section reasoning
- documentation rewriting

### Embeddings

```text
Google Gemini
gemini-embedding-001
```

Used for:

- README indexing
- semantic retrieval
- pgvector document storage
- proposal store synchronization

### Vector Store

```text
PostgreSQL + pgvector
```

Three logical collections are maintained per repository:

```text
readme
docs-branch
docs-main
```

### Application

```text
FastAPI
LangGraph
LangChain
PyGithub
PostgreSQL
```

---

# Project Status

### Completed

- GitHub App authentication
- Signature-verified webhook receiver
- Section-level README parsing
- RAG-based candidate retrieval
- Gemini embedding integration
- GPT-OSS 120B migration
- LLM-based stale-section detection
- LLM-based documentation rewriting
- GitHub review branch workflow
- Batched multi-file commits
- Human-in-the-loop review using LangGraph `interrupt()`
- PostgreSQL-backed checkpointing
- PR/run tracking
- Multi-repository support
- Repository-specific vectorstores
- Three-tier documentation resolution
- Self-trigger protection
- `docs-main` synchronization
- README-missing graceful handling
- Observability endpoints
- Real end-to-end testing on multiple repositories

### Deferred

**Test branch / automated code verification**

A future phase is planned around:

```text
pull_request event
        ↓
GitHub Actions sandbox
        ↓
run tests
        ↓
diagnose failures
        ↓
retry
        ↓
combine test + documentation results
```

This is intentionally separate from the current documentation workflow.

### Current deployment phase

**Phase 5 — Render deployment**

The next major step is deploying the FastAPI service to Render and configuring the GitHub App webhook to use the deployed URL.

The PostgreSQL/pgvector database remains external, with Neon as the intended database provider.

---

# Project Roadmap

```text
Phase 0
GitHub App + webhook foundation
        ✅

Phase 1
Initial documentation pipeline
        ✅

Phase 2
LLM + RAG reasoning
        ✅

Phase 3
LangGraph + PostgreSQL durability + HITL
        ✅

Phase 4
Automated test branch
        ⏸ Deferred

Phase 5
Render deployment + live demo
        🚧 Current
```

---

# Demo Scenario

A useful GitSteward demonstration is:

```text
1. Make a real code change.
2. Push it to main.
3. GitHub sends the webhook.
4. GitSteward detects stale README sections.
5. GitSteward creates/updates its review PR.
6. Human reviews the proposed documentation.
7. Human merges or closes the PR.
8. GitSteward resumes from its PostgreSQL checkpoint.
9. A merge-only docs push updates docs-main.
10. The real README remains untouched.
```

The same workflow can then be demonstrated on a second repository to show multi-repository isolation.

---

# Why GitSteward?

GitSteward is intentionally built around a simple principle:

> **AI can propose documentation changes, but humans remain responsible for approving them.**

The interesting part is not simply using an LLM to rewrite Markdown. The project combines:

- GitHub App authentication
- webhook-driven automation
- semantic retrieval
- persistent vector memory
- LangGraph workflows
- PostgreSQL checkpointing
- human-in-the-loop execution
- multi-repository support
- GitHub Pull Requests as the review surface

The result is an agent that can continuously reason about whether a codebase and its documentation are still telling the same story — while keeping the final decision in human hands.