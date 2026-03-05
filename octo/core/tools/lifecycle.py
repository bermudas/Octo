"""Agent lifecycle tools — task_complete, escalate_question.

Lightweight versions for regular worker agents (non-background).
These guide the LLM to produce structured output but don't manage
any external state.  Background agents use their own closure-based
versions in background.py that interact with TaskStore.
"""
from __future__ import annotations

from langchain_core.tools import tool


@tool
def task_complete(summary: str) -> str:
    """Signal that your assigned task is fully complete.

    Call this when you have finished all work.  Your summary will be
    relayed to the supervisor and then to the user.

    Args:
        summary: concise description of what was accomplished and any
            key results or findings.
    """
    return summary


@tool
def escalate_question(question: str) -> str:
    """Ask the user a clarifying question when you are blocked.

    Call this when you need information or a decision from the user
    before you can proceed.  Your question will be relayed through
    the supervisor.

    Args:
        question: the specific question you need answered.
    """
    return (
        f"[ESCALATION] The following question needs to be relayed to the user:\n\n"
        f"{question}\n\n"
        f"Please include this question in your response to the user."
    )


# ── Restart signalling ────────────────────────────────────────────────
_restart_requested = False


def is_restart_requested() -> bool:
    return _restart_requested


def clear_restart_flag() -> None:
    global _restart_requested
    _restart_requested = False


@tool
def request_restart(reason: str) -> str:
    """Request Octo to restart itself so code changes take effect.

    Call this AFTER you have finished editing Octo's own source files and
    need the running process to reload with the new code.  The restart
    happens gracefully after the current turn completes — the session is
    preserved and resumed automatically.

    Args:
        reason: brief explanation of why a restart is needed (e.g.
            "applied bugfix to octo/graph.py").
    """
    global _restart_requested
    _restart_requested = True
    return f"Restart scheduled. Reason: {reason}. It will happen after this response."


AGENT_LIFECYCLE_TOOLS = [task_complete, escalate_question, request_restart]
