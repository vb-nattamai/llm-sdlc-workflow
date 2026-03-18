"""BFF sub-agent — generates the bff/ service in the monorepo."""
from __future__ import annotations
from typing import Optional
from models.artifacts import (
    ArchitectureArtifact, EngineeringArtifact, GeneratedSpecArtifact,
    IntentArtifact, ReviewFeedback,
)
from .base_agent import BaseAgent, load_prompt

SYSTEM_PROMPT = load_prompt("bff_agent.md")


class BffAgent(BaseAgent):
    def __init__(self, artifacts_dir: str = "./artifacts"):
        super().__init__(name="BFF Agent", artifacts_dir=artifacts_dir)

    async def run(
        self,
        intent: IntentArtifact,
        architecture: ArchitectureArtifact,
        contract: GeneratedSpecArtifact,
        review_feedback: Optional[ReviewFeedback] = None,
        iteration: int = 1,
    ) -> EngineeringArtifact:
        spec_section = self._build_contract_section(contract)
        feedback_section = self._build_feedback_section(review_feedback)

        plan_message = f"""Plan and list every file for the bff/ service.

## Intent
{self._compact(intent)}

## Architecture
{self._compact(architecture)}
{spec_section}{feedback_section}

Return JSON with every file's content = \"__PENDING__\". Valid json."""

        fill_tmpl = (
            "Write COMPLETE, RUNNABLE Kotlin/Spring WebFlux content for: {path}\n"
            "Purpose: {purpose}\n"
            "Service: bff (port 8080, calls backend:8081)\n"
            "Architecture: {arch_style}\n"
            "BFF endpoints: {endpoints_summary}\n\n"
            "Return JSON: {{\"content\": \"<full file>\"}}\n"
            "No TODOs. Valid json."
        )

        artifact = await self._query_and_parse_chunked(
            system=SYSTEM_PROMPT,
            plan_message=plan_message,
            file_keys=["generated_files"],
            model_class=EngineeringArtifact,
            fill_message_tmpl=fill_tmpl,
            fill_context={
                "arch_style": getattr(architecture, "architecture_style", "monorepo"),
                "endpoints_summary": "; ".join(contract.openapi_spec[:200].splitlines()[:5]) if contract.openapi_spec else "see architecture",
            },
        )
        artifact.service_name = "bff"
        artifact.review_iteration = iteration
        if review_feedback:
            artifact.review_feedback_applied = list(review_feedback.critical_issues) + list(review_feedback.high_issues)
        self.save_artifact(artifact, "03b_bff_artifact.json")
        self._write_service_files(artifact)
        self.save_history()
        return artifact

    def _build_contract_section(self, contract: GeneratedSpecArtifact) -> str:
        parts = ["\n\n## Contract (source of truth — implement exactly)"]
        if contract.openapi_spec:
            parts.append(f"### OpenAPI spec\n```yaml\n{contract.openapi_spec[:4000]}\n```")
        if contract.tech_stack_constraints:
            parts.append(f"### Tech constraints\n{contract.tech_stack_constraints}")
        if contract.architecture_constraints:
            parts.append(f"### Architecture constraints\n{contract.architecture_constraints}")
        return "\n\n".join(parts)

    def _build_feedback_section(self, feedback: Optional[ReviewFeedback]) -> str:
        if not feedback:
            return ""
        lines = [f"\n\n## Review Feedback (iteration {feedback.iteration}) — MUST address"]
        if feedback.critical_issues:
            lines += ["### CRITICAL:"] + [f"- {i}" for i in feedback.critical_issues]
        if feedback.high_issues:
            lines += ["### HIGH:"] + [f"- {i}" for i in feedback.high_issues]
        return "\n".join(lines)

    def _write_service_files(self, artifact: EngineeringArtifact) -> None:
        import os
        from rich.console import Console
        con = Console()
        base = os.path.join(self.artifacts_dir, "generated")
        os.makedirs(base, exist_ok=True)
        for f in artifact.generated_files:
            safe = os.path.normpath(f.path).lstrip(os.sep)
            full = os.path.join(base, safe)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as fh:
                fh.write(f.content)
            con.print(f"[dim]  📄 {full}[/dim]")
