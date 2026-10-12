# Installed architecture

```mermaid
flowchart TD
    U[Local dashboard or CLI: one task + acceptance checks] --> C[Single-task controller]
    C --> G[Detect VM ownership and host-visible Vulkan GPUs]
    G --> L[Private Ollama: quantized model + CPU offload]
    C --> W[Snapshot current project into disposable Git workspace]
    W --> B[Baseline source checks]
    B --> P[Model produces a short structured plan]
    P --> A[One bounded JSON action]
    L <--> A
    A --> R[List, search, read source]
    A --> F[Hash-checked exact file patch]
    A --> S[Offline terminal sandbox]
    R --> O[Observation]
    F --> O
    S --> E[Exit status + bounded compiler output]
    E --> O
    O --> A
    A --> V[Verify syntax and required behavior tests]
    V -->|Failure: concrete feedback| O
    V -->|Pass| Q[Fresh model review of diff + evidence]
    Q -->|Findings| O
    Q -->|Approved| K[Commit exact verified workspace]
    K --> D[Dashboard: diff and check evidence]
    D -->|User applies| X[Check source conflicts, back up, apply files]
```

Model inference is sequential. The reviewer is a fresh request to the same local
model, rather than another simultaneous GPU process. It is a second pass, not an
independent model guarantee. Required tests supplied by the operator are separate
from both model passes.

The trusted controller owns model options, task budgets, validation and commit.
The model cannot change context size, load models, increase resource budgets,
apply to the live checkout, access the host GPU through a shell command, or call
Git commit. Repository text and terminal output are presented as untrusted data.
There is no `eval` of model output.

The model emits `summary`, `tool`, and `arguments` matching a constrained JSON
schema. `summary` is a short visible action description, not a reasoning transcript.
Planning/review use smaller separate schemas. Reads return the complete current
file hash even when the requested source range is truncated. File patches require
that hash and a unique exact match, preventing stale and ambiguous replacements.

Command code executes in a separate user/PID/network/IPC/mount namespace with
its own constrained process-tree scope. The read-only source mount prevents
commands from bypassing surgical edits or weakening tests. Scratch build files
can be written inside bounded `/tmp`; logs are captured outside the task source.

The controller stores each plan, action, observation, check and model metric.
The next request includes the task, plan, recent failure ledger and recent complete
turn pairs. Old pairs are discarded when CPU tokenizer accounting approaches
the configured window, reserving 2,500 tokens for template/generation overhead.
Oversized actions and repeated output are rejected before execution.

Before committing and before applying, the exact source inventory must match the
inventory that passed validation. Apply also requires the original source files
to match the task's starting manifest. Unrelated user edits remain untouched.

Hardware selection happens at task boundaries. The inference process uses only
the selected Vulkan devices. NVIDIA bound to VFIO is excluded even if a stale
enumeration claims it exists. Explicit VM reservation excludes it too. A mode
change restarts only the private inference service; it does not mutate PCI drivers.
Mixed-vendor distribution and handback remain subject to real driver qualification.

## Study conversations and visual inputs

The loopback HTTP server owns both Managers and a shared activity lock. Starting
a code run checks the chat worker; starting a reply checks the coding worker.
The workers retain the inference slot through cleanup/unload. GPU handback
cancels both classes of active work if the current hardware policy is dual mode.

Chat: user question + saved complete recent pairs → optional image reader →
optional bounded query plan → Google-first SearXNG → validated public result
links and bounded snippets → Qwen3 14B thinking/text stream → saved final answer
and source metadata. Search never hands shell/file tools to the chat model.
The dashboard polls the saved stream every 2.5s. It renders text with DOM nodes,
not arbitrary model-generated HTML. All network requests require a local session
token, valid Host and same-origin checks at the dashboard boundary.

Image uploads have bounded compressed size, pixels and concurrent decodes. The
normalized image has a content hash and an opaque local ID; inference validates
it before use. The 4B image reader returns constrained factual JSON. Models run
sequentially and image descriptions remain explicitly untrusted/approximate.

SearXNG is an independently pinned upstream checkout with its own virtualenv,
loopback listener and systemd resource limits. The agent consumes only its search
result JSON and does not fetch arbitrary returned URLs, reducing URL-fetch abuse.
Search queries are the only university-study data deliberately sent online by
this implementation when search is enabled. Code command sandboxes stay offline.
