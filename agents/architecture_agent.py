"""
Architecture Agent — designs system architecture from the intent artifact.
Accepts an optional SpecArtifact to constrain the design.
"""

from __future__ import annotations

from typing import Optional

from models.artifacts import ArchitectureArtifact, DiscoveryArtifact, SpecArtifact
from .base_agent import BaseAgent, load_prompt

SYSTEM_PROMPT = load_prompt("architecture_agent.md")


class ArchitectureAgent(BaseAgent):
    def __init__(self, artifacts_dir: str = "./artifacts"):
        super().__init__(name="Architecture Agent", artifacts_dir=artifacts_dir)

    async def run(
        self, intent: DiscoveryArtifact, spec: Optional[SpecArtifact] = None
    ) -> ArchitectureArtifact:
        spec_section = ""
        if spec:
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
                spec_section = "\n\n## Technical Specifications (MUST be honoured)\n" + "\n\n".join(parts)

        user_message = f"""Design the system architecture for the following requirements.

## Intent Summary
{self._compact(intent)}
{spec_section}

Respond ONLY with the JSON block."""

        artifact = await self._query_and_parse(
            system=SYSTEM_PROMPT,
            user_message=user_message,
            model_class=ArchitectureArtifact,
        )

        self.save_artifact(artifact, "02_architecture_artifact.json")
        self.save_history()
        return artifact
