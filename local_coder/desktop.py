"""Bounded live-desktop follow-up for an applied Orbit Quickshell task."""
from __future__ import annotations

from pathlib import Path
import subprocess

from .settings import DEFAULT_PROJECT


OPENCLAW = Path("/home/gerald/.openclaw/bin/openclaw")
RESTART_ORBIT = DEFAULT_PROJECT / "orbit-shell/scripts/restart-orbit"


def finish_quickshell(run_id: str, task: str) -> dict:
    """Reload Orbit deterministically, then ask OpenClaw for read-only visual inspection."""
    if not RESTART_ORBIT.is_file():
        raise ValueError("Orbit reload helper is unavailable")
    reload_result = subprocess.run(
        [str(RESTART_ORBIT)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=30, check=False,
    )
    if reload_result.returncode:
        detail = (reload_result.stderr or reload_result.stdout).strip()[-1000:]
        raise ValueError("Orbit Shell reload failed" + (": " + detail if detail else ""))

    verification = {"status": "unavailable", "summary": "OpenClaw is not installed"}
    if OPENCLAW.is_file():
        prompt = (
            "A verified code change was applied and Orbit Shell was reloaded. Use only the "
            "wayland_screenshot tool to inspect the live desktop. Do not click, type, run shell "
            "commands, or edit files. Briefly report whether Orbit Shell is visible and whether "
            "the requested UI appears present. Requested change: " + task[:1200]
        )
        inspected = subprocess.run(
            [str(OPENCLAW), "agent", "--session-key", f"agent:main:local-coder-{run_id}",
             "--message", prompt, "--json", "--timeout", "120"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=150, check=False,
        )
        output = (inspected.stdout or inspected.stderr).strip()[-4000:]
        verification = {
            "status": "inspected" if inspected.returncode == 0 else "failed",
            "summary": output,
        }
    return {"reloaded": True, "openclaw": verification}
