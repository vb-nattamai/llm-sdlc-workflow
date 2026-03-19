"""
Architecture Agent — designs system architecture from the intent artifact.
Accepts an optional SpecArtifact to constrain the design.
"""

from __future__ import annotations

from typing import Optional

from llm_sdlc_workflow.models.artifacts import ArchitectureArtifact, DiscoveryArtifact, SpecArtifact
from .base_agent import BaseAgent, load_prompt

SYSTEM_PROMPT = load_prompt("architecture_agent.md")


class ArchitectureAgent(BaseAgent):
    def __init__(self, artifacts_dir: str = "./artifacts"):
        super().__init__(name="Architecture Agent", artifacts_dir=artifacts_dir)

    async def run(
        self, intent: DiscoveryArtifact, spec: Optional[SpecArtifact] = None
    ) -> ArchitectureArtifact:
        user_message = f"""Design the system architecture for the following requirements.

## Intent Summary
{self._compact(intent)}
{self._build_spec_section(spec)}

Respond ONLY with the JSON block."""

        artifact = await self._query_and_parse(
            system=SYSTEM_PROMPT,
            user_message=user_message,
            model_class=ArchitectureArtifact,
        )

        self.save_artifact(artifact, "02_architecture_artifact.json")
        self.save_history()
        return artifact


    # ─── Architecture fix loop support ───────────────────────────────────────

    def _build_spec_section(self, spec: "Optional[SpecArtifact]") -> str:  # noqa: F821
        """Shared helper — build the spec constraints block used by run() and apply_test_feedback()."""
        if not spec:
            return ""
        parts = []
        if spec.architecture_constraints:
            parts.append(f"**Architecture constraints:**\n{spec.architecture_constraints}")
        if spec.tech_stack_constraints:
            parts.append(f"**Tech stack constraints:**\n{spec.tech_stack_constraints}")
        if spec.api_spec:
            parts.append(f"**API spec (OpenAPI/Swagger):**\n```\n{spec.api_spec[:3000]}\n```")
        if spec.database_schema:
            parts.append(f"**Database schema:**\n```\n{spec.database_schema[:2000]}\n```")
        for name, content in spec.additional_specs.items():
            parts.append(f"**{name}:**\n```\n{content[:1000]}\n```")
        if parts:
            return "\n\n## Technical Specifications (MUST be honoured)\n" + "\n\n".join(parts)
        return ""

    async def apply_test_feedback(
        self,
        intent: DiscoveryArtifact,
        current: ArchitectureArtifact,
        test_result: "TestingArtifact",  # noqa: F821
        spec: Optional[SpecArtifact] = None,
    ) -> ArchitectureArtifact:
        """Re-design the architecture to fix all blocking issues found in Stage 1 testing.

        Called by the pipeline's architecture fix loop when testing returns blockers.
        Returns a revised ArchitectureArtifact with all blocking issues addressed.
        """
        from llm_sdlc_workflow.models.artifacts import TestingArtifact  # local import to avoid cycles

        blocking = "\n".join(f"  - {i}" for i in test_result.blocking_issues) or "  (none listed)"
        findings = "\n".join(f"  - {f}" for f in test_result.findings) or "  (none listed)"
        uncovered = "\n".join(f"  - {u}" for u in test_result.uncovered_areas) or "  (none listed)"

        user_message = f"""Revise the system architecture to fix ALL blocking issues found by the Stage 1 testing agent.

## Original Intent
{self._compact(intent)}

## Current Architecture (needs revision)
{self._compact(current)}

## ⚠️  Blocking Issues — ALL MUST BE RESOLVED
{blocking}

## Additional Testing Findings
{findings}

## Requirements Not Yet Covered
{uncovered}
{self._build_spec_section(spec)}

Redesign the architecture so that every blocking issue above is eliminated.
Do NOT remove or ignore any requirement — add, split or restructure components as needed.
Respond ONLY with the JSON block."""

        artifact = await self._query_and_parse(
            system=SYSTEM_PROMPT,
            user_message=user_message,
            model_class=ArchitectureArtifact,
        )

        self.save_artifact(artifact, "02_architecture_artifact.json")
        self.save_history()
        return artifact
