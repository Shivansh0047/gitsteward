---
source_anchor: "README.md#what-it-does"
source_commit: "0febe9d33e56c484faab549fc953c5f469f7558b"
status: "updated"
---

**Why flagged:** webhooks.py: The pipeline now aborts early when a repository lacks a README.md, so the description that it always fetches and rewrites README sections is no longer accurate.

1. A push lands on a watched repository’s `main` branch.  
2. GitSteward fetches the real code diff. It then looks for a `README.md` in the repository; if none is found, the pipeline aborts early, logs “No README.md found … — nothing to analyze,” and does nothing further.  
3. When a `README.md` is present, the system retrieves the sections most semantically related to the change (RAG over the actual README, not a hard‑coded rule table).  
4. An LLM evaluates those candidate sections, decides which are now inaccurate, and drafts a rewrite for each.  
5. All proposed rewrites are bundled into a **single commit** on a dedicated review branch, placed inside an isolated `gitsteward-docs/` folder, and opened as a Pull Request.  
6. The pipeline **pauses** at this point and waits indefinitely for a human to merge or close the PR on GitHub.  
7. Once the human decides, GitSteward resumes automatically, records the outcome, and (if merged) syncs the documentation store via the RAG vectorstore.
