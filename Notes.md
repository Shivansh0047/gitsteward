# Workflow of testforge

1. Github App - A GitHub App is a separate, independent bot identity — like giving a contractor their own keycard that only opens specific doors (permissions you choose), only in specific buildings (repos you install it on), and every action it takes shows up in the log. We gave 2 permissions - Contents (read/write, so it can create files/branches) and Pull requests (read/write, so it can open PRs).
2. Set up smee.io — a free relay service, because GitHub can't send webhook notifications to localhost on your laptop. It forwards GitHub → smee's public URL → down to your local server.
3. github_app.py - GitHub Apps authenticate in two stages:
    1. JWT (JSON Web Token) — a short-lived token signed with your private key, proving "I am the TestForge App itself." Valid for ~10 minutes.
    2. Installation token — you exchange that JWT for a second token scoped specifically to one installation (i.e., "TestForge, but specifically as installed on RAG-Chatbot-Service"). This is the token that actually has permission to read/write files, open PRs, etc. Valid for ~1 hour.
We are using a lib called py github which handles both.
4. webhooks - a endpoint, Whenever something happens on RAG-Chatbot-Service (a push, a PR closed, etc.), GitHub sends an HTTP request to this URL with details about what happened, as JSON. But there's a security problem: that URL is public (via smee.io, and later your real deployed server). Anyone on the internet could send a fake POST request pretending to be GitHub. So GitHub signs every real request with a signature, computed using the webhook secret you set when creating the App
5. We use hmac.compare_digest() instead of == because it takes the same amount of time to run regardless of where strings differ. A plain == can leak timing information an attacker could use to guess the correct signature byte-by-byte. This is a real technique called a "timing attack," so this isn't just being overly cautious.
6. We need the RAW bytes of the body — not a parsed dict — because the signature was computed over those exact raw bytes. If we parsed to JSON first and re-encoded it, whitespace/ordering differences would make our recomputed signature not match GitHub's, even on legitimate request.
7. Live test - make sure server is running, start smee tunnel using *smee-client --url https://smee.io/B4XkYr4oSi9Bzg7w --target http://localhost:8000/webhook/github*. Whenever GitHub sends something there (because that's the Webhook URL we configured on the App), smee-client immediately forwards it down to http://localhost:8000/webhook/github — the exact endpoint we just built
8. doc_rules - given a list of changed file paths, figure out which README sections might be affected, without AI, for testing. every pattern in RULES is hand-written against RAG-Chatbot-Service's actual file layout (app/rag/llm.py, app/routes/chat.py, etc.) and its actual README section anchors.
9. Next we will write a new branch creating and writing file logic

* Branch Logic - TestForge must never commit directly to main. Every proposed doc change has to go through a Pull Request that a human approves, this is done for security reasons. TestForge creates a new branch, TestForge writes files only into test-forge-docs/ on that branch — never touching README.md, never touching any real code file. TestForge opens a Pull Request: head = test-forge/a1b2c3d, base = main. This PR's diff shows only the new/changed files under test-forge-docs/, then It just posts a short comment on the original commit like "Opened PR #7 for review" and waits.the human, review the PR on GitHub like any normal PR — read the diff, and either merge it (approving the suggestion) or close it without merging (rejecting it). We will have a one single resuable brnach instead of creating ner brenches. On a push, check: is there already an open  PR from a test-forge/* branch, If yes → reuse that same branch, just write/update the files on it (the existing PR automatically shows the new commits, no new PR needed), If no → this is either the first run, or the last suggestion was just merged/closed — so create a fresh branch and open a new PR.
10. when TestForge wrote stack.md via the GitHub API, that write is itself a commit — which fires its own push webhook event straight back to your server. Your code correctly received it, ran it through match_anchors(), found nothing (because test-forge-docs/* paths aren't in our RULES table), and safely did nothing. This is a subtle but important thing to have proven: TestForge's own writes don't cause infinite loops, precisely because nothing under test-forge-docs/ is itself a trigger. Worth remembering as a design rule going forward — if we ever add logic that reacts to changes in test-forge-docs/, we'd need to guard against this deliberately. For now, it's naturally safe.
11. We have now a tracking which which stores the summary of what testforge has done in testforge/README.md, which can alsact as memory for LLM, to counter Renders cold start.
12. A nice fact why test runs directly in terminal are slow - Every time you run python -c "...", it's a brand new Python process, from scratch, every single time. So you're paying "cold start" cost every single time. This won't be a problem once it's running as a real server. When we run this inside FastAPI via uvicorn, all those imports happen once, at server startup — not per-request.
13. The retrival was not getting good results, so we shouldn't treat retrieval as the final decision-maker. The right design is: widen k (say, to 6 or 7, instead of 3) so we're less likely to leave out a genuinely relevant section just because its raw vector distance happened to be middling, and then hand all of those candidates — plus the actual code diff — to the LLM, and let it make the real judgment call. Adding Headings to emebddings inproved results as well.
14. Working of some files
    1. rag/readme_source.py - 
        Fetches and chunks the demo repo's README.md for retrieval.
        fetch_readme(): pulls README.md from GitHub; raises ReadmeNotFoundError
        if it doesn't exist (a future version will generate one from the code
        in that case — not built yet).

        chunk_readme(): splits the README into one chunk per section using
        LangChain's MarkdownHeaderTextSplitter, tagging each chunk with a
        GitHub-style anchor slug (e.g. "post-chat") so results can be matched
        back to doc_rules.py and linked directly in generated PRs.

        Notes.md is never referenced anywhere in this file — it's excluded by
        construction, not by a filter.
    2. rag/embeddings.py
        In-memory semantic search over the chunked README, via Chroma + Gemini
        embeddings.

        Rebuilt fresh at server startup (not persisted to disk) since Render's
        free tier wipes disk on cold start/redeploy — cheap to rebuild since
        we're only ever embedding one file's worth of sections.

        Uses Gemini's task_type parameter (RETRIEVAL_DOCUMENT for the README
        chunks, RETRIEVAL_QUERY for search queries) since this is an asymmetric
        search: short queries vs. longer reference text.

        Retrieval alone is not the final judge of relevance — see rag/llm.py's
        locate_stale_sections(), which takes retrieval's top candidates and
        lets an LLM make the actual staleness call.