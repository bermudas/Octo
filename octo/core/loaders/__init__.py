"""Core loaders — MCP tools, agents, skills, and persona.

Public API::

    from octo.core.loaders.agent_loader import AgentConfig, load_agents, load_octo_agents
    from octo.core.loaders.agent_loader import load_agents_from_storage  # async, S3/storage
    from octo.core.loaders.skill_loader import SkillConfig, load_skills
    from octo.core.loaders.skill_loader import load_skills_from_storage  # async, S3/storage
    from octo.core.loaders.persona_loader import load_persona_from_storage  # async, S3/storage
    from octo.core.loaders.mcp_loader import MCPSessionPool, create_mcp_client
"""
from __future__ import annotations
