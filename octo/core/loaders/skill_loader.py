"""Load SKILL.md files → SkillConfig dataclasses."""
from __future__ import annotations

import importlib.util
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from octo.config import EXTERNAL_SKILLS_DIRS, SKILLS_DIR

log = logging.getLogger(__name__)

# pip package name → Python import name (only for names that differ)
_PIP_TO_IMPORT: dict[str, str] = {
    "pillow": "PIL",
    "python-docx": "docx",
    "python-pptx": "pptx",
    "pyyaml": "yaml",
    "scikit-learn": "sklearn",
    "beautifulsoup4": "bs4",
    "pdf2image": "pdf2image",
}


@dataclass
class SkillConfig:
    name: str
    description: str
    body: str  # full markdown content for injection into conversation
    model_invocation: bool = True  # False = user-only (/slash command), not offered to LLM
    # --- agentskills.io standard fields ---
    version: str = "0.0.0"
    author: str = ""
    tags: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)  # pre-approved tool names
    compatibility: str = ""  # environment requirements (agentskills.io)
    # --- extended fields ---
    dependencies: dict = field(default_factory=dict)
    requires: list[dict] = field(default_factory=list)
    permissions: dict = field(default_factory=dict)
    source: str = "local"  # "local" | "marketplace" | "storage"
    # --- progressive disclosure ---
    skill_dir: Path | None = None  # absolute path to skill directory (filesystem mode)
    storage_prefix: str = ""  # storage path prefix, e.g. "skills/test-generation" (storage mode)
    references: list[str] = field(default_factory=list)  # relative paths of files in references/
    reference_contents: dict[str, str] = field(default_factory=dict)  # {relative_path: content} pre-loaded
    scripts: list[str] = field(default_factory=list)  # relative paths of files in scripts/


def _catalog_subdir(skill_dir: Path, subdir_name: str) -> list[str]:
    """List files in a skill subdirectory (references/, scripts/), relative to skill_dir."""
    subdir = skill_dir / subdir_name
    if not subdir.is_dir():
        return []
    return sorted(
        str(f.relative_to(skill_dir))
        for f in subdir.rglob("*")
        if f.is_file()
    )


def _parse_skill_md_text(text: str, fallback_name: str = "skill") -> SkillConfig | None:
    """Parse SKILL.md text content with YAML frontmatter.

    Pure text parser — no filesystem access. Used by both filesystem and
    storage-based loaders.

    Args:
        text: Full SKILL.md file content.
        fallback_name: Name to use if not specified in frontmatter.
    """
    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None

    name = meta.get("name", fallback_name)
    description = meta.get("description", "")
    body = parts[2].strip()

    # model-invocation: true (default) / false (user-only slash command)
    model_invocation = meta.get("model-invocation", True)
    if isinstance(model_invocation, str):
        model_invocation = model_invocation.lower() not in ("false", "no", "0")

    # allowed-tools: space-delimited string or YAML list
    raw_tools = meta.get("allowed-tools", [])
    if isinstance(raw_tools, str):
        allowed_tools = raw_tools.split()
    else:
        allowed_tools = list(raw_tools) if raw_tools else []

    return SkillConfig(
        name=name,
        description=description,
        body=body,
        model_invocation=model_invocation,
        version=str(meta.get("version", "0.0.0")),
        author=meta.get("author", ""),
        tags=meta.get("tags", []),
        allowed_tools=allowed_tools,
        compatibility=meta.get("compatibility", ""),
        dependencies=meta.get("dependencies", {}),
        requires=meta.get("requires", []),
        permissions=meta.get("permissions", {}),
    )


def _parse_skill_md(path: Path) -> SkillConfig | None:
    """Parse a single SKILL.md file from filesystem."""
    text = path.read_text(encoding="utf-8")
    cfg = _parse_skill_md_text(text, fallback_name=path.parent.name)
    if cfg is not None:
        skill_dir = path.parent.resolve()
        cfg.skill_dir = skill_dir
        cfg.references = _catalog_subdir(skill_dir, "references")
        cfg.scripts = _catalog_subdir(skill_dir, "scripts")
        # Pre-load reference contents (max 8KB each, max 32KB total)
        total_loaded = 0
        for ref_path in cfg.references:
            if total_loaded >= 32_000:
                break
            full_path = skill_dir / ref_path
            try:
                content = full_path.read_text(encoding="utf-8")
                if len(content) <= 8_000:
                    cfg.reference_contents[ref_path] = content
                    total_loaded += len(content)
            except Exception:
                pass
    return cfg


def _scan_skills_dir(
    directory: Path, seen: set[str], source: str = "local",
) -> list[SkillConfig]:
    """Scan a single skills directory, skipping names already in *seen*."""
    results: list[SkillConfig] = []
    if not directory.is_dir():
        return results
    for skill_dir in sorted(directory.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        cfg = _parse_skill_md(skill_file)
        if cfg and cfg.name not in seen:
            cfg.source = source
            seen.add(cfg.name)
            results.append(cfg)
    return results


def load_skills(
    skills_dir: Path | None = None,
    external_dirs: list[Path] | None = None,
) -> list[SkillConfig]:
    """Scan skills directory and external skill dirs (skills.sh ecosystem).

    Priority: skills_dir wins over external dirs. Within external dirs,
    first-found wins (so .agents/skills/ beats .claude/skills/).

    Args:
        skills_dir: Primary skills directory. Defaults to SKILLS_DIR from
            octo.config (CLI mode).
        external_dirs: Additional skill directories to scan. Defaults to
            EXTERNAL_SKILLS_DIRS from octo.config (CLI mode).
    """
    if skills_dir is None:
        skills_dir = SKILLS_DIR
    if external_dirs is None:
        external_dirs = EXTERNAL_SKILLS_DIRS
    seen: set[str] = set()

    # Primary: Octo-native skills
    skills = _scan_skills_dir(skills_dir, seen)

    # External: skills.sh / Agent Skills ecosystem directories
    for ext_dir in external_dirs:
        found = _scan_skills_dir(ext_dir, seen, source="skills.sh")
        if found:
            log.info("Loaded %d skill(s) from %s", len(found), ext_dir)
        skills.extend(found)

    return skills


# ---------------------------------------------------------------------------
# Dependency checking
# ---------------------------------------------------------------------------

def _pip_name(spec: str) -> str:
    """Extract bare package name from a pip specifier like 'pdfplumber>=0.11'."""
    return re.split(r"[><=!~\[]", spec, maxsplit=1)[0].strip().lower()


def _import_name(pip_pkg: str) -> str:
    """Map a pip package name to its Python import name."""
    key = pip_pkg.lower()
    if key in _PIP_TO_IMPORT:
        return _PIP_TO_IMPORT[key]
    # Default: replace dashes with underscores
    return key.replace("-", "_")


def check_missing_deps(skill: SkillConfig) -> list[str]:
    """Return list of pip specifiers whose packages are not importable."""
    python_deps: list[str] = skill.dependencies.get("python", [])
    if not python_deps:
        return []

    missing: list[str] = []
    for spec in python_deps:
        pkg = _pip_name(spec)
        mod = _import_name(pkg)
        if importlib.util.find_spec(mod) is None:
            missing.append(spec)
    return missing


def verify_skills_deps(skills: list[SkillConfig]) -> dict[str, list[str]]:
    """Check all skills for missing Python deps. Returns {skill_name: [missing_specs]}.

    Also logs warnings for any skills with missing dependencies.
    """
    problems: dict[str, list[str]] = {}
    for sk in skills:
        missing = check_missing_deps(sk)
        if missing:
            problems[sk.name] = missing
            log.warning(
                "Skill '%s' has missing Python deps: %s  "
                "(run: pip install %s)",
                sk.name,
                ", ".join(missing),
                " ".join(_pip_name(s) for s in missing),
            )
    return problems


# ---------------------------------------------------------------------------
# Async storage-based loading (for OctoEngine / S3 / Artifacts)
# ---------------------------------------------------------------------------

async def _catalog_storage_subdir(storage: Any, skill_prefix: str, subdir: str) -> list[str]:
    """List files in a skill's subdirectory within storage (references/, scripts/).

    Returns relative paths like "references/api-guide.md".
    """
    full_prefix = f"{skill_prefix}/{subdir}"
    try:
        entries = await storage.list_dir(full_prefix)
    except (FileNotFoundError, Exception):
        return []
    # entries are filenames within the subdir
    return sorted(f"{subdir}/{e.rstrip('/')}" for e in entries if e.rstrip("/"))


async def load_skills_from_storage(storage: Any, prefix: str = "skills") -> list[SkillConfig]:
    """Load SKILL.md files from a StorageBackend (S3, filesystem, etc.).

    Expects layout:
        {prefix}/
            test-generation/
                SKILL.md
                references/       # optional — extra context docs
                    api-guide.md
                    examples.md

    Each subdirectory under {prefix}/ should contain a SKILL.md file.
    Optional references/ subdirectories are scanned and their paths stored
    in SkillConfig.references for progressive disclosure.

    Args:
        storage: A StorageBackend instance (S3Storage, FilesystemStorage, etc.).
        prefix: Storage path prefix for skill directories. Default "skills".

    Returns:
        List of SkillConfig objects parsed from storage.
    """
    skills: list[SkillConfig] = []
    seen_names: set[str] = set()

    try:
        entries = await storage.list_dir(prefix)
    except (FileNotFoundError, Exception) as e:
        log.debug("No skills found at '%s': %s", prefix, e)
        return skills

    for entry in sorted(entries):
        # entry might be "test-generation/" or "test-generation"
        dir_name = entry.rstrip("/")
        if not dir_name:
            continue

        skill_path = f"{prefix}/{dir_name}/SKILL.md"
        try:
            text = await storage.read(skill_path)
        except FileNotFoundError:
            continue

        cfg = _parse_skill_md_text(text, fallback_name=dir_name)
        if cfg and cfg.name not in seen_names:
            cfg.source = "storage"
            cfg.storage_prefix = f"{prefix}/{dir_name}"
            # Scan references/ subdirectory and pre-load contents
            cfg.references = await _catalog_storage_subdir(
                storage, f"{prefix}/{dir_name}", "references",
            )
            # Pre-load reference contents (max 8KB each, max 32KB total)
            if cfg.references:
                total_loaded = 0
                for ref_path in cfg.references:
                    if total_loaded >= 32_000:
                        break
                    full_path = f"{prefix}/{dir_name}/{ref_path}"
                    try:
                        content = await storage.read(full_path)
                        if len(content) <= 8_000:
                            cfg.reference_contents[ref_path] = content
                            total_loaded += len(content)
                        else:
                            log.debug(
                                "Skipping large reference %s (%d bytes)",
                                full_path, len(content),
                            )
                    except Exception:
                        pass
            seen_names.add(cfg.name)
            skills.append(cfg)

    if skills:
        loaded_refs = sum(len(s.reference_contents) for s in skills)
        log.info(
            "Loaded %d skill(s) from storage prefix '%s' (%d reference(s) pre-loaded)",
            len(skills), prefix, loaded_refs,
        )

    return skills
