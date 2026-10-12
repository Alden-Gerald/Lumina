# Lumina roadmap

This file tracks durable product priorities only. Completed implementation plans,
per-task checklists, and model scratch memory do not belong in the repository.

## Foundation in place

- Local Chat and Code workspaces with explicit model selection.
- Disposable coding workspaces, hash-checked edits, offline command execution,
  validation, review, backups, and source-conflict detection.
- Structured 7B roadmap execution with bounded recovery and saved progress.
- Optional read-only helper and revision-matched background checks.
- Document and image attachments with bounded local extraction.
- Conversation branching, feedback, history, queues, storage controls, and
  versioned metadata backup/restore.
- Scoped personal memory, attributed knowledge retrieval, and inspectable
  preference records.

## Next

### Portable setup

- Replace workstation-specific defaults with a guided first-run configuration.
- Detect compatible inference backends and recommend profiles from measured RAM,
  VRAM, and context requirements.
- Provide reproducible service installation and upgrade documentation.

### Verification and accessibility

- Add automated browser coverage for the main Chat, Code, Settings, and recovery
  flows.
- Expand keyboard, focus, contrast, narrow-screen, and reduced-motion checks.
- Keep qualification results tied to exact model, hardware, and source revisions.

### Data control

- Improve storage previews and reference-aware cleanup before deletion.
- Make exports easier to inspect while continuing to exclude credentials and raw
  private artifacts by default.
- Extend provenance views for memories, knowledge passages, and web sources.

## Later

- Support additional local inference backends without weakening resource gates.
- Add evaluated, reversible local adapter training only when a supported trainer,
  deterministic data split, capability checks, and rollback path are available.
- Package hardware presets contributed from verified installations.

## Decision rule

A roadmap item is ready to ship only when its behavior is observable, its failure
mode is clear, user data remains recoverable, and meaningful checks cover the
change. Model review alone is not completion evidence.
