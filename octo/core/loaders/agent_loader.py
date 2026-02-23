"""Load AGENT.md files → AgentConfig dataclasses.

Loads from two sources:
  1. Project agent dirs (AGENT_DIRS) — Claude Code AGENT.md files
  2. Octo-native agents (.octo/agents/*/AGENT.md) — includes deep_research type
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from octo.config import AGENT_DIRS, AGENTS_DIR


@dataclass
class AgentConfig:
    name: str
    description: str
    system_prompt: str
    tools: list[str] = field(default_factory=list)
    model: str = ""  # empty = inherit default
    type: str = ""  # "deep_research" for deepagents, empty for create_agent
    color: str = "cyan"
    source_project: str = ""


def _parse_frontmatter_fallback(raw: str) -> dict[str, str]:
    """Fallback parser for YAML frontmatter with complex multi-line values.

    Claude Code AGENT.md descriptions can contain literal \\n, XML tags, etc.
    that break standard YAML parsing. This extracts top-level key: value pairs.
    """
    meta: dict[str, str] = {}
    current_key = ""
    current_val = ""

    for line in raw.strip().splitlines():
        # Check if this line starts a new key (word followed by colon at start)
        if ":" in line and not line[0].isspace():
            colon_idx = line.index(":")
            candidate_key = line[:colon_idx].strip()
            # Valid YAML keys are simple words
            if candidate_key.isidentifier():
                if current_key:
                    meta[current_key] = current_val.strip()
                current_key = candidate_key
                current_val = line[colon_idx + 1:].strip()
                continue
        # Continuation of previous value
        if current_key:
            current_val += " " + line.strip()

    if current_key:
        meta[current_key] = current_val.strip()

    return meta


def _parse_agent_md_text(text: str, fallback_name: str = "agent") -> AgentConfig | None:
    """Parse AGENT.md text content with YAML frontmatter.

    Pure text parser — no filesystem access. Used by both filesystem and
    storage-based loaders.

    Args:
        text: Full AGENT.md file content.
        fallback_name: Name to use if not specified in frontmatter.
    """
    if not text.startswith("---"):
        return None

    # Split frontmatter from body
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        # Fallback for complex frontmatter (long descriptions with special chars)
        meta = _parse_frontmatter_fallback(parts[1])

    if not meta:
        return None

    name = meta.get("name", fallback_name)
    description = meta.get("description", "")
    # Clean up description — take only first sentence/paragraph for routing
    if len(description) > 200:
        # Cut at first period after 50 chars, or at 200
        cut = description.find(".", 50)
        if cut != -1 and cut < 300:
            description = description[:cut + 1]
        else:
            description = description[:200] + "..."
    body = parts[2].strip()

    # tools can be a list or comma-separated string
    raw_tools = meta.get("tools", [])
    if isinstance(raw_tools, str):
        tools = [t.strip() for t in raw_tools.split(",") if t.strip()]
    else:
        tools = list(raw_tools)

    model = meta.get("model", "")
    if model == "inherit":
        model = ""

    color = meta.get("color", "cyan")
    agent_type = meta.get("type", "")

    return AgentConfig(
        name=name,
        description=description,
        system_prompt=body,
        tools=tools,
        model=model,
        type=agent_type,
        color=color,
    )


def _parse_agent_md(path: Path) -> AgentConfig | None:
    """Parse a single AGENT.md file from filesystem."""
    text = path.read_text(encoding="utf-8")
    cfg = _parse_agent_md_text(text, fallback_name=path.stem)
    if cfg is not None:
        # Derive source project from parent path
        cfg.source_project = path.parent.parent.parent.name  # .claude/agents/x.md → project dir
    return cfg


def load_agents(agent_dirs: list[Path] | None = None) -> list[AgentConfig]:
    """Scan all agent directories and return AgentConfig list.

    Args:
        agent_dirs: Directories to scan for AGENT.md files.
            Defaults to AGENT_DIRS from octo.config (CLI mode).
    """
    if agent_dirs is None:
        agent_dirs = AGENT_DIRS
    agents: list[AgentConfig] = []
    seen_names: set[str] = set()

    for agent_dir in agent_dirs:
        if not agent_dir.is_dir():
            continue
        for md_file in sorted(agent_dir.glob("*.md")):
            cfg = _parse_agent_md(md_file)
            if cfg and cfg.name not in seen_names:
                agents.append(cfg)
                seen_names.add(cfg.name)

    return agents


def load_octo_agents(agents_dir: Path | None = None) -> list[AgentConfig]:
    """Scan .octo/agents/*/AGENT.md and return AgentConfig list.

    These are Octo-native agents (e.g. deep_research type) configured
    directly in the workspace, not loaded from external projects.

    Args:
        agents_dir: Directory containing agent subdirectories.
            Defaults to AGENTS_DIR from octo.config (CLI mode).
    """
    if agents_dir is None:
        agents_dir = AGENTS_DIR
    agents: list[AgentConfig] = []

    if not agents_dir.is_dir():
        return agents

    for agent_dir in sorted(agents_dir.iterdir()):
        agent_file = agent_dir / "AGENT.md"
        if not agent_file.is_file():
            continue
        cfg = _parse_agent_md(agent_file)
        if cfg:
            cfg.source_project = "octo"
            agents.append(cfg)

    return agents


# ---------------------------------------------------------------------------
# Async storage-based loading (for OctoEngine / S3 / Artifacts)
# ---------------------------------------------------------------------------

import logging

_log = logging.getLogger(__name__)


async def load_agents_from_storage(storage: Any, prefix: str = "agents") -> list[AgentConfig]:
    """Load AGENT.md files from a StorageBackend (S3, filesystem, etc.).

    Expects layout:
        {prefix}/
            qa-engineer/AGENT.md
            test-architect/AGENT.md

    Each subdirectory under {prefix}/ should contain an AGENT.md file.

    Args:
        storage: A StorageBackend instance (S3Storage, FilesystemStorage, etc.).
        prefix: Storage path prefix for agent directories. Default "agents".

    Returns:
        List of AgentConfig objects parsed from storage.
    """
    agents: list[AgentConfig] = []
    seen_names: set[str] = set()

    try:
        entries = await storage.list_dir(prefix)
    except (FileNotFoundError, Exception) as e:
        _log.debug("No agents found at '%s': %s", prefix, e)
        return agents

    for entry in sorted(entries):
        # entry might be "qa-engineer/" or "qa-engineer"
        dir_name = entry.rstrip("/")
        if not dir_name:
            continue

        agent_path = f"{prefix}/{dir_name}/AGENT.md"
        try:
            text = await storage.read(agent_path)
        except FileNotFoundError:
            continue

        cfg = _parse_agent_md_text(text, fallback_name=dir_name)
        if cfg and cfg.name not in seen_names:
            cfg.source_project = "storage"
            seen_names.add(cfg.name)
            agents.append(cfg)

    if agents:
        _log.info("Loaded %d agent(s) from storage prefix '%s'", len(agents), prefix)

    return agents
