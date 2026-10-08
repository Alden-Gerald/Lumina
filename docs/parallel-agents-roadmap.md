# Parallel local coding roadmap

1. **Separate inference workers.** Pin the 14B Q4_K_M builder to RX 6600,
   with CPU offload and an 8192-token context. Pin a single 2B Q4_K_M helper
   to GTX 1050 Ti with a 4096-token context. Both services belong to one
   systemd slice limited to 16 GiB RAM, with no swap. RAM is CPU offload
   memory; it does not turn into additional physical VRAM.
2. **Bounded read-only helpers.** Scout, test suggestions and diff review
   share one helper queue. They receive bounded source excerpts, have no
   tools or write access, and return advisory JSON. Only the builder edits.
   At most four helper requests per task; no recursive agent spawning.
3. **Concurrent real checks.** After each completed patch, copy an immutable
   source revision and run syntax checks plus supplied behavior tests in
   its read-only sandbox. Cancel obsolete checks; accept results only when
   the full source manifest matches. Final builder review and exact-revision
   checks gate the existing local task commit and explicit Apply action.
4. **Visible operation and fallback.** Show builder, helper and check lanes
   in the dashboard. GTX reservation stops the helper without restarting
   the RX builder. No CPU fallback helper while the builder is offloaded.
5. **Verification and rollout.** Test stale-result rejection, cancellation,
   helper isolation and VM reservation. Measure both live models and shared
   memory. Run a disposable feature task with independent behavior tests.
   Preserve live Quickshell files and running chats/tasks during deployment.

Success requires a working feature and real test evidence. A smaller model's
opinion is never a substitute for executable behavior tests. Parallel workers
may improve elapsed time but still share CPU, RAM and memory bandwidth.

## Implemented and qualified

All five stages are implemented. See [verification](verification.md) for the
real feature task, hardware measurements and limitations. The dashboard now
defaults to the 14B builder with optional parallel helpers. Quick chat and the
image reader also use all 33 RX layers, which fit the measured 8GB envelope.

The helper service starts on demand. To reinstall this machine's checked-in
worker units while Chat and Code are idle, run:

```bash
cd /home/gerald/local-coder
.venv/bin/python scripts/install-parallel-workers.py
```

Use `--no-team` on the CLI or clear **Parallel assistants** to disable the
advisory GPU worker. CPU revision checks still run. After returning the GTX
from VFIO to nouveau/NVK, run `local-coder vm-release`; the next task discovers
it. The app never changes PCI bindings automatically.
