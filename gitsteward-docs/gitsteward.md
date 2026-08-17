---
source_anchor: "README.md#gitsteward"
source_commit: "c4b5a1e28c1a43d0965da65e2e1ed1eb186b9d02"
status: "updated"
---

**Why flagged:** rag/llm.py: The README still lists the Groq model as `llama-3.3-70b-versatile`, but the code now uses `openai/gpt-oss-120b`.

GitSteward is a GitHub App‑based AI agent that watches a repository's commits, detects when code changes make `README.md` documentation stale, and proposes fixes as reviewable Pull Requests — with a human always in the loop. It never edits a repository's real documentation directly, and it never merges its own suggestions.  

Built with **FastAPI**, **LangGraph**, **LangChain**, **Groq** (`openai/gpt-oss-120b`), **Google Gemini** (`gemini-embedding-001`), **Chroma**, and **Postgres**.  

> Demo repository used throughout development: [`Shivansh0047/RAG-Chatbot-Service`](https://github.com/Shivansh0047/RAG-Chatbot-Service) — a separate, unrelated FastAPI/RAG project used purely as a real‑world test subject.
