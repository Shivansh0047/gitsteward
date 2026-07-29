# Workflow of testforge

1. Github App - A GitHub App is a separate, independent bot identity — like giving a contractor their own keycard that only opens specific doors (permissions you choose), only in specific buildings (repos you install it on), and every action it takes shows up in the log. We gave 2 permissions - Contents (read/write, so it can create files/branches) and Pull requests (read/write, so it can open PRs).
2. Set up smee.io — a free relay service, because GitHub can't send webhook notifications to localhost on your laptop. It forwards GitHub → smee's public URL → down to your local server.
3. github_app.py - GitHub Apps authenticate in two stages:
    1. JWT (JSON Web Token) — a short-lived token signed with your private key, proving "I am the TestForge App itself." Valid for ~10 minutes.
    2. Installation token — you exchange that JWT for a second token scoped specifically to one installation (i.e., "TestForge, but specifically as installed on RAG-Chatbot-Service"). This is the token that actually has permission to read/write files, open PRs, etc. Valid for ~1 hour.
We are using a lib called py github which handles both.
