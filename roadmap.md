# Local 7B Roadmap Executor

## Goal

Replace long, monolithic 14B coding runs with a fully local 7B workflow that:

1. Creates a persistent `roadmap.md` for every coding task.
2. Breaks the request into small, ordered checklist items.
3. Gives the model only the current checklist item and relevant context.
4. Tests every completed item before moving to the next one.
5. Stops with useful failure evidence instead of continuing after a failed check.
6. Resumes safely after a service restart.
7. Never calls Codex, a handoff service, or another cloud model.

## Execution rules

- Complete the phases below in order.
- Work on only one unchecked item at a time.
- Do not start the next phase until the current phase's gate passes.
- Keep each patch small: normally one behavior and one or two production files.
- Preserve existing source-conflict, file-count, changed-line, timeout, and cancellation limits.
- Deterministic code—not the model—owns checklist state, validation, retry limits, and advancement.
- Runtime roadmaps live in the run workspace/metadata, never in the user's final project patch.

---

## Phase 0 — Protect the existing behavior

- [ ] Record the current full test result as the baseline.
- [ ] Add a feature flag named `roadmap_execution`; default it to off.
- [ ] Confirm existing 14B, 9B, and 30B task modes behave unchanged with the flag off.
- [ ] Add a test proving a normal task does not create or apply a runtime roadmap file.

### Gate 0

- [ ] Existing test suite passes.
- [ ] New compatibility test passes.
- [ ] No target-project files change during the test.

---

## Phase 1 — Add the 7B model profile

- [ ] Add a configurable 7B coding profile with an Ollama model tag supplied through settings.
- [ ] Use a conservative default such as `qwen2.5-coder:7b-instruct-q4_K_M`, but do not download it automatically.
- [ ] Detect whether the configured model is installed.
- [ ] Show `not installed` in Lumina when it is absent.
- [ ] Keep the existing profiles selectable.
- [ ] Set an explicit context and output-token budget suitable for the chosen 7B model.

### Gate 1

- [ ] Profile-selection unit test passes.
- [ ] Missing-model test passes without starting a download.
- [ ] Existing profile tests still pass.
- [ ] A local `/api/tags` response is enough to determine availability.

---

## Phase 2 — Define the runtime roadmap format

- [ ] Define a versioned roadmap data structure in run state.
- [ ] Include the original task, acceptance criteria, creation time, revision, current item, and overall status.
- [ ] Give every checklist item a stable ID, title, bounded objective, relevant paths, checks, retry count, and status.
- [ ] Allow only these item states: `pending`, `working`, `validating`, `passed`, `failed`, and `blocked`.
- [ ] Render the structured state to a human-readable `roadmap.md`.
- [ ] Write both structured state and Markdown atomically.
- [ ] Store them below the run directory, outside the target repository snapshot and final diff.

### Gate 2

- [ ] Round-trip serialization test passes.
- [ ] Atomic-write interruption test preserves the previous valid roadmap.
- [ ] Invalid state-transition tests are rejected.
- [ ] Apply/diff tests prove `roadmap.md` cannot enter the user's project patch.

---

## Phase 3 — Build the small-task planner

- [ ] Add a planner schema that returns structured checklist items, not free-form prose.
- [ ] Give the planner only the task, acceptance criteria, bounded repository summary, available tools, and required checks.
- [ ] Require between 2 and 12 ordered items.
- [ ] Require every item to describe one observable outcome.
- [ ] Require every item to name its validation method.
- [ ] Reject vague items such as “finish implementation,” “fix everything,” or “verify it works.”
- [ ] Reject items that exceed existing file or changed-line limits.
- [ ] Convert the accepted plan into the persisted runtime `roadmap.md`.
- [ ] If planning fails twice, stop with `needs_attention` and preserve both validation errors.

### Gate 3

- [ ] Planner-schema tests reject missing checks, duplicate IDs, and invalid ordering.
- [ ] Oversized-plan test is rejected.
- [ ] A representative feature request produces small, independently testable items.
- [ ] Planner failure produces a clear result log without modifying source files.

---

## Phase 4 — Execute exactly one checklist item

- [ ] Add a deterministic selector that returns only the first actionable item.
- [ ] Build the model prompt from the original goal, acceptance criteria, compact roadmap summary, current item, relevant file excerpts, current diff, and latest validation.
- [ ] Do not include future-item implementation instructions in the action prompt.
- [ ] Mark the selected item `working` before the first action.
- [ ] Keep the existing precise file-hash and patch safeguards.
- [ ] Limit each item to a bounded number of actions and elapsed time.
- [ ] Prevent a second item from entering `working` concurrently.

### Gate 4

- [ ] Unit test proves only one item can be selected.
- [ ] Prompt-capture test proves later-item details are excluded.
- [ ] Tool tests still reject guessed paths, stale hashes, and out-of-scope edits.
- [ ] Cancellation preserves the active item and roadmap state.

---

## Phase 5 — Add the per-item validation gate

- [ ] Change item state from `working` to `validating` after its patch is complete.
- [ ] Run syntax/static checks relevant to the changed file types.
- [ ] Run the item's declared behavioral check.
- [ ] Run user-supplied required checks when they are relevant to the item.
- [ ] Record command, exit status, bounded output summary, and resulting revision in the roadmap.
- [ ] Mark the item `passed` only when every required check succeeds.
- [ ] Select the next item only after the previous item is `passed`.
- [ ] Never weaken or delete a failing check to make an item pass.

### Gate 5

- [ ] Passing-validation integration test advances to the next item.
- [ ] Failing-validation integration test keeps the same item active.
- [ ] Test proves later items cannot run after a failure.
- [ ] Validation evidence appears in both run state and `roadmap.md`.

---

## Phase 6 — Recover locally from a failed item

- [ ] Classify failures into stable categories: bad path, stale hash, ambiguous patch, command failure, review failure, no progress, repeated action, scope limit, and environment failure.
- [ ] Build a small recovery prompt from the current item, last action, failure category, bounded observation, and current diff.
- [ ] Permit at most two recovery attempts per item.
- [ ] Stop immediately on repeated failure signatures or identical actions without progress.
- [ ] Keep the failed item unchecked and record the recovery attempts.
- [ ] End in `needs_attention` with a concrete “why it stopped” result when recovery is exhausted.
- [ ] Do not call Codex, handoff, web search, or any cloud supervisor.

### Gate 6

- [ ] Recoverable stale-hash test succeeds locally.
- [ ] Repeated-action test stops within the configured bound.
- [ ] Unrecoverable failure test preserves the patch, roadmap, and diagnostics.
- [ ] Network-denial test proves the executor does not require cloud access.

---

## Phase 7 — Keep the 7B context small

- [ ] Add a separate token budget for task, roadmap, source excerpts, diff, observations, and output.
- [ ] Include only files relevant to the current checklist item.
- [ ] Replace old action/observation pairs with compact factual summaries.
- [ ] Always retain the original goal, acceptance criteria, current item, latest file hashes, current diff, and latest failed check.
- [ ] Drop completed-item tool logs after their validation result is recorded.
- [ ] Refuse a model call when mandatory context cannot fit; stop with a precise context-budget explanation.

### Gate 7

- [ ] Token-budget unit tests cover every reserved section.
- [ ] Long-run test stays below the configured 7B context limit.
- [ ] Compaction test retains all mandatory facts.
- [ ] Completed-item logs do not re-enter later prompts.

---

## Phase 8 — Resume after interruption

- [ ] Persist the roadmap before and after every state transition.
- [ ] On startup, discover incomplete roadmap-driven runs.
- [ ] Reconcile roadmap state with the current workspace diff and file hashes.
- [ ] Resume a `pending` item normally.
- [ ] Revalidate an item left in `validating` before advancing.
- [ ] Convert an interrupted `working` item into a recovery attempt rather than blindly repeating its last action.
- [ ] Refuse resume when source or workspace state conflicts with the saved revision.

### Gate 8

- [ ] Restart test resumes from the correct item.
- [ ] Restart-during-validation test reruns checks and does not duplicate edits.
- [ ] Source-conflict test stops safely.
- [ ] Completed items are never executed twice.

---

## Phase 9 — Show roadmap progress in Lumina

- [ ] Add a roadmap panel to the task workspace.
- [ ] Show completed count, total count, current item, and current validation state.
- [ ] Display checklist items in order with clear passed, active, pending, failed, and blocked states.
- [ ] Show validation evidence inline without a disclosure dropdown.
- [ ] Update progress through existing polling without reanimating unchanged content.
- [ ] Add a download/view action for the runtime `roadmap.md`.
- [ ] Keep controls readable on narrow screens and keyboard accessible.

### Gate 9

- [ ] Browser syntax check passes.
- [ ] UI test covers active, passed, failed, and resumed roadmap states.
- [ ] Polling test proves unchanged roadmap elements remain stable.
- [ ] Accessibility test confirms labels, live status, and keyboard navigation.

---

## Phase 10 — End-to-end local workflow

- [ ] Run a small two-item fixture task with the 7B profile.
- [ ] Confirm item 1 edits, validates, and passes before item 2 begins.
- [ ] Confirm item 2 edits and validates.
- [ ] Run the final full-task checks and existing model review gate.
- [ ] Confirm the final diff contains only requested project changes.
- [ ] Confirm runtime `roadmap.md` remains in run storage.
- [ ] Confirm no Codex/handoff/cloud endpoint was contacted.
- [ ] Apply the result through the existing source-conflict and backup safeguards.

### Gate 10

- [ ] End-to-end success fixture passes.
- [ ] End-to-end mid-roadmap failure fixture stops safely.
- [ ] End-to-end restart fixture resumes and finishes.
- [ ] Full project test suite passes.

---

## Phase 11 — Controlled rollout

- [ ] Keep roadmap mode opt-in for the first 20 real tasks.
- [ ] Record item count, retries, validation failures, context use, elapsed time, and final status locally.
- [ ] Compare 7B roadmap runs with existing 14B runs on the same class of bounded tasks.
- [ ] Review every `needs_attention` roadmap and add a deterministic fix where possible.
- [ ] Make the 7B roadmap profile the default only after it completes at least 80% of the trial tasks without manual repair.
- [ ] Preserve a one-click choice of the larger profiles for tasks that exceed roadmap-mode limits.

### Gate 11

- [ ] Trial report is generated from local run data.
- [ ] No secrets, raw private reasoning, or unrelated source content appears in metrics.
- [ ] Default-profile decision is based on measured success, not model size alone.

## Definition of done

- [ ] A user can select the local 7B roadmap profile and submit one prompt.
- [ ] Lumina creates and displays a persistent task-specific `roadmap.md`.
- [ ] The executor completes and validates one small item at a time.
- [ ] Failed checks prevent advancement.
- [ ] Interrupted runs resume without duplicating completed work.
- [ ] Final application retains all existing safety gates.
- [ ] The entire planning, coding, checking, recovery, and resume loop runs locally without Codex.
