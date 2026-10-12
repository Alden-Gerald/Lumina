# Lumina

Lumina is a private, local-first workspace for chatting, studying, and completing
bounded coding tasks with models running on your own machine. It combines a calm
web interface with guarded file edits, isolated command execution, visible checks,
and explicit control over when a verified patch reaches your project.

![Lumina chat workspace showing local model controls and file attachments](docs/assets/lumina-code-workspace.png)

## What it does

| Workspace | Highlights |
| --- | --- |
| **Chat** | Local conversations, structured answers, optional web search, source activity, and branching. |
| **Code** | Task planning, precise file edits, isolated checks, model review, diff inspection, and guarded apply. |
| **Files** | PDF, Office, text, spreadsheet, and image attachments with bounded local extraction. |
| **Control** | Theme selection, model choice, queues, history, retention controls, backups, and recovery tools. |

Lumina keeps inference and project work local by default. Web search is optional;
when enabled, only the planned search query and bounded public-page requests leave
the machine. The interface identifies search, file-reading, model, and validation
activity instead of presenting hidden work as certainty.

## Safety model

Coding tasks run in disposable Git workspaces. The model receives a constrained
tool set and cannot directly apply changes to the source checkout. File edits use
hash-checked replacements, commands run offline against read-only source, and the
exact revision must pass validation before a local commit can be produced.

Applying a result is a separate guarded step:

1. Lumina verifies that the source files still match the task's starting state.
2. It creates a backup of affected files.
3. It copies only the checked result into the project.

This is defense in depth, not a promise that model output is correct. Supply a
behavior check for important work and review visual changes before applying them.
See [the architecture](docs/architecture.md) for the complete flow.

## Requirements

- Python 3.11+
- Git
- Ollama-compatible local inference on `127.0.0.1:11435`
- Bubblewrap for the offline command sandbox
- A Vulkan-capable GPU setup matching the profiles in
  [`local_coder/settings.py`](local_coder/settings.py)

The checked-in profiles are tuned for the project's current Linux workstation
and model inventory. Treat them as a reference configuration when adapting Lumina
to different hardware.

## Run from source

Replace `REPOSITORY_URL` with this repository's HTTPS clone URL.

```bash
git clone REPOSITORY_URL Lumina
cd Lumina
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/local-coder doctor
.venv/bin/local-coder serve
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). Keep the dashboard and model
services on loopback unless you have configured the repository's authenticated
LAN gateway and firewall rules for your own network.

## Use the CLI

Start one bounded task with a concrete outcome and, when possible, an independent
check:

```bash
local-coder run "Add a compact battery indicator" \
  --source /absolute/path/to/project \
  --profile roadmap \
  --acceptance "Show charging state without changing the bar layout" \
  --check "node --test tests/battery-indicator.test.js"
```

Inspect and control saved runs:

```bash
local-coder list
local-coder show RUN_ID
local-coder diff RUN_ID
local-coder cancel RUN_ID
local-coder apply RUN_ID
```

Large changes should be split into several observable tasks. Commands run without
network access, so install dependencies before starting a task and direct build
artifacts to `/tmp` when a tool expects to write beside read-only source.

## Models and resource limits

Lumina includes profiles for a 7B roadmap builder, a 14B builder, a 30B MoE coding
model, and an optional read-only helper. Chat, document reading, image reading,
and coding share a bounded local inference budget and are scheduled to avoid
unsafe overlap.

The controller limits actions, elapsed time, changed files, changed lines, output
tokens, and recovery attempts. Unavailable helpers are skipped; a failed check or
conflicting source state stops the task with its work preserved.

## Attachments and privacy

Lumina can read selectable-text PDFs, DOCX, XLS/XLSX, PPTX, CSV, plain text,
Markdown, JSON, logs, and still PNG/JPEG/WebP images. Parsing is bounded by file
size, page/row limits, time, and memory. Documents with scanned text need OCR
before upload, and embedded macros or programs are never executed.

Conversations, task records, attachments, backups, and model data live outside
the repository under `~/.local/share/local-coder`. Settings provides history,
archive, retention, backup, preference-memory, and credential controls. Imported
documents, ratings, memories, and datasets do **not** update model weights.

## Integrations

Two MCP interfaces are available:

- `local-coder mcp` exposes low-level tools inside one disposable snapshot.
- `local-coder handoff-mcp` accepts a complete bounded coding task and runs it
  asynchronously through the normal planning, checking, and review gates.

The optional OpenClaw Wayland integration is available in
[`integrations/openclaw-wayland`](integrations/openclaw-wayland).

## Development

Run the test suite from an environment with the project dependencies installed:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Hardware qualification is separate from unit tests:

```bash
.venv/bin/python scripts/qualify-model.py --profile power
```

Useful references:

- [Architecture](docs/architecture.md)

## Project layout

```text
local_coder/                   controller, sandbox, chat, storage, and web UI
local_coder/web/               browser interface and vendored front-end assets
integrations/openclaw-wayland/ optional desktop-control integration
scripts/                       setup, qualification, certificate, and GPU helpers
services/                      example user-service units
tests/                         unit and integration coverage
```

Lumina is evolving around one principle: local AI should remain inspectable,
bounded, and under the user's control.
