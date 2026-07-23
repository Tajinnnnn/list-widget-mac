---
name: mentor-review
description: Get your uncommitted changes in this repo reviewed by a senior-engineer mentor persona that teaches while it reviews — direct explanations for real bugs/security-adjacent issues, leading questions for style/design teaching moments. Use when the user says "/mentor-review", "review my code", "check what I just wrote", or asks for feedback on code they just wrote in this repo.
---

# mentor-review

Dispatch the `senior-mentor-reviewer` subagent (via the Agent tool, `subagent_type: senior-mentor-reviewer`) to review the repo's current uncommitted changes.

1. Do NOT pre-filter or summarize the diff yourself — let the subagent read `git status`/`git diff HEAD` and full file context itself, per its own instructions.
2. Launch it in the foreground (`run_in_background: false`) — the user is waiting on this review, not moving on to other work.
3. Show the subagent's report to the user as-is. Don't compress or re-summarize it — the teaching structure (direct vs. leading-question) is the point.
4. If the user then asks a follow-up question about a specific finding, answer directly in this conversation — no need to re-dispatch the subagent for a single follow-up.
