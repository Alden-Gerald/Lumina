# Lumina user-control engineering plan

This plan turns the October 2026 user-control audit into staged, reversible work. Each phase must preserve existing local data, remain honest about unavailable capabilities, and ship with tests before the next phase begins.

## Release 1 — recovery and account control (P0)

1. Add authenticated username/password rotation with current-password verification, strong input validation, atomic credential replacement, and optional invalidation of every existing LAN session.
2. Replace the single recovery action with **Continue once**, **Continue with instructions**, and **Create follow-up from preserved work**. Keep the three-attempt safety limit and surface the exact reason when continuation is unavailable.
3. Add a persisted, visible queue for model work. Show the active owner, allow queued work to be cancelled or reordered, and keep the existing single-model and memory constraints.

Acceptance: credential changes reject a wrong current password; old sessions can be invalidated; all three recovery paths preserve work; queued requests run in order and survive a service restart.

## Release 2 — storage, history, privacy, and recovery (P0/P1)

1. Add attachment usage totals, reference discovery, archive controls, and deletion only when no saved conversation or run references the file.
2. Add paginated/searchable chat history, rename/archive actions, and a reviewed-context flow for continuing a capped chat in a new conversation.
3. Make coding-preference collection explicit. Add inspect, redact, export, and delete controls. Default existing installations to their current behavior during migration, but make the setting visible and editable.
4. Add versioned JSON backup/restore for user-controlled metadata and conversations. Exclude credentials and raw model artifacts from exports.

Acceptance: referenced files cannot be deleted accidentally; archived chats remain recoverable; imports are validated before any write; privacy exports contain no patch text, file contents, or secrets.

## Release 3 — memory, knowledge, and research (P1)

1. Add an editable memory library with global/project scope, source attribution, enable/disable, and forget controls. Relevant enabled memories are injected as untrusted context and disclosed in each response.
2. Add a knowledge library backed by imported documents. Provide preview, provenance, scope, retrieval citations, and safe removal without deleting still-referenced source files.
3. Upgrade web research from snippets to bounded reads of permitted public HTML and PDFs. Validate every redirect and resolved address, cap bytes/time, extract passages, cite them, and show per-source failures.

Acceptance: memory and knowledge are separate; every injected item is attributable and removable; private/link-local destinations are rejected; responses distinguish snippets from fetched passages.

## Release 4 — datasets and optional training (P2)

1. Add JSON/JSONL dataset import with schema validation, redaction warnings, deduplication, provenance, and deterministic train/evaluation splits.
2. Keep evaluation and training as separate explicit operations. Training must be opt-in, create a versioned adapter/model artifact, record the base model and dataset hashes, run evaluation, and support activation rollback.
3. If no supported local trainer is installed, disable training with an actionable capability report. Never label document import, feedback, or retrieval as training.

Acceptance: invalid or duplicate rows are reported; evaluation data is never silently trained on; an activated artifact can be rolled back; unsupported training cannot be started.

## Cross-cutting design

- Data migrations are idempotent and use atomic writes with mode `0600`.
- Destructive operations require exact IDs and reference checks; backups are created before bulk restore.
- Local versus hosted processing, retention, exports, and deletion behavior are documented in Settings and the README.
- New APIs keep loopback host/origin checks and the per-session mutation token.
- Rollout is additive. Rollback removes new UI/API use while leaving versioned JSON records readable; no migration deletes old data.
- Tests cover authorization, migrations, queue ordering, retry budgets, reference-aware deletion, search pagination, memory scoping, dataset validation, and backup round trips.

