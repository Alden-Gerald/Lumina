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

## Hardware and models

| Profile | Exact Ollama model | Context | RX-only GPU layers | Dual GPU layers |
| --- | --- | ---: | ---: | ---: |
| Coding 30B MoE | `qwen3-coder:30b-a3b-q4_K_M` | 32,768 | 15 | 22 |
| Accuracy 14B | `qwen2.5-coder:14b-instruct-q4_K_M` | 16,384 | 28 | 38 |
| Balanced 9B (optional download) | `qwen3.5:9b` | 8,192 | 28 | 33 |

The 30B model has approximately 3.3B active parameters per token, but its entire
quantized weight set must remain accessible. Its download is about 19GB. CPU
offload allows a larger model to run while preserving GPU space for context.
More parameters do not guarantee a better patch; independent behavior checks
remain necessary. This coding model uses bounded action output rather than an
unlimited reasoning transcript.

The private inference service uses Vulkan, a quantized Q8 KV cache, one request
at a time, and a **16 GiB host-memory cap** (14 GiB soft pressure threshold,
no swap). That budget is an upper limit, not a permanent allocation. The model
unloads after a task, and after 30 seconds idle. Linux may retain reclaimable
file cache. RAM does not turn an 8GB GPU into a 24GB GPU: model layers and their
associated cache are distributed between GPU and CPU; transfers and CPU memory
bandwidth limit speed.

The agent refuses to start the 30B profile with less than 16 GiB available host
RAM, or the smaller profiles with less than 8 GiB. Windows currently has an
8 GiB allocation and a 16 GiB maximum; increasing its allocation may require
using the 14B profile or stopping inference. Sandboxed commands have a separate
4 GiB ceiling, not a reserved allocation.

The original Ollama service on port 11434 remains separate. If another app has
a model loaded there, unload it before a task. Local Coder uses port 11435 and
its own model store. Cloud inference is disabled.

## GTX 1050 Ti and Windows

Both cards can be considered by the common Vulkan backend when both are visible
to Linux. This is layer distribution, not a unified 12GB GPU. The slower GTX
can increase capacity without increasing speed; dual mode requires a real
benchmark before any speed claim. CPU offload continues in either mode.

The initial setup had the GTX **bound to VFIO at boot**. During the later Chat
validation both cards were host-visible with nouveau/NVK and real mixed-GPU
inference completed. Linux cannot use a VFIO-owned card just because Windows is
shut down. A side-by-side speed comparison and a live Windows handback test are
still pending. The RX-only path is fully operational.
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
start/resume. A running dual-GPU task is cancelled with its files preserved and
our inference runner stopped before libvirt can detach the GTX. Existing RX-only
tasks continue. Subsequent tasks rediscover hardware and use RX + CPU/RAM.
Use `local-coder vm-reserve` before starting Windows through another application.
VM shutdown does not itself clear a manual reservation: run `vm-release` when
Windows is off and the GTX is actually host-visible. Mode changes occur between
tasks; there is no seamless migration of a generation in progress.

Launcher backup:
`/home/gerald/.local/share/local-coder/win11-launch.before-local-coder`.

## Command line

```bash
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

## Chat and study mode

The dashboard has **Chat** and **Code** tabs. Mathematics is rendered locally using vendored KaTeX 0.19.0 (MIT license, package integrity checked). Chat uses `qwen3:14b` (14.8B,
Q4_K_M) with a 16,384-token context, 24 RX-only GPU layers (32 verified in dual
mode), CPU offload, and the same private inference service capped at 16 GiB.
Chat needs at least 12 GiB available host RAM. It has no file-editing or terminal
tools. Paste lecture notes, ask worked problems, or request practice questions.
Conversation history is saved locally and complete recent exchanges are retained
within the context budget. After 50 exchanges, start a new chat.

**Reason carefully** enables the model's thinking capability. Thinking and final
answer share a 4,096-token limit; direct mode has a 2,048-token limit. Each reply
has a 15-minute deadline and a Stop button. Internal thinking text is not displayed
or saved. If reasoning consumes its limit without producing an answer, the app
tries one bounded direct answer using the remaining time. A length-limited answer
is labeled; ask a follow-up to continue. Reasoning does not guarantee correctness.

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

## Image attachments

Both modes support **Attach images**, pasting a screenshot, and dropping images
onto the attachment area. Up to two PNG, JPEG or WebP images can be attached,
4 MiB each. Images are decoded, stripped of metadata, resized to at most 1024px
on their longest edge, and kept privately in the local data directory. Animated
images, SVG, and files exceeding 12 million pixels are rejected.

A separate `qwen3.5:4b` Q4_K_M local vision model reads each image with an 8k
context and 16 GPU layers. It unloads before the coding or study model starts.
The larger text models receive its description and visible text. This keeps
image processing within the same memory budget; the 30B coding model itself is
not a vision model. Very small screenshot text may need a tighter crop.

Attachments and conversations remain on disk for task history; clearing the
composer does not delete an attachment already associated with a saved task.
Private data lives under `/home/gerald/.local/share/local-coder`, outside this Git
repository. Do not expose the model, search or dashboard ports to your network.

The Chat/Code separation and SearXNG approach were informed by the
[Odysseus project](https://github.com/odysseus-dev/odysseus). This implementation
adds these focused capabilities to the existing bounded agent; it does not
install or copy Odysseus's broader workspace.
