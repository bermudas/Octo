"""System prompt composer — reads persona files and memory.

Supports two modes:
- **CLI mode** (default): reads from ``.octo/persona/`` filesystem + daily
  memory + project state.
- **Engine mode**: receives persona files as a ``dict[str, str]`` (loaded
  from S3 storage by ``persona_loader``).  Daily memory and project state
  are not available in this mode.

Both modes share the same assembly logic via ``build_system_prompt()``.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from octo.config import PERSONA_DIR, MEMORY_DIR, STATE_PATH, SYSTEM_PROMPT_BUDGET

# Identity files loaded in priority order.
# TOOLS.md is engine-specific but harmless if present in CLI mode too.
_IDENTITY_FILES = ("SOUL.md", "IDENTITY.md", "USER.md", "AGENTS.md", "TOOLS.md")


def _read_if_exists(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def build_system_prompt(persona_files: dict[str, str] | None = None) -> str:
    """Compose the supervisor system prompt from persona files.

    Args:
        persona_files: Optional dict mapping filename (e.g. ``"SOUL.md"``)
            to content.  When provided, files are read from this dict
            (engine/server mode).  When ``None``, files are read from the
            local ``.octo/persona/`` directory (CLI mode).
    """
    parts: list[str] = []

    # Core identity
    for name in _IDENTITY_FILES:
        if persona_files is not None:
            text = persona_files.get(name, "").strip()
        else:
            text = _read_if_exists(PERSONA_DIR / name)
        if text:
            parts.append(text)

    # Today's memory — only available in CLI mode (local filesystem)
    if persona_files is None:
        today = date.today().isoformat()
        mem = _read_if_exists(MEMORY_DIR / f"{today}.md")
        if mem:
            _MEM_CAP = 3000
            if len(mem) > _MEM_CAP:
                mem = "[... earlier entries omitted ...]\n" + mem[-_MEM_CAP:]
            parts.append(f"# Today's Memory ({today})\n\n{mem}")

    # Long-term memory
    if persona_files is not None:
        ltm = persona_files.get("MEMORY.md", "").strip()
    else:
        ltm = _read_if_exists(PERSONA_DIR / "MEMORY.md")
    if ltm:
        parts.append(f"# Long-Term Memory\n\n{ltm}")

    # Project state — only available in CLI mode (local filesystem)
    if persona_files is None:
        state = _read_if_exists(STATE_PATH)
        if state:
            parts.append(f"# Current Project State\n\n{state}")

    # Enforce budget: truncate lowest-priority sections first.
    # Parts order: [0..N]=identity files, [N+]=memory/state (lower priority)
    _SEP = "\n\n---\n\n"
    total = sum(len(p) for p in parts) + len(_SEP) * max(0, len(parts) - 1)
    if total > SYSTEM_PROMPT_BUDGET:
        overflow = total - SYSTEM_PROMPT_BUDGET
        protected = min(len(_IDENTITY_FILES), len(parts))
        for idx in range(len(parts) - 1, protected - 1, -1):
            if overflow <= 0:
                break
            if len(parts[idx]) > 500:
                cut = min(overflow, len(parts[idx]) - 500)
                parts[idx] = parts[idx][:len(parts[idx]) - cut] + (
                    "\n[... truncated to fit prompt budget ...]"
                )
                overflow -= cut

    return _SEP.join(parts)
