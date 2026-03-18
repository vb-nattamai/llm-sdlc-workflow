"""
Review Agent — audits engineering + infrastructure for security, reliability,
code quality, and performance.

Runs in an iterative loop:
  - First call: full review of all code and IaC.
  - Subsequent calls: re-review of areas flagged as critical/high in previous rounds.

Returns ReviewArtifact (which extends ReviewFeedback) so the pipeline can
check .passed and pass .critical_issues / .high_issues back to agents.
"""

from __future__ import annotations

from models.artifacts import (
    ArchitectureArtifact,
    EngineeringArtifact,
    InfrastructureArtifact,
    DiscoveryArtifact,
    ReviewArtifact,
    ReviewFeedback,
)
from .base_agent import BaseAgent, load_prompt

SYSTEM_PROMPT = load_prompt("review_agent.md")


class ReviewAgent(BaseAgent):
    def __init__(self, artifacts_dir: str = "./artifacts", generated_dir_name: str = "generated"):
        super().__init__(name="Review Agent", artifacts_dir=artifacts_dir, generated_dir_name=generated_dir_name)

    async def run(
        self,
        intent: DiscoveryArtifact,
        architecture: ArchitectureArtifact,
        engineering: EngineeringArtifact,
        infrastructure: InfrastructureArtifact,
        iteration: int = 1,
        previous_feedback: ReviewFeedback | None = None,
    ) -> ReviewArtifact:
        prev_section = ""
        if previous_feedback and iteration > 1:
            prev_section = (
                f"\n\n## Previous critical issues (must confirm as fixed or still present)\n"
                + "\n".join(f"- {i}" for i in previous_feedback.critical_issues)
                + "\n## Previous high issues\n"
                + "\n".join(f"- {i}" for i in previous_feedback.high_issues)
            )

        user_message = f"""Review iteration {iteration}.

## Discovery Summary
{self._compact(intent)}

## Architecture Summary
{self._compact(architecture)}

## Engineering Artifact (source code)
{self._compact(engineering)}

## Infrastructure Artifact (IaC files)
{self._compact(infrastructure)}
{prev_section}

Review both the source code AND the IaC files.
Set passed=true ONLY if critical_issues is empty.
Respond ONLY with the JSON block."""

        artifact = await self._query_and_parse(
            system=SYSTEM_PROMPT,
            user_message=user_message,
            model_class=ReviewArtifact,
        )
        # Ensure the iteration counter matches
        artifact.iteration = iteration

        filename = f"04_review_artifact_iter{iteration}.json"
        self.save_artifact(artifact, filename)
        self.save_history()
        return artifact
