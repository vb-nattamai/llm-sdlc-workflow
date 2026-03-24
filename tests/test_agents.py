"""
Integration tests for individual agents.

All LLM calls are mocked via patch.object(agent, "_raw_query").
No real API keys or network connections are needed.

Tests cover:
  - DiscoveryAgent.run()      — happy path, retries, empty response, coercion
  - ArchitectureAgent.run()   — happy path, spec constraints, no spec
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from llm_sdlc_workflow.agents.architecture_agent import ArchitectureAgent
from llm_sdlc_workflow.agents.discovery_agent import DiscoveryAgent
from llm_sdlc_workflow.models.artifacts import (
    ArchitectureArtifact,
    DiscoveryArtifact,
    SpecArtifact,
)


# ─── LLM response builders ────────────────────────────────────────────────────


def _discovery_llm_response(**overrides) -> str:
    """Minimal valid JSON that parses into a DiscoveryArtifact."""
    data = {
        "raw_requirements": "Build a task management API",
        "requirements": ["User authentication via JWT", "CRUD operations for tasks"],
        "user_goals": ["Fast delivery", "Secure API"],
        "constraints": ["Must use PostgreSQL"],
        "success_criteria": ["All endpoints return < 200ms"],
        "key_features": ["JWT auth", "Task CRUD"],
        "tech_preferences": ["Python", "FastAPI"],
        "domain_context": "Task management SaaS",
        "scope": "REST API backend only",
        "risks": ["Scope creep"],
        "decisions": [],
    }
    data.update(overrides)
    return json.dumps(data)


def _architecture_llm_response(**overrides) -> str:
    """Minimal valid JSON that parses into an ArchitectureArtifact."""
    data = {
        "system_overview": "Three-tier REST API",
        "architecture_style": "Monolith",
        "components": [
            {
                "name": "API Server",
                "responsibility": "Handle HTTP requests",
                "interfaces": ["REST"],
                "dependencies": ["Database"],
                "technology_hint": "FastAPI",
            }
        ],
        "data_flow": ["Client → API → DB"],
        "api_design": ["GET /tasks", "POST /tasks"],
        "database_design": "PostgreSQL with tasks table",
        "security_design": "JWT auth with bcrypt",
        "deployment_strategy": "Docker Compose",
        "patterns_used": ["Repository pattern"],
        "scalability_considerations": ["Horizontal scaling"],
        "trade_offs": ["Monolith is simpler"],
        "spec_compliance_notes": [],
        "design_decisions": [],
    }
    data.update(overrides)
    return json.dumps(data)


# ─── DiscoveryAgent ───────────────────────────────────────────────────────────


class TestDiscoveryAgentRun:
    async def test_returns_discovery_artifact_instance(self, tmp_path):
        agent = DiscoveryAgent(artifacts_dir=str(tmp_path))
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value=_discovery_llm_response())):
            result = await agent.run("Build a task management API")
        assert isinstance(result, DiscoveryArtifact)

    async def test_populates_requirements_list(self, tmp_path):
        agent = DiscoveryAgent(artifacts_dir=str(tmp_path))
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value=_discovery_llm_response())):
            result = await agent.run("Build a task management API")
        assert "User authentication via JWT" in result.requirements
        assert "CRUD operations for tasks" in result.requirements

    async def test_preserves_raw_requirements(self, tmp_path):
        agent = DiscoveryAgent(artifacts_dir=str(tmp_path))
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value=_discovery_llm_response())):
            result = await agent.run("Build a task management API")
        assert result.raw_requirements == "Build a task management API"

    async def test_populates_all_required_fields(self, tmp_path):
        agent = DiscoveryAgent(artifacts_dir=str(tmp_path))
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value=_discovery_llm_response())):
            result = await agent.run("Build a task management API")
        assert result.user_goals
        assert result.constraints
        assert result.domain_context
        assert result.scope

    async def test_saves_artifact_json_to_disk(self, tmp_path):
        agent = DiscoveryAgent(artifacts_dir=str(tmp_path))
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value=_discovery_llm_response())):
            await agent.run("Build a task management API")
        artifact_file = tmp_path / "01_discovery_artifact.json"
        assert artifact_file.exists()
        data = json.loads(artifact_file.read_text())
        assert data["raw_requirements"] == "Build a task management API"

    async def test_saves_conversation_history_to_disk(self, tmp_path):
        agent = DiscoveryAgent(artifacts_dir=str(tmp_path))
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value=_discovery_llm_response())):
            await agent.run("Build a task management API")
        history_files = list(tmp_path.glob("*_history.json"))
        assert len(history_files) == 1
        history = json.loads(history_files[0].read_text())
        assert len(history) >= 2  # at least user + assistant turns

    async def test_retries_on_transient_error_then_succeeds(self, tmp_path):
        agent = DiscoveryAgent(artifacts_dir=str(tmp_path))
        # Two-phase: phase1 fails once then succeeds, phase2 succeeds on first try
        mock = AsyncMock(
            side_effect=[
                RuntimeError("transient rate limit"),
                _discovery_llm_response(),
                _discovery_llm_response(),  # phase 2 call
            ]
        )
        with patch.object(agent, "_raw_query", new=mock), patch("asyncio.sleep", new=AsyncMock()):
            result = await agent.run("Build a task management API")
        assert isinstance(result, DiscoveryArtifact)
        assert mock.call_count == 3  # 2 for phase1 (1 retry) + 1 for phase2

    async def test_raises_after_max_retries_exhausted(self, tmp_path):
        agent = DiscoveryAgent(artifacts_dir=str(tmp_path))
        mock = AsyncMock(side_effect=RuntimeError("persistent failure"))
        with patch.object(agent, "_raw_query", new=mock), patch("asyncio.sleep", new=AsyncMock()):
            with pytest.raises(RuntimeError, match="persistent failure"):
                await agent.run("Build a task management API")
        assert mock.call_count == 3  # MAX_RETRIES

    async def test_raises_value_error_on_empty_llm_response(self, tmp_path):
        agent = DiscoveryAgent(artifacts_dir=str(tmp_path))
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value="")):
            with pytest.raises(ValueError, match="empty response"):
                await agent.run("Build a task management API")

    async def test_coerces_dict_items_in_list_fields(self, tmp_path):
        """LLM may return dicts instead of strings — field_validator must coerce them."""
        agent = DiscoveryAgent(artifacts_dir=str(tmp_path))
        response = _discovery_llm_response(
            requirements=[{"description": "User authentication"}, "CRUD tasks"],
            constraints=[{"name": "PostgreSQL only"}, "No NoSQL"],
        )
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value=response)):
            result = await agent.run("Build a task management API")
        assert "User authentication" in result.requirements
        assert "CRUD tasks" in result.requirements
        assert "PostgreSQL only" in result.constraints
        assert "No NoSQL" in result.constraints

    async def test_optional_tech_preferences_is_falsy_when_llm_returns_null(self, tmp_path):
        """When LLM returns null for tech_preferences the validator coerces it to [].
        Both None (field absent) and [] (null passed through validator) are falsy."""
        agent = DiscoveryAgent(artifacts_dir=str(tmp_path))
        response = _discovery_llm_response(tech_preferences=None)
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value=response)):
            result = await agent.run("Build a task management API")
        # _coerce_str_list(None) → [] so tech_preferences is falsy (either None or [])
        assert not result.tech_preferences

    async def test_input_requirements_appear_in_llm_call(self, tmp_path):
        """The user's requirements text must be forwarded to the LLM."""
        agent = DiscoveryAgent(artifacts_dir=str(tmp_path))
        mock = AsyncMock(return_value=_discovery_llm_response())
        with patch.object(agent, "_raw_query", new=mock):
            await agent.run("unique-requirement-string-abc")
        # Requirements appear in Phase 1 (first call); call_args only has the last call
        user_msg = mock.call_args_list[0][0][1]  # phase 1 user_message
        assert "unique-requirement-string-abc" in user_msg


# ─── ArchitectureAgent ────────────────────────────────────────────────────────


def _make_intent() -> DiscoveryArtifact:
    return DiscoveryArtifact(
        raw_requirements="Build API",
        requirements=["Auth", "CRUD"],
        user_goals=["Fast delivery"],
        constraints=["PostgreSQL"],
        success_criteria=["< 200ms"],
        key_features=["JWT"],
        domain_context="API",
        scope="backend",
    )


class TestArchitectureAgentRun:
    async def test_returns_architecture_artifact_instance(self, tmp_path):
        agent = ArchitectureAgent(artifacts_dir=str(tmp_path))
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value=_architecture_llm_response())):
            result = await agent.run(_make_intent())
        assert isinstance(result, ArchitectureArtifact)

    async def test_populates_architecture_fields(self, tmp_path):
        agent = ArchitectureAgent(artifacts_dir=str(tmp_path))
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value=_architecture_llm_response())):
            result = await agent.run(_make_intent())
        assert result.architecture_style == "Monolith"
        assert result.system_overview
        assert result.database_design

    async def test_populates_components_list(self, tmp_path):
        agent = ArchitectureAgent(artifacts_dir=str(tmp_path))
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value=_architecture_llm_response())):
            result = await agent.run(_make_intent())
        assert len(result.components) == 1
        assert result.components[0].name == "API Server"

    async def test_saves_artifact_to_disk(self, tmp_path):
        agent = ArchitectureAgent(artifacts_dir=str(tmp_path))
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value=_architecture_llm_response())):
            await agent.run(_make_intent())
        assert (tmp_path / "02_architecture_artifact.json").exists()

    async def test_works_without_spec(self, tmp_path):
        agent = ArchitectureAgent(artifacts_dir=str(tmp_path))
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value=_architecture_llm_response())):
            result = await agent.run(_make_intent(), spec=None)
        assert isinstance(result, ArchitectureArtifact)

    async def test_includes_spec_constraints_in_user_message(self, tmp_path):
        agent = ArchitectureAgent(artifacts_dir=str(tmp_path))
        spec = SpecArtifact(
            architecture_constraints="Must use microservices pattern",
            tech_stack_constraints="Kotlin Spring Boot, React TypeScript",
        )
        mock = AsyncMock(return_value=_architecture_llm_response())
        with patch.object(agent, "_raw_query", new=mock):
            await agent.run(_make_intent(), spec=spec)
        # Spec constraints are injected in Phase 1 (first call)
        user_message = mock.call_args_list[0][0][1]
        assert "microservices" in user_message
        assert "Kotlin" in user_message

    async def test_includes_api_spec_in_user_message_when_provided(self, tmp_path):
        agent = ArchitectureAgent(artifacts_dir=str(tmp_path))
        spec = SpecArtifact(api_spec="openapi: '3.0.0'\ninfo:\n  title: MyAPI\n")
        mock = AsyncMock(return_value=_architecture_llm_response())
        with patch.object(agent, "_raw_query", new=mock):
            await agent.run(_make_intent(), spec=spec)
        # API spec is injected in Phase 1 (first call)
        user_message = mock.call_args_list[0][0][1]
        assert "openapi" in user_message.lower()

    async def test_intent_compact_appears_in_user_message(self, tmp_path):
        """Architecture agent must pass a compact summary of the intent to the LLM."""
        agent = ArchitectureAgent(artifacts_dir=str(tmp_path))
        mock = AsyncMock(return_value=_architecture_llm_response())
        with patch.object(agent, "_raw_query", new=mock):
            await agent.run(_make_intent())
        # Intent compact is included in Phase 1 (first call)
        user_message = mock.call_args_list[0][0][1]
        # The compact output contains the DiscoveryArtifact class name
        assert "DiscoveryArtifact" in user_message

    async def test_retries_on_transient_error(self, tmp_path):
        agent = ArchitectureAgent(artifacts_dir=str(tmp_path))
        # Two-phase: phase1 fails then succeeds, phase2 succeeds on first try
        mock = AsyncMock(
            side_effect=[RuntimeError("timeout"), _architecture_llm_response(), _architecture_llm_response()]
        )
        with patch.object(agent, "_raw_query", new=mock), patch("asyncio.sleep", new=AsyncMock()):
            result = await agent.run(_make_intent())
        assert isinstance(result, ArchitectureArtifact)
        assert mock.call_count == 3  # 2 for phase1 (1 retry) + 1 for phase2

    async def test_raises_value_error_on_empty_response(self, tmp_path):
        agent = ArchitectureAgent(artifacts_dir=str(tmp_path))
        with patch.object(agent, "_raw_query", new=AsyncMock(return_value="")):
            with pytest.raises(ValueError, match="empty response"):
                await agent.run(_make_intent())
