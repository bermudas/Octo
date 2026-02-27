"""Load persona files from StorageBackend (S3, filesystem, etc.).

Persona files define the supervisor's identity, user context, memory,
and tool usage guidelines.  In CLI mode these are read from the local
``.octo/persona/`` directory; in engine mode (OctoEngine) they are loaded
from the configured StorageBackend (typically S3 via Artifacts).

Usage::

    from octo.core.loaders.persona_loader import load_persona_from_storage

    files = await load_persona_from_storage(storage, prefix="persona")
    # {"SOUL.md": "...", "IDENTITY.md": "...", "TOOLS.md": "...", ...}
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)


async def load_persona_from_storage(
    storage: Any,
    prefix: str = "persona",
) -> dict[str, str]:
    """Load persona ``.md`` files from a StorageBackend.

    Expects layout::

        {prefix}/
            SOUL.md
            IDENTITY.md
            USER.md
            MEMORY.md
            TOOLS.md

    Args:
        storage: A StorageBackend instance (S3Storage, FilesystemStorage, etc.).
        prefix: Storage path prefix for persona files.  Default ``"persona"``.

    Returns:
        Dict mapping filename (e.g. ``"SOUL.md"``) to file content.
        Empty dict if no files found or storage is unavailable.
    """
    files: dict[str, str] = {}

    try:
        entries = await storage.list_dir(prefix)
    except (FileNotFoundError, Exception) as e:
        _log.debug("No persona files found at '%s': %s", prefix, e)
        return files

    for entry in sorted(entries):
        name = entry.rstrip("/")
        if not name or not name.endswith(".md"):
            continue

        path = f"{prefix}/{name}"
        try:
            text = await storage.read(path)
            if text and text.strip():
                files[name] = text.strip()
        except (FileNotFoundError, Exception):
            continue

    if files:
        _log.info(
            "Loaded %d persona file(s) from storage prefix '%s': %s",
            len(files),
            prefix,
            ", ".join(sorted(files)),
        )

    return files
