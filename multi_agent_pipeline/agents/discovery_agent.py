"""
Discovery Agent — analyses raw requirements and produces a structured IntentArtifact.

Position in the SDLC: FIRST — before Architecture, Spec, and Engineering.

Responsibilities:
  - Parse and clarify ambiguous requirements
  - Uncover implicit goals the user may not have stated explicitly
  - Identify constraints (technical, business, regulatory, timeline)
  - Define scope boundaries (in-scope / out-of-scope)
  - Surface risks and uncertainties early
  - Record every interpretation decision with rationale
"""

from __future__ import annotations

from models.artifacts import IntentArtifact
from .base_agent import BaseAgent, load_prompt

SYSTEM_PROMPT = load_prompt("discovery_agent.md")


class DiscoveryAgent(BaseAgent):
    def __init__(self, artifacts_dir: str = "./artifacts"):
        super().__init__(name="Discovery Agent", artifacts_dir=artifacts_dir)

    async def run(self, requirements: str) -> IntentArtifact:
        """
        Analyse raw requirements and return a validated IntentArtifact.
        Also saves the artifact and conversation history to disk.
        """
        user_message = f"""Please analyse the following requirements and produce the structured intent artifact.

## Requirements
{requirements}

Remember: respond ONLY with the JSON block. Document every interpretation decision."""

        artifact = await self._query_and_parse(
            system=SYSTEM_PROMPT,
            user_message=user_message,
            model_class=IntentArtifact,
        )

        self.save_artifact(artifact, "01_intent_artifact.json")
        self.save_history()
        return artifact
