# Verification on Gerald's computer

Verified 8 October 2026 on Fedora 44, Ryzen 7 5800X, RX 6600 8GB, 32GB system RAM. GTX 1050 Ti remained VFIO-owned throughout. No dual-GPU speed claim is made.

| Actual check | Result |
| --- | --- |
| Agent/sandbox/compiler/API/MCP/inference tests | 25 passed |
| 14B, 16k coding benchmark | Completed in four actions; independent behavior checks passed |
| 30B Q4_K_M, 16k coding benchmark | Completed in four actions; independent behavior checks passed |
| 30B Q4_K_M, 32k dashboard coding benchmark | Completed in four actions; independent behavior checks passed |
| 32k allocated context capacity check | Successfully processed 12,639 input tokens and generated a bounded JSON reply |
| Live source after benchmarks | 0 files differ from the starting manifest |

The final dashboard task took 162.0 seconds including model load, planning, reading, patching, checks, review and commit. This is a small utility task, not proof that arbitrary shell features or full interactive QML behavior are correct.

GPU measurements include the live desktop, approximately 0.9 GiB when idle. During the 32k feature run sampled GPU peak was 7.03 GiB and private inference cgroup memory peak sampled 14.00 GiB. During the longer context probe the peaks were 7.03 GiB GPU and 14.00 GiB host memory. The cgroup includes resident allocations and charged file cache; virtual mapped file size is not the same as resident RAM. The service's hard host-memory ceiling is 16 GiB.

The backend allocated 32,768 KV cells across 48 layers: 1,156 MiB of Q8 KV cache on CPU and 476 MiB on GPU. It offloaded 15/49 model layers, including the output layer. A complete 32k input prompt has not been exercised; 12,639 actual prompt tokens were processed with that full cache allocation. CPU token estimates include serialized metadata and intentionally exceed actual prompt tokens.

Baseline checked {"qml": 89, "shell": 17, "javascript": 9}. Preexisting QML warnings were retained; no unrelated warning cleanup was required. Changed JavaScript source passed syntax checks. Immutable Node assertions checked all three Zen Browser identities, Firefox regression, ordinary editor behavior and the New Tab case.

Actual task workspaces and commits:

- 14B: `0e774cd128b245c1afb390cc3ad1a603`, commit `e1da0ad839e40d5b8402151f18a139bbd5979f03`.
- 30B / 16k: `e5bd4570122449fa8a61df4cc035620a`, commit `7e49dde11373db44e8ae6f3d8fbcc464293a8cc5`.
- 30B / 32k through dashboard: `f42bad5b8b944788b779148952d2ae35`, commit `b122439bcb0234afc6fe664731f5e07b22ab3553`.

Task directories are under `/home/gerald/.local/share/local-coder/runs`. Benchmark reports are `qualification-power-16384.json`, `qualification-power.json`, and `context-qualification.json` in the same data root. Their model metrics report actual prompts, output counts, profile options and memory samples. Benchmarks remain unapplied.

The HTTP UI was exercised from prompt entry through completed checks and review. The real MCP stdio client discovered tools, read and patched a disposable file, executed its behavior check in the sandbox, and confirmed the original source was unchanged. Cancellation before the first inference token was also tested.

The GTX helper and launcher integration passed shell syntax checks. GPU policy tests cover VFIO ownership overriding stale visibility, host-visible dual Vulkan selection, manual VM reservation, and missing NVIDIA render devices. Live GTX rebinding, mixed-vendor inference and Windows startup after a nouveau handback remain unverified until administrator access is available.
