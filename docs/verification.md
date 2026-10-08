# Verification on Gerald's computer

Verified 8 October 2026 on Fedora 44, Ryzen 7 5800X, RX 6600 8GB, 32GB system RAM. GTX 1050 Ti was VFIO-owned for the initial coding benchmarks. Later attachment and Chat tests found both cards host-visible with nouveau/NVK. No dual-GPU speed improvement is claimed.

| Actual check | Result |
| --- | --- |
| Agent/sandbox/compiler/API/MCP/inference/chat/image tests | 53 passed |
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

The GTX helper and launcher integration passed shell syntax checks. GPU policy tests cover VFIO ownership overriding stale visibility, host-visible dual Vulkan selection, manual VM reservation, and missing NVIDIA render devices. Live execution of the GTX rebinding helper and Windows startup after a nouveau handback remain unverified. Later mixed-vendor inference tests are recorded below.

## Images and study Chat

The real browser Attach images button uploaded the generated Battery 73% reference
in Code and Chat. The 4B image model read that text correctly. The coding pipeline
then patched a disposable Python fixture, passed immutable checks at 0%, 73% and
100%, passed model review, and created commit
`124827f52e04ef3c500726f4830337706f01a1e5` in run
`bdfbcd3df9c549fcacb3fc1d9483c39b`. The 30B code stages used 22 GPU layers,
32k allocated context, and unloaded the vision model before code inference.
Sampled AMD GPU peak was 7.08 GiB including the desktop; private host-memory peak
was 9.49 GiB. Source fixture edits remain unapplied.

Real study conversation `3827fcd094dc4050a7e4ebc5ef10f79e` used Qwen3 14B Q4_K_M
with thinking enabled, 16k allocated context and 32 GPU layers across both cards.
It correctly solved A=[[2,1],[1,2]]: eigenvalues 3 and 1, eigenvectors (1,1) and
(1,-1), checked both matrix-vector products, and supplied a practice question.
The inference took 616.92s and generated 1,430 tokens including thinking. No
truncation occurred. Sampled AMD total GPU peak was 5.90 GiB and inference cgroup
RAM peak 13.57 GiB. Logs report approximately 4,858 MiB allocated on RX, 2,981 MiB
on GTX, and a 16k Q8 KV cache split across GPU and CPU. This proves mixed-device
operation for this task; it does not establish a speed benefit.

The saved conversation restored after service restart. Browser DOM inspection
found 20 rendered KaTeX expressions and zero equation errors. KaTeX assets and
fonts are served from localhost with no CDN.

Search checks observed Google's WML endpoint returning access denied. Yahoo
returned relevant MIT OpenCourseWare lectures once but subsequently timed out;
Mwmbl returned relevant eigenvalue/eigenvector educational results. The app
labels fallback engines, rejects clearly unrelated Bing results, and treats
snippets as untrusted observations. Empty searches produce an explicit warning.
Search is optional, not a promise that every provider is available.

Real web-assisted chat `57b4b9fba40542a481b3d3ff6c418a8b` reserved the GTX in
software (without starting a VM or changing PCI drivers), rediscovered RX-only
hardware, and completed with 24 GPU layers and a 16k context. It generated a
query, retrieved four relevant Mwmbl results after Google/Yahoo failures, and
returned a correct one-sentence eigenvector definition with citation [1]. Query
inference took 6.95s and the final answer 8.04s, excluding search/network and
setup. Sampled AMD GPU peak including the desktop was 6.90 GiB. Cgroup memory
peak was only 1.04 GiB on this cached run; this is not the full resident model
footprint because previously cached file pages can be charged elsewhere.
The private service retained its 16 GiB cgroup ceiling throughout. The reservation
was released after the reply, and no models remained loaded.


## Chat controls and activity (8 October 2026)

- 44 automated tests passed, including Auto routing under missing-model and
  RAM constraints, manual model capability/limits, progress history persistence,
  cancellation/failure/restart recovery, and duration boundaries through hours.
  JavaScript syntax and Git whitespace checks passed.
- Actual browser file selection and clipboard PNG paste both displayed the
  attachment **inside** the Chat composer above its textarea. No separate Chat
  attachment panel was visible. No browser errors occurred.
- Auto direct greeting `2d5a6a7dd57d4f30a44b96e4b57824fc` chose the installed
  `qwen3.5:4b` model and completed in 7s. No additional model was downloaded.
- Auto study/search `99ffdb84ed334d489e7f49f6612be7ed` chose `qwen3:14b` and
  completed in 1m 33sec. Google returned access denied; Yahoo reported certificate
  validation failure; the labeled Mwmbl fallback supplied two sources, including
  MIT OpenCourseWare. The answer cited that source. Browser and controller both
  showed partial answer text **before** completion, with Working, Writing your
  answer, a cursor, live elapsed minutes/seconds, and actual activity entries.
  RX VRAM peaked at 5.68 GiB during sampling. This was dual Vulkan mode; GTX VRAM
  was not exposed by the AMD sysfs counter and is not inferred from this value.
- Deliberately oversized manual 4B request
  `a51a9080333a430f99bddf84b8e9a87a` failed in 1s with a context-budget
  explanation and an enabled retry composer. It did not generate an answer.
- Cancellation `caed854755904a669aa0786f8809c17d` ended in 0s, displayed
  **Stopped**, hid the Stop button, and restored Send. Manual Coding 30B disabled
  Deep Thinking and explained that the model answers directly.
- The inference service still has MemoryMax=16 GiB, MemoryHigh=14 GiB, no swap,
  and one loaded model/request. Existing GPU/context profiles remain fixed;
  Auto does not expand VRAM or raise those limits.
- Visual proofs are local: `chat-working-proof.png` and
  `chat-progress-proof.png` under `/home/gerald/.local/share/local-coder`.


## Study files (8 October 2026)

- 53 tests passed, including real isolated PDF/DOCX/XLSX/XLS/PPTX/CSV readers,
  formula preservation without execution, Word tables, long-file retrieval,
  summary coverage across files, context budget refusal, extraction caps, XML
  external-entity and compressed-archive rejection, file/text hash tampering,
  file downloads, Chat follow-ups, and coding reference files through a checked
  sandbox task. JavaScript syntax and Git whitespace checks passed.
- Browser file chooser accepted four files together (PDF, DOCX, XLSX, PPTX).
  All four showed text-ready file cards above the textarea, within the composer.
- Conversation `27e44fd0c6af457f8435f876225317bc` selected Study 14B automatically
  for attached documents and answered in 1m 9sec: “The specified calibration
  voltage is 37.5 volts [F1: Page 2].” This value was in the second PDF page,
  not in the user prompt. Six passages from four files were supplied; no vision
  model was used for document reading.
- Its follow-up, with no attachments uploaded again, used the manually selected
  local 4B model and answered in 7s: “The specified resistance is 12 ohms
  [F3: Sheet Measurements · ending at row 4].” The value was present in the
  DOCX table and spreadsheet cells. Both replies retained expandable passages.
- A PDF with no selectable text was rejected at upload with guidance to attach
  a screenshot, without creating a ready attachment or starting model inference.
  Clipboard PNG paste was rechecked successfully after that failure.
- Readers run on CPU inside a networkless Bubblewrap namespace, 256 MiB virtual
  memory per process, CPU/time/output ceilings. Existing inference GPU/context
  profiles and the private service's 16 GiB RAM maximum remain fixed.
- Local browser proof: `/home/gerald/.local/share/local-coder/attach-files-proof.png`.
  Answer proof: `file-study-answer-proof.png` in the same directory. Test documents
  contain generated, non-personal lecture and measurement data.

## Response actions and context optimization (8 October 2026)

- 62 tests passed, including persisted/cleared ratings, exact-context feedback
  records, legacy message IDs, independent branches, redo of an earlier response
  without later turns or its original answer, attachment preservation, failed
  retries, active-worker guards, bounded context excerpts, code compaction logs,
  and real API downloads. JavaScript syntax, Git whitespace and dependency checks
  passed. No GPU/context/RAM profile was expanded.
- Browser Copy placed the exact final answer on the clipboard. A negative rating
  and correction note survived a reload in test conversation
  `643759ad52e14ef682bc73dc79b83553`. Native Markdown and feedback JSON downloads
  completed; the exported record contained the actual `qwen3.5:4b` model/settings,
  exact input messages and no internal thinking text.
- Real-model redo `7f95f891ee5944238a2a5015b94987de` answered in 7s and incorporated
  the saved note, explicitly giving one volt = one joule per coulomb. The original
  answer/rating remained intact. Branching without inference also passed in UI.
- A separate synthetic long-history fixture (`29e2c1f4b64844b8b940e0ae1172023b`)
  had ten deliberately oversized earlier exchanges plus locally attached neutral
  study notes. CPU optimization retained 11 earlier excerpts, with estimated
  input 1,013 tokens inside the 4B profile's 3,192-token input budget. The complete
  22-message history remained saved; the answer correctly cited 37.5 V from the
  attachment in 11s. A subsequent real redo (`7ea27698e047499489b7cad7ee732e6a`)
  retained the same file and answered 37.5 V with a file citation in 7s.
- The compact activity list kept file-reading and optimization events visible
  after completion. The answer also showed an expandable conversation-memory
  record. Browser proof: `response-optimization-proof.png` in the private data
  directory. Fixtures and feedback notes are explicitly labeled UI verification.
- A dashboard restart during this update interrupted user coding task
  `6211e6421add4ca9b69c4ef7cfffe101`. The controller recovered it as needs-attention
  with its isolated workspace/logs preserved; no automatic continuation or apply
  was performed. Subsequent UI-only edits required no service restart.
