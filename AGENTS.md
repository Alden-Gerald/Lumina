# Local AI handoff

For implementation requests that change code in this repository, delegate the
complete bounded task through `local_ai_handoff.handoff_to_local_ai`. Send a
concise task and explicit acceptance criteria. Use the `quality` profile unless
the user explicitly selects another installed profile. When the user attaches a
Codex image, include its complete local `/tmp/codex-clipboard-...` path in
`attachment_paths` so Local Coder receives the image. After the tool accepts the task,
report its run ID and end the Codex turn. Do not implement the change in Codex
and do not poll the local task automatically.

Always pass `source_path` for the project that actually owns the requested
change. Orbit Shell, Quickshell, display, bar, popup, and desktop-widget changes
use `/home/gerald/dotfiles/quickshell`, even when Codex is currently opened in
this Local Coder repository. Codex-originated tasks use `auto_apply=true`; after
validation Local Coder applies the guarded patch, reloads Orbit Shell, and asks
OpenClaw for a read-only desktop inspection.

Use `local_ai_handoff.get_handoff_status` only when the user asks for progress.
Use `local_ai_handoff.get_handoff_diff` only when the user explicitly requests a
Codex review or when a local task reports `needs_attention`. Dashboard-originated
tasks keep the manual Apply gate. For a Codex handoff, automatic apply is
permitted only after Local Coder's checks and model review pass; source-conflict
detection must remain enabled.

Do not delegate explanations, planning-only requests, status questions, or
read-only reviews. Also keep the task in Codex when the user explicitly asks
Codex to implement it directly. If the handoff tool is unavailable, explain the
failure and continue in Codex only when that matches the user's request.
