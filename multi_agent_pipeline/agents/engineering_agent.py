"""
Engineering Agent — orchestrates BackendAgent, BffAgent, and FrontendAgent
to generate the full monorepo in parallel.

All three sub-agents receive the same GeneratedSpecArtifact (forward contract)
so their code is consistent with each other from the start.

assemble() merges the three per-service outputs into a single flat
EngineeringArtifact that the rest of the pipeline consumes.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from rich.console import Console

from models.artifacts import (
    ArchitectureArtifact,
    EngineeringArtifact,
    GeneratedSpecArtifact,
    IntentArtifact,
    ReviewFeedback,
    ServiceArtifact,
)
from .backend_agent import BackendAgent
from .bff_agent import BffAgent
from .frontend_agent import FrontendAgent
from .base_agent import BaseAgent

console = Console()


class EngineeringAgent(BaseAgent):
    def __init__(self, artifacts_dir: str = "./artifacts"):
        super().__init__(name="Engineering Agent", artifacts_dir=artifacts_dir)
        self.backend_agent = BackendAgent(artifacts_dir)
        self.bff_agent = BffAgent(artifacts_dir)
        self.frontend_agent = FrontendAgent(artifacts_dir)

    async def run(
        self,
        intent: IntentArtifact,
        architecture: ArchitectureArtifact,
        contract: GeneratedSpecArtifact,
        review_feedback: Optional[ReviewFeedback] = None,
        iteration: int = 1,
    ) -> EngineeringArtifact:
        """Run BE, BFF, and FE sub-agents in parallel, then assemble into one artifact."""
        console.print(
            f"[cyan]⚙  Engineering (iter {iteration}): "
            "launching Backend + BFF + Frontend in parallel…[/cyan]"
        )
        be, bff, fe = await asyncio.gather(
            self.backend_agent.run(intent, architecture, contract, review_feedback, iteration),
            self.bff_agent.run(intent, architecture, contract, review_feedback, iteration),
            self.frontend_agent.run(intent, architecture, contract, review_feedback, iteration),
        )
        assembled = self._assemble(be, bff, fe, iteration)
        self.save_artifact(assembled, "03_engineering_artifact.json")
        return assembled

    async def apply_review_feedback(
        self,
        intent: IntentArtifact,
        architecture: ArchitectureArtifact,
        current: EngineeringArtifact,
        feedback: ReviewFeedback,
        contract: GeneratedSpecArtifact,
    ) -> EngineeringArtifact:
        """Re-run all sub-agents with review feedback. Increments review_iteration."""
        console.print(
            f"[yellow]🔄 Engineering: applying review feedback "
            f"(iter {current.review_iteration} → {current.review_iteration + 1})[/yellow]"
        )
        return await self.run(
            intent=intent,
            architecture=architecture,
            contract=contract,
            review_feedback=feedback,
            iteration=current.review_iteration + 1,
        )

    # ─── Assembly ────────────────────────────────────────────────────────────

    def _assemble(
        self,
        be: EngineeringArtifact,
        bff: EngineeringArtifact,
        fe: EngineeringArtifact,
        iteration: int,
    ) -> EngineeringArtifact:
        """Merge three per-service artifacts into one flat EngineeringArtifact."""
        all_files = be.generated_files + bff.generated_files + fe.generated_files
        all_endpoints = list({ep for a in (be, bff, fe) for ep in a.api_endpoints})
        all_models = list({m for a in (be, bff, fe) for m in a.data_models})
        all_env = {**be.environment_variables, **bff.environment_variables, **fe.environment_variables}
        all_steps = be.implementation_steps + bff.implementation_steps + fe.implementation_steps
        all_notes = be.spec_compliance_notes + bff.spec_compliance_notes + fe.spec_compliance_notes
        all_decisions = be.decisions + bff.decisions + fe.decisions
        all_feedback = (
            be.review_feedback_applied
            + bff.review_feedback_applied
            + fe.review_feedback_applied
        )
        assembled = EngineeringArtifact(
            service_name=None,
            services={
                "backend": self._to_service(be),
                "bff": self._to_service(bff),
                "frontend": self._to_service(fe),
            },
            backend_tech=be.backend_tech,
            frontend_tech=fe.frontend_tech,
            infrastructure="three-tier monorepo: backend (8081) + bff (8080) + frontend (3000)",
            generated_files=all_files,
            implementation_steps=all_steps,
            environment_variables=all_env,
            api_endpoints=all_endpoints,
            data_models=all_models,
            spec_compliance_notes=all_notes,
            decisions=all_decisions,
            review_iteration=iteration,
            review_feedback_applied=all_feedback,
        )
        console.print(
            f"[green]✅ Engineering assembled: "
            f"{len(be.generated_files)} BE + {len(bff.generated_files)} BFF + "
            f"{len(fe.generated_files)} FE = {len(all_files)} total files[/green]"
        )
        return assembled

    def _to_service(self, artifact: EngineeringArtifact) -> ServiceArtifact:
        return ServiceArtifact(
            service=artifact.service_name or "unknown",
            tech_stack=artifact.backend_tech or artifact.frontend_tech,
            generated_files=artifact.generated_files,
            api_endpoints=artifact.api_endpoints,
            data_models=artifact.data_models,
            environment_variables=artifact.environment_variables,
            implementation_steps=artifact.implementation_steps,
            spec_compliance_notes=artifact.spec_compliance_notes,
            decisions=artifact.decisions,
            review_iteration=artifact.review_iteration,
            review_feedback_applied=artifact.review_feedback_applied,
        )
