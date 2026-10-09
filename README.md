# Local Coder

A local coding agent installed for Gerald's Quickshell workspace. Open
[the dashboard](http://127.0.0.1:8787) or launch **Local Coder** from the desktop.
Describe one feature, include acceptance criteria, and choose a model. The agent
plans, reads source, applies exact replacements, observes errors, checks its work,
requests a separate model review, and commits in a disposable task workspace.
**Apply checked changes** copies the reviewed result into your original project,
with conflict checks and a backup. Reload Quickshell yourself when ready.

Your existing uncommitted Quickshell files are included in each starting snapshot.
Tasks never reset your checkout, touch its Git history, or restart the live shell.
Existing tests are protected from edits; the agent can add regression tests.

## Lumina on the home network

From a laptop on the `192.168.18.0/24` home network, open
**https://lumina.local:8443** and sign in as `lumina`. Lumina uses a private
local certificate authority (CA). Its public certificate is
`~/.local/share/local-coder/lan/lumina-ca.crt` and is also available at
`https://lumina.local:8443/lumina-ca.crt`. Trust this CA on each laptop or
browser that will use Lumina. Verify its SHA-256 fingerprint before installing:
`28:DB:AA:16:C4:0D:15:C6:24:FA:41:35:0B:16:05:BF:6A:14:17:B1:9C:95:7B:AC:DC:2E:E4:E4:D2:E6:26:48`.
Never copy or install `lumina-ca.key` on another device. The CA is already
trusted in this computer's Fedora and Chromium/Brave certificate stores.
Fully restart an open browser after adding the CA. Renew the
server certificate (without replacing the CA) with
`/home/gerald/local-coder/.venv/bin/python /home/gerald/local-coder/scripts/lumina-cert.py`.
The first password is generated during setup; change it from this computer with
`/home/gerald/local-coder/.venv/bin/python /home/gerald/local-coder/scripts/lumina-set-password.py`.

`lumina-mdns.service` publishes the name through Avahi, and
`lumina-gateway.service` provides HTTPS login and forwards signed-in requests to
the dashboard on `127.0.0.1:8787`. The gateway listens only on `192.168.18.5`
and rejects clients outside `192.168.18.0/24`. Sessions expire after 12 hours;
five failed logins from one address trigger a one-minute lockout. The model,
search, and dashboard services continue to listen only on loopback.
Fedora's firewall must allow the HTTPS entrance for this subnet. Apply its
restricted rule with `sudo /home/gerald/local-coder/scripts/lumina-open-firewall`.

## Hardware and models

| Role / profile | Exact Ollama model | Context | Assigned GPU layers |
| --- | --- | ---: | ---: |
| Default automatic builder 7B | `qwen2.5-coder:7b-instruct-q4_K_M` | 8,192 | RX 6600: all layers |
| Optional builder 14B | `qwen2.5-coder:14b-instruct-q4_K_M` | 8,192 | RX 6600: 28; remainder CPU |
| Read-only helper 2B | `qwen3.5:2b-q4_K_M` | 4,096 | GTX 1050 Ti: all 25 |
| Optional coding 30B MoE | `qwen3-coder:30b-a3b-q4_K_M` | 32,768 | RX 6600: 15; remainder CPU |
| Balanced 9B (optional download) | `qwen3.5:9b` | 8,192 | RX 6600: 28 |

The instruction-tuned 7B builder is the default. It writes a private per-run
`roadmap.md`, works in small bounded actions, and checks every edit before moving
on. A recoverable `needs attention` result automatically continues at most three
times using the preserved workspace and failure evidence. **Parallel assistants** lets one 2B worker
serve a scout, a test assistant and up to two reviews sequentially while the
builder works. Helpers receive bounded excerpts and have no file or command
interfaces. Findings are advisory; only the builder edits. After each patch, CPU
checks run against an immutable revision in a read-only sandbox. Old results
cannot approve newer files. The final builder review and exact-revision checks still
gate the local commit. Supply a required behavior test for stronger evidence;
syntax checks alone do not prove that a UI works.

Failed actions followed by successful recovery actions are saved locally as
sanitized preference pairs in `~/.local/share/local-coder/training/`. Patch text,
file contents, attachment data and command arguments are omitted. Later automatic
runs use only bounded tool/failure patterns from this preference memory. This is
not silent weight training; the records are suitable input for a separately
validated offline adapter-training release after enough high-quality pairs exist.

See [the implementation roadmap](docs/parallel-agents-roadmap.md).

The 30B model has approximately 3.3B active parameters per token, but its entire
quantized weight set must remain accessible. Its download is about 19GB. CPU
offload allows a larger model to run while preserving GPU space for context.
More parameters do not guarantee a better patch; independent behavior checks
remain necessary. This coding model uses bounded action output rather than an
unlimited reasoning transcript.

Both private inference workers use Vulkan, a quantized Q8 KV cache and one
request per worker. They share a **single 16 GiB systemd slice cap** (14 GiB soft
pressure threshold, no swap). The helper also has a 4 GiB ceiling. That budget is an upper limit, not a permanent allocation. The model
unloads after a task; coding requests keep it warm for up to five minutes
between actions, and chat requests for 30 seconds. Linux may retain reclaimable
file cache. RAM does not turn an 8GB GPU into a 24GB GPU: model layers and their
associated cache are distributed between GPU and CPU; transfers and CPU memory
bandwidth limit speed.

The agent refuses to start the 30B profile with less than 16 GiB available host
RAM, or the smaller profiles with less than 8 GiB. Windows currently has an
8 GiB allocation and a 16 GiB maximum; increasing its allocation may require
using the 14B profile or stopping inference. Sandboxed commands have a separate
4 GiB ceiling for interactive tools and a 2 GiB ceiling for background checks,
not reserved allocations.

The original Ollama service on port 11434 remains separate. If another app has
a model loaded there, unload it before a task. Local Coder uses port 11435 and
its own model store. Cloud inference is disabled.

## GTX 1050 Ti and Windows

The RX 6600 is exclusively assigned to the builder on port 11435. The GTX,
when host-visible through nouveau/NVK, runs a separate helper on port 11436.
Their VRAM is not pooled. Real concurrent inference has been qualified on this
machine; performance gains depend on the task, and the older GTX has relatively
slow prompt processing. CPU offload remains on the builder.

A VFIO-owned or manually reserved GTX cannot run the helper, even if Windows
is shut down. Helpers are skipped while unavailable; they never fall back to
CPU alongside the offloaded builder. The RX builder and CPU checks continue.
Physical Windows handback still needs a live VM test; manual reservation has
been tested without changing PCI bindings.
An administrator can return the secondary GPU to nouveau/NVK while all VMs are
off:

```bash
sudo /home/gerald/local-coder/scripts/gtx-host-enable
local-coder vm-release
local-coder gpu-status
```

The helper verifies this machine's GTX PCI identity, refuses an active VM or boot
display GPU, changes only the secondary graphics function, and attempts to restore
VFIO on binding failure. It leaves the GTX audio function with VFIO. It was
prepared and syntax checked; live rebinding has not been tested because this
session has no passwordless administrator access. Kernel boot configuration
and VM XML were not changed. Reboot restores the current VFIO boot policy.

The existing `win11-launch` now reserves the GTX for Windows before requesting
start/resume. The GTX helper service and its runner stop before libvirt can detach the card.
The RX builder continues without a restart. Subsequent tasks rediscover whether
the GTX is available; use `local-coder vm-release` after returning it to the host.
Use `local-coder vm-reserve` before starting Windows through another application.
VM shutdown does not itself clear a manual reservation: run `vm-release` when
Windows is off and the GTX is actually host-visible. Mode changes occur between
tasks; there is no seamless migration of a generation in progress.

Launcher backup:
`/home/gerald/.local/share/local-coder/win11-launch.before-local-coder`.

## Command line

```bash
local-coder run 'Fix one bounded feature automatically' --profile roadmap \
  --check 'node --test tests/window-title.test.js'
local-coder run 'Add one small feature and preserve the existing layout' --profile power \
  --acceptance 'Describe expected behavior and edge cases'
local-coder run 'Fix this utility' --profile quality \
  --check 'node --test tests/window-title.test.js'
local-coder list
local-coder show TASK_ID
local-coder diff TASK_ID
local-coder cancel TASK_ID
local-coder apply TASK_ID
local-coder doctor
```

The optional check is a required test supplied by you, separate from the model's
review. Put build outputs in `/tmp` because command execution sees a read-only
source checkout. For example, configure a compiler to output `/tmp/program`, or
copy source to `/tmp/build` before a build that insists on writing alongside it.
Install dependencies yourself before a task; sandbox commands have no network.

Limits: 24 actions, 30 minutes, eight changed files, 400 changed lines, 1,536
generated tokens per action. Repeated actions, three malformed/truncated outputs,
out-of-memory errors, failed baseline checks, and three failed reviews stop a
task with its partial workspace and observations preserved. An interrupted task
does not automatically resume. Inspect its diff and start a smaller follow-up.

Large features need several bounded tasks. QML syntax and lint are checked,
but whole-shell rendering and interaction cannot be inferred from a syntax pass.
Supply a behavior test when possible and inspect visual behavior after applying.

## MCP and other interfaces

### Hand off a complete Codex task to the local AI

The dedicated handoff MCP lets Codex emit one compact task request and then end
its turn while Local Coder plans, edits, checks and reviews asynchronously. It
returns only compact status evidence; model transcripts and full command logs
stay local. Dashboard tasks retain the manual Apply gate. A Codex handoff can
request guarded automatic apply after checks and review pass.

Add this stdio server to the Codex configuration for the project you want the
local model to edit:

```toml
[mcp_servers.local_ai_handoff]
command = "/home/gerald/.local/bin/local-coder"
args = ["handoff-mcp", "--source", "/absolute/path/to/project"]
```

The server exposes `handoff_to_local_ai`, `get_handoff_status`,
`get_handoff_diff`, and `cancel_handoff`. A successful handoff starts the normal
bounded Local Coder controller through the loopback dashboard service and returns
immediately. Pass `source_path` when the requested change belongs to a different
project than the server default. Codex should not poll automatically; follow progress in
[the local dashboard](http://127.0.0.1:8787), or ask Codex to check the saved run
ID. With `auto_apply=true`, source-conflict checks still run before the verified
patch reaches the live project. For Orbit Quickshell, the shell is then reloaded
and OpenClaw performs a read-only screenshot inspection of the live desktop.

When Lumina is already open, it polls for new Codex-originated runs and switches
from Chat or the manual task form to the live task automatically. Codex clipboard
images are uploaded to the local attachment store before the run starts. If a
requested model profile is not installed, the handoff selects the installed
`quality` profile instead of creating a run that immediately fails.

This repository's `AGENTS.md` automatically chooses that handoff for future code
implementation requests. Planning, explanations and read-only reviews stay in
Codex, and an explicit request for Codex to implement directly overrides the
handoff.

For streamable HTTP on loopback instead of stdio:

```bash
local-coder handoff-mcp --source /absolute/path/to/project --http --port 8002
```

The existing MCP interface below is different: it gives an external agent
low-level tools inside one disposable snapshot rather than delegating the whole
task to Local Coder.

The MCP SDK exposes typed `list_dir`, `search_code`, `read_file`, `file_patch`,
`create_file`, `run_command`, `verify`, and `workspace_info` tools. Each MCP server
starts in its own disposable snapshot and cannot apply to the live project.

MCP clients can launch this stdio command:

```json
{
  "mcpServers": {
    "local-coder": {
      "command": "/home/gerald/.local/bin/local-coder",
      "args": ["mcp", "--source", "/home/gerald/dotfiles/quickshell"]
    }
  }
}
```

For a client that supports streamable HTTP:

```bash
local-coder mcp --http --port 8001
```

Connect to `http://127.0.0.1:8001/mcp`. The included dashboard is the installed
interface; OpenHands/Open WebUI were not installed. Compatible clients can use
the private Ollama endpoint and MCP tools, but should retain equivalent task and
memory limits. Direct chat clients bypass the controller's bounded coding loop.

## Isolation and recovery

Commands use bubblewrap namespaces, an empty home, cleared environment, no host
network, no host devices, no desktop session, and read-only toolchain mounts.
Git metadata is read-only. Only the validated file tools can write task source.
Resource limits apply to the process tree; timeouts and cancellation kill it.
Execution fails closed if isolation or resource limits are unavailable. This
shares the host kernel and is not a VM boundary against kernel exploits.

The dashboard binds only to loopback. Host/Origin checks and a per-service token
protect mutations from browser cross-origin requests. It has no cloud telemetry.
Task prompts, logs, backups and model files remain under
`/home/gerald/.local/share/local-coder`. Source snapshots exclude common secret
paths and ignored files, but cannot discover arbitrary secrets embedded in code.

```bash
systemctl --user status local-coder local-coder-ollama
systemctl --user stop local-coder local-coder-ollama
systemctl --user start local-coder-ollama local-coder
journalctl --user -u local-coder-ollama -n 100
```

## Implementation and verification

1. Typed tool harness and MCP with path checks, hash-checked exact replacements,
   source snapshots and an offline command sandbox.
2. JSON action scaffold, bounded streaming Ollama requests, persistent task/event
   logs, CPU tokenizer accounting and a local dashboard.
3. Exit codes and compiler observations returned to the model; required checks
   and validation of the exact final file inventory gate commits and apply.
4. Sequential model review, Q4 weights/Q8 cache, GPU selection at task boundaries,
   CPU offload, host-memory limits and hardware qualification benchmarks.

Run the meaningful harness, sandbox, error-repair, API and MCP tests with:

```bash
cd /home/gerald/local-coder
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/qualify-model.py --profile power
```

The hardware benchmark adds Zen Browser recognition in a disposable Quickshell
snapshot. Independent Node assertions cover all three Zen IDs, Firefox regression,
ordinary app labels and new-tab titles. It never applies its result to your shell.
Measurements and actual run IDs are in `docs/verification.md`.

Model metadata: [Qwen3-Coder tags](https://ollama.com/library/qwen3-coder/tags),
[Qwen3-Coder overview](https://ollama.com/library/qwen3-coder),
[Ollama GPU support](https://docs.ollama.com/gpu),
[Ollama context and KV cache settings](https://docs.ollama.com/faq),
[Mesa NVK support](https://docs.mesa3d.org/drivers/nvk.html).

## OpenClaw desktop agent

OpenClaw uses the private Ollama service on port 11435 and can control this
Hyprland Wayland desktop through the [local Wayland plugin](integrations/openclaw-wayland/README.md).
Open its local dashboard with `/home/gerald/.openclaw/bin/openclaw dashboard`.

## Chat and study mode

The dashboard has **Chat** and **Code** tabs. Mathematics is rendered locally using vendored KaTeX 0.19.0 (MIT license, package integrity checked).

Chat's **AI model** selector defaults to **Auto**. Auto chooses from installed
models within the available host RAM budget. With **Structured answer** enabled,
complex questions prefer the 7B instruction model and run a bounded
decompose–solve–synthesize workflow: two to five non-overlapping subproblems,
one local answer per part, then one coverage-checked final answer. Roadmap format
and synthesis coverage each receive at most one repair attempt. Short greetings
and artifact-building requests bypass the workflow. Without it, study questions
prefer `qwen3:14b`; short greetings/translation without structured answering prefer
`qwen3.5:4b`; coding questions without structured answering prefer the 30B coding model,
then the 14B coding model. Longer conversation history keeps greetings on the
study model. You can select a model manually; unavailable choices are disabled.
Auto uses deterministic routing, not a separate model. The actual selected model
and reason appear in the activity log. The completed answer displays its smaller
question roadmap and whether each part was solved or limited. Direct coding models
disable the structured control. Chat remains a conversation: use **Code** to
edit project files.

The default study model is `qwen3:14b` (14.8B,
Q4_K_M) with a 16,384-token context, 24 RX-only GPU layers (32 verified in dual
mode), CPU offload, and the same private inference service capped at 16 GiB.
Study 14B needs at least 12 GiB available host RAM; Quick chat and Coding 14B need 8 GiB, and Coding 30B needs 16 GiB. Quick chat uses the already installed 4B image model in text mode, with an 8k context and all 33 layers on the RX 6600. It has no file-editing or terminal
tools. Paste lecture notes, ask worked problems, or request practice questions.
Conversation history is saved locally and complete recent exchanges are retained
within the context budget. After 50 exchanges, start a new chat.

**Deep Thinking** enables the model's thinking capability. Thinking and final
answer share a 4,096-token limit; direct mode has a 2,048-token limit. Each reply
has a 15-minute deadline and a Stop button. Internal thinking text is not displayed
or saved. If reasoning consumes its limit without producing an answer, the app
tries one bounded direct answer using the remaining time. A length-limited answer
is labeled; ask a follow-up to continue. The control explicitly warns that Deep
Thinking takes longer. Reasoning does not guarantee correctness.

Chat shows **Working / Done / Failed / Stopped**, an animated stage indicator,
and streamed answer text with a writing cursor. Expand **Working for / Worked
for** to see actual model selection, image reading, search queries, retrieved
source counts and engine warnings, thinking/writing stages, and memory release.
Completed and failed turns retain their own activity history. Internal reasoning
is not exposed. The running timer updates every second and freezes at completion:
`10s`, `1m 10sec`, `1hr 5min 15sec`. Service restarts mark interrupted work failed.

**Google web search** is optional and off by default. It plans one search query
(or up to three with reasoning), searches through a local SearXNG service, then
synthesizes search snippets with numbered citations and expandable source links.
Only queries go to search engines; model inference stays local. Google is tried
first. On this connection Google currently rejects the SearXNG WML endpoint, so
Yahoo/Startpage, Mwmbl/Wikipedia, then Bing/DuckDuckGo are available as clearly labeled fallbacks.
Obviously unrelated results are discarded. Search failures are shown rather than
invented. This is bounded web-assisted chat, not exhaustive full-page research:
the app reads search snippets, not full articles or PDF links.

Search runs on loopback port 8788 with a separate 512 MiB memory ceiling and one
CPU core quota. Pinned source version and dependency lock are recorded in
`/home/gerald/.local/share/local-coder/search-version.txt` and
`search-requirements.lock.txt`; settings are `search-settings.yml` there.
`local-coder-search.service` starts at user login. Chat and Code are serialized
at the API boundary so their models never intentionally overlap in memory.

## File attachments

Both modes have **Attach files**. In Chat, previews and file cards appear above
text inside the same composer. Select multiple files using the plus button, drop
files onto the composer, or paste an image. Supported files:

- PDF with selectable text; Word `.docx`; Excel `.xlsx` and legacy `.xls`.
- PowerPoint `.pptx`, CSV, UTF-8/UTF-16 TXT, Markdown, JSON, and log files.
- Still PNG, JPEG, WebP images, through the existing local image reader.

Attach up to **four files per message**, including at most **two images**.
Documents are limited to **10 MiB each**; images to **4 MiB each**. Unsupported
formats, encrypted documents, malformed archives and unreadable files produce
an explanation before submission. Old Word `.doc` and PowerPoint `.ppt` need
exporting to `.docx`/`.pptx`; macro-enabled Office formats are not accepted.

Documents are read on the CPU in a separate Bubblewrap process with no network,
no GPU, one read-only input file, a 256 MiB virtual-memory limit per process,
14/15-second CPU soft/hard limits, a 20-second wall deadline and bounded output.
The dashboard retains its 512 MiB service cap. PDF reading uses the already
installed Poppler `pdfinfo`/`pdftotext`; Office/text readers use `openpyxl`,
`xlrd`, `defusedxml` and the standard library. Dependencies are recorded in
`pyproject.toml`. Nothing executes macros, formulas, links or embedded programs.

Extraction retains at most **200,000 characters**, the first **80 PDF pages**
or **80 slides**, and the first **10 Excel sheets / 5,000 rows / 64 columns** per
sheet with a **20,000-cell** total ceiling. Office archives must fit a 32 MiB
uncompressed limit. The file card shows text readiness and expandable reading
limits. PDFs without selectable text need screenshots; there is no automatic
OCR. Word/PDF/slide diagrams, charts, embedded images and slide speaker notes
are not interpreted by the document reader. Excel formulas appear as text,
not calculated results.

The tutor selects up to eight relevant passages across attached files using
local lexical retrieval and the chosen model's token budget. Broad summaries
sample passages across each file; they are not exhaustive whole-document
reviews. Auto prefers Study 14B when documents are attached. Follow-up questions
can retrieve from the four most recently attached documents without uploading
again. Answers cite labels such as `[F1: Page 2]`; expand **File passages** to
inspect the exact supplied text. Document reading appears in the activity log.
Code can use selected passages as reference specifications in its existing
bounded task sandbox.

Images are decoded, stripped of metadata, resized to at most 1024px on the
longest edge, and read sequentially by `qwen3.5:4b` Q4_K_M with an 8k context
and 33 GPU layers on the RX 6600. It unloads before the main model starts. Animated images,
SVG, and files over 12 million pixels are rejected. Document reading does not
load another GPU model or expand the fixed inference memory/context limits.

Raw files and extracted text remain privately on disk with content hashes.
Clearing the composer does not delete saved attachments. Document links download
as data with an attachment disposition; images retain their JPEG previews.
Private data lives under `/home/gerald/.local/share/local-coder`, outside this
Git repository. Search query planning does not receive attachment contents;
only the user's question is used for external queries when search is enabled.
Do not expose the model, search or dashboard ports to your network.

The Chat/Code separation and SearXNG approach were informed by the
[Odysseus project](https://github.com/odysseus-dev/odysseus). This implementation
adds these focused capabilities to the existing bounded agent; it does not
install or copy Odysseus's broader workspace.

## Response actions, feedback and conversation optimization

Each completed Chat answer has thumbs up/down, **Redo in a new branch**, **Copy
response**, and a **More** menu. Rating the same thumb again clears the rating.
Rated answers have an optional correction/usefulness note saved locally. More
can branch the conversation at that answer, download the answer as Markdown,
export that answer's feedback as JSON, or expand its recorded activity log.
Clipboard failures show selectable text instead of claiming a successful copy.

Redo generates one bounded reply using the current model/Deep Thinking/search
controls. It starts a new branch from the original question, excludes that
answer and any later turns from the prompt, preserves prior context and saved
attachments, and includes a saved feedback note if present. **Open original
chat** returns to the untouched original. Branching without redo includes the
selected answer and lets you explore a different follow-up. Ratings are separate
for copied or regenerated answers. A failed/stopped retry preserves its original.

Feedback is stored alongside its exact response in the private conversation
file. Export records contain the rating/note, answer, real model/generation
settings, exact inference messages, search snippets and selected file passages.
Answers generated before this feature lack an exact input snapshot and their
export explicitly reports `context_complete: false`; no context is invented.
**Ratings do not update model weights automatically.** These records can support
later human review or a separately designed, validated training process.

The live **Machine activity** list shows actual recent operations, with
icons; expand **Activity log** to inspect timestamps and recorded details. Each
answer retains its own history. Code logs name the real tool operation (reading,
editing, running a command, checking). Chat has no command-execution tools and
does not fabricate such activity. Private thinking text is never logged.

Before a Chat reply, automatic context optimization retains the system prompt,
latest question/sources and recent complete exchanges. When older exchanges no
longer fit, it adds a small CPU-selected memory of earlier excerpts, prioritizing
the initial question and words relevant to the current question. The log reports
how many exchanges/excerpts were retained and when optimization ran. This is
extractive memory, not an exhaustive summary: details may be omitted, so repeat
critical facts if needed. The complete original conversation remains on disk.
No additional model is loaded and fixed context/GPU/16 GiB RAM limits remain.
Oversized current questions/sources fail clearly instead of exceeding the budget.

Code also reports its existing context compaction when it trims older tool turns;
it retains its anchored task, plan, recent failure ledger and newest observations.
All operations remain in the saved activity log. Compaction does not resume a
stopped task or remove the existing action/time/patch/review limits.

## User control, retention, and recovery

Settings is the control center for locally retained data. Account controls rotate
the optional LAN username and password only after the current password is
verified; choosing session invalidation makes the gateway reject older session
cookies on their next request. Credentials and password hashes are never exported.

When one local model job is active, new dashboard requests enter a persisted FIFO
queue instead of being discarded. Settings shows which kind of work owns the
model and lets queued items move up, move down, or be cancelled. Coding failures
offer one continuation, a continuation with reviewed instructions, automatic
recovery, or a fresh recovery generation from the preserved workspace. Each
generation retains the three-attempt safety limit and explains when it is reached.

Conversation history supports server-side search and pagination, rename/archive,
and a reviewed-context continuation into a new chat. Attachment storage reports
bytes and every saved conversation/task reference. Archiving keeps bytes and
references; permanent deletion is allowed only when no saved work references the
file. Metadata backups are versioned JSON and exclude credentials, raw attachment
bytes, and model artifacts. Restore creates a local safety snapshot first and
does not overwrite an existing conversation ID.

Personal memory and the knowledge library are separate. Memory contains small,
editable user facts or preferences with global/project scope. Knowledge imports
documents, retains source attribution, retrieves bounded passages, and exposes
the exact `[K…]` passages used by an answer. Forgetting a memory or removing a
knowledge entry does not masquerade as model training.

Web search sends only the planned query to the configured search service. For up
to three public results, Lumina may additionally read bounded HTML/text/PDF
content after validating redirects and resolved addresses; private, loopback,
link-local and unverifiable destinations are rejected. The response shows whether
it used a fetched passage, a snippet fallback, or encountered a retrieval error.

Recovery-preference collection is local and user controlled. Existing installs
retain the previous enabled behavior until it is changed in Settings. Records can
be inspected, exported, redacted for common secret patterns, or deleted. Dataset
imports validate JSON/JSONL rows, deduplicate examples, retain provenance and use
a deterministic held-out evaluation split. Importing documents, ratings, memories,
or datasets does not update model weights. Adapter training remains disabled until
a supported, evaluated and rollback-safe local trainer is integrated; Settings
reports that limitation rather than presenting a placeholder as working.

The staged rollout and rollback requirements are documented in
[`docs/lumina-user-control-plan.md`](docs/lumina-user-control-plan.md).
