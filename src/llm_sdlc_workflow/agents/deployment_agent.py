"""
Deployment Agent — generates CI/CD pipelines and Kubernetes/Helm deployment manifests.

Responsibilities:
  - GitHub Actions CI workflow (build, test, lint, Docker build)
  - GitHub Actions CD workflows (staging auto-deploy + production canary/blue-green)
  - Kubernetes manifests (Namespace, Deployment, Service, Ingress, HPA, PDB)
  - Blue-green deployment manifests + atomic traffic-switch script
  - Canary deployment via Argo Rollout CRD + AnalysisTemplate
  - Helm chart (Chart.yaml, values per environment, full templates/)
  - Deployment and rollback helper scripts

Runs in parallel with InfrastructureAgent.apply() after the review loop passes.
Output files are written to generated/deployment/.
"""

from __future__ import annotations

import os
from typing import Optional

from rich.console import Console

from llm_sdlc_workflow.models.artifacts import (
    ArchitectureArtifact,
    DeploymentArtifact,
    DiscoveryArtifact,
    EngineeringArtifact,
    GeneratedSpecArtifact,
    ReviewFeedback,
)
from .base_agent import BaseAgent, load_prompt

SYSTEM_PROMPT = load_prompt("deployment_agent.md")

console = Console()


class DeploymentAgent(BaseAgent):
    def __init__(
        self,
        artifacts_dir: str = "./artifacts",
        generated_dir_name: str = "generated",
    ):
        super().__init__(
            name="Deployment Agent",
            artifacts_dir=artifacts_dir,
            generated_dir_name=generated_dir_name,
        )

    async def run(
        self,
        intent: DiscoveryArtifact,
        architecture: ArchitectureArtifact,
        engineering: EngineeringArtifact,
        contract: GeneratedSpecArtifact,
        review_feedback: Optional[ReviewFeedback] = None,
        iteration: int = 1,
    ) -> DeploymentArtifact:
        """Generate the full CI/CD and deployment package via chunked LLM calls."""

        feedback_section = self._build_feedback_section(review_feedback)

        services = contract.monorepo_services or ["backend", "bff", "frontend"]
        ports = contract.service_ports or {}
        ports_str = ", ".join(f"{s}:{p}" for s, p in ports.items()) if ports else "see architecture"

        plan_message = f"""Generate a complete CI/CD and Kubernetes deployment package for this application.

## Discovery Summary
{self._compact(intent)}

## Architecture Summary
{self._compact(architecture)}

## Engineering Summary (services already generated)
{self._compact(engineering)}

## Services & Ports
Services: {', '.join(services)}
Ports: {ports_str}
{feedback_section}

Produce ALL files listed in the system prompt:
  - GitHub Actions workflows (.github/workflows/)
  - Kubernetes manifests (k8s/)
  - Blue-green manifests (k8s/blue-green/)
  - Canary Argo Rollout manifests (k8s/canary/)
  - Helm chart (helm/)
  - Deployment scripts (scripts/)
  - Makefile

Include BOTH canary AND blue-green strategies — the user chooses at deploy time.

Return JSON with every deployment_file content = "__PENDING__". Valid json."""

        fill_tmpl = (
            "Write the COMPLETE content for the deployment file at path: {path}\n"
            "Purpose: {purpose}\n\n"
            "## Context\n"
            f"Services: {', '.join(services)}\n"
            f"Ports: {ports_str}\n"
            "Architecture: {arch_style}\n\n"
            "Rules:\n"
            "  - No hardcoded secrets — use env vars / GitHub secrets\n"
            "  - All shell scripts: set -euo pipefail\n"
            "  - GitHub Actions: use pinned action versions (@v4, @v3)\n"
            "  - K8s labels: use app.kubernetes.io/* recommended labels\n"
            "  - Helm templates: use _helpers.tpl helpers\n\n"
            "Return JSON: {{\"content\": \"<full file content>\"}}\n"
            "No truncation. No placeholders. Complete, runnable file. Valid json."
        )

        artifact = await self._query_and_parse_chunked(
            system=SYSTEM_PROMPT,
            plan_message=plan_message,
            file_keys=["deployment_files"],
            model_class=DeploymentArtifact,
            fill_message_tmpl=fill_tmpl,
            fill_context={
                "arch_style": getattr(architecture, "architecture_style", "microservices"),
            },
        )

        artifact.review_iteration = iteration
        if review_feedback:
            artifact.review_feedback_applied = (
                list(review_feedback.critical_issues) + list(review_feedback.high_issues)
            )

        self._write_deployment_files(artifact)
        self.save_artifact(artifact, "07_deployment_artifact.json")
        self.save_history()
        return artifact

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _build_feedback_section(self, feedback: Optional[ReviewFeedback]) -> str:
        if not feedback:
            return ""
        lines = [f"\n## Review Feedback (iteration {feedback.iteration}) — MUST address"]
        if feedback.critical_issues:
            lines += ["### CRITICAL:"] + [f"- {i}" for i in feedback.critical_issues]
        if feedback.high_issues:
            lines += ["### HIGH:"] + [f"- {i}" for i in feedback.high_issues]
        return "\n".join(lines)

    def _write_deployment_files(self, artifact: DeploymentArtifact) -> None:
        """Write all deployment files under generated/deployment/."""
        base = os.path.join(self.artifacts_dir, self.generated_dir_name)
        written = 0
        for f in artifact.deployment_files:
            safe = os.path.normpath(f.path).lstrip(os.sep)
            # Files that start with .github/ or are root-level go directly into generated/
            # All others land under deployment/ to avoid colliding with service files
            if safe.startswith(".github") or safe in ("Makefile",):
                full = os.path.join(base, safe)
            else:
                full = os.path.join(base, "deployment", safe)
            os.makedirs(os.path.dirname(full) or base, exist_ok=True)
            with open(full, "w") as fh:
                fh.write(f.content)
            console.print(f"[dim]  🚀 {full}[/dim]")
            written += 1
        console.print(
            f"[green]✅ Deployment files written: {written} files "
            f"(strategy: {artifact.deployment_strategy})[/green]"
        )
        if artifact.deployment_notes:
            console.print("[bold yellow]📋 Deployment prerequisites:[/bold yellow]")
            for note in artifact.deployment_notes:
                console.print(f"  [yellow]• {note}[/yellow]")
        if artifact.secrets_required:
            console.print("[bold cyan]🔑 GitHub secrets to configure:[/bold cyan]")
            for secret in artifact.secrets_required:
                console.print(f"  [cyan]• {secret}[/cyan]")
