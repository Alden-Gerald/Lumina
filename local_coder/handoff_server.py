"""MCP tools that let Codex hand a complete task to the local coding agent."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from mcp.server import MCPServer
from pydantic import Field

from .handoff import HandoffClient


def serve(source: Path, http: bool = False, port: int = 8002):
    source = Path(source).resolve(strict=True)
    if not source.is_dir():
        raise ValueError("Handoff source must be a project directory")
    client = HandoffClient()
    mcp = MCPServer(
        "Local AI handoff",
        version="0.1.0",
        instructions=(
            "Delegate complete coding tasks to the local AI with handoff_to_local_ai. Include every attached "
            "Codex image path in attachment_paths and use the quality profile unless the user explicitly chooses another. "
            "Set source_path to the absolute root of the project the user wants changed; do not assume it is the Codex "
            "workspace. Quickshell and Orbit desktop tasks use /home/gerald/dotfiles/quickshell. After a successful "
            "handoff, stop implementing and end the Codex turn; do not poll automatically. The local agent works "
            "asynchronously in a disposable workspace, runs checks and review, then safely applies Codex-originated "
            "results when auto_apply is enabled. Use get_handoff_status only when the user asks for progress. Read the diff "
            "only for explicit review or recovery, keeping local output out of Codex context by default."
        ),
    )

    @mcp.tool()
    def handoff_to_local_ai(
        task: Annotated[str, Field(min_length=5, max_length=5000)],
        acceptance: Annotated[str, Field(max_length=2000)] = "",
        profile: Literal["quality", "balanced", "power"] = "quality",
        test_commands: Annotated[list[list[str]] | None, Field(max_length=4)] = None,
        parallel_assistants: bool = True,
        attachment_paths: Annotated[list[str] | None, Field(max_length=2)] = None,
        source_path: Annotated[str | None, Field(max_length=1000)] = None,
        auto_apply: bool = True,
    ) -> dict:
        """Hand a coding change to local AI. Set the real target project root, forward images, start asynchronously, then end the Codex turn."""
        target = Path(source_path).resolve(strict=True) if source_path else source
        if not target.is_dir():
            raise ValueError("Handoff source must be a project directory")
        return client.start(task, target, profile, acceptance, test_commands, parallel_assistants,
                            attachment_paths, auto_apply)

    @mcp.tool()
    def get_handoff_status(run_id: str) -> dict:
        """Return a compact local-task status. Call only when the user asks for progress or after an external completion signal."""
        return client.status(run_id)

    @mcp.tool()
    def get_handoff_diff(
        run_id: str,
        max_characters: Annotated[int, Field(ge=1000, le=20000)] = 12000,
    ) -> dict:
        """Read a bounded diff for explicit Codex review or recovery; routine completed tasks should remain in the local dashboard."""
        return client.diff(run_id, max_characters)

    @mcp.tool()
    def cancel_handoff(run_id: str) -> dict:
        """Request cancellation of a running local-AI task."""
        return client.cancel(run_id)

    if http:
        mcp.run(transport="streamable-http", host="127.0.0.1", port=port)
    else:
        mcp.run()
