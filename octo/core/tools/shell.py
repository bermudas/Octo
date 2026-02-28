"""Shell tool — command execution (cross-platform).

Named to match Claude Code's Bash tool.
On Windows, prefers Git Bash for Unix-like compatibility.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys

from langchain_core.tools import tool

_IS_WINDOWS = sys.platform == "win32"


def _find_git_bash() -> str | None:
    """Find Git Bash executable on Windows."""
    # Check common locations
    for candidate in [
        shutil.which("bash"),  # on PATH (e.g. Git Bash added to PATH)
        os.path.expandvars(r"%ProgramFiles%\Git\bin\bash.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Git\bin\bash.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe"),
        r"C:\Program Files\Git\bin\bash.exe",
    ]:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


# Resolve once at import time
_GIT_BASH: str | None = _find_git_bash() if _IS_WINDOWS else None


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill a process and all its children (cross-platform)."""
    if _IS_WINDOWS:
        # On Windows, shell=True spawns cmd.exe which spawns the real process.
        # proc.kill() only kills cmd.exe, leaving the child alive.
        # Use taskkill /T to kill the entire process tree.
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            proc.kill()
    else:
        proc.kill()


@tool
async def Bash(command: str, timeout: int = 120) -> str:
    """Execute a shell command and return its output.

    Args:
        command: The shell command to execute.
        timeout: Maximum execution time in seconds (default 120).

    Returns:
        Combined stdout and stderr output, or error message.
    """
    try:
        # Run subprocess in a thread to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _run_subprocess, command, timeout),
            timeout=timeout + 5,  # small grace period over subprocess timeout
        )
        return result
    except asyncio.TimeoutError:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error executing command: {e}"


def _run_subprocess(command: str, timeout: int) -> str:
    """Run a subprocess with proper timeout handling (runs in thread)."""
    if _IS_WINDOWS and _GIT_BASH:
        # Use Git Bash for Unix-like compatibility (grep, sed, pipes, etc.)
        args = [_GIT_BASH, "-c", command]
        kwargs: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
        }
    elif _IS_WINDOWS:
        # Fallback to cmd.exe if Git Bash not found
        args = command
        kwargs = {
            "shell": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
        }
    else:
        # Unix — use shell directly
        args = command
        kwargs = {
            "shell": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }

    proc = subprocess.Popen(args, **kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        # After killing, drain remaining output
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except Exception:
            stdout, stderr = "", ""
        return f"Error: Command timed out after {timeout}s"

    output_parts = []
    if stdout:
        output_parts.append(stdout)
    if stderr:
        output_parts.append(f"[stderr]\n{stderr}")
    if proc.returncode != 0:
        output_parts.append(f"[exit code: {proc.returncode}]")
    output = "\n".join(output_parts) if output_parts else "(no output)"
    # Truncate very large outputs
    if len(output) > 50000:
        output = output[:50000] + "\n... (truncated)"
    return output


bash_tool = Bash
