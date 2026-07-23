---
name: sec-review
description: Get your uncommitted changes in this repo audited for security issues — secrets, injection points, insecure storage, Keychain/entitlement/sandbox misuse. Use when the user says "/sec-review", "security review", "is this safe to ship", or asks whether code they just wrote has security problems.
---

# sec-review

Dispatch the `security-reviewer` subagent (via the Agent tool, `subagent_type: security-reviewer`) to audit the repo's current uncommitted changes.

1. Do NOT pre-filter or summarize the diff yourself — let the subagent read `git status`/`git diff HEAD` and full file context itself, per its own instructions.
2. Launch it in the foreground (`run_in_background: false`) — the user is waiting on this before deciding whether to commit.
3. Show the subagent's report to the user as-is.
4. If the user asks a follow-up question about a specific finding, answer directly in this conversation — no need to re-dispatch the subagent for a single follow-up.
