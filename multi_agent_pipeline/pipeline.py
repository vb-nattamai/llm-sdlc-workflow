"""
Pipeline Orchestrator — coordinates all agents.

Flow:
  1. DiscoveryAgent       → DiscoveryArtifact
  2. ArchitectureAgent    → ArchitectureArtifact
  3. TestingAgent         → TestingArtifact (stage: architecture)
  4. SpecAgent             → GeneratedSpecArtifact (forward contract: OpenAPI + DDL)
  5. EngineeringAgent  ┐
     InfrastructureAgent ┘  ← run in PARALLEL (asyncio.gather)
  6. ReviewAgent          → ReviewArtifact (loop up to MAX_REVIEW_ITERATIONS)
     ↳ if not passed → EngineeringAgent.apply_review_feedback
                      + InfrastructureAgent.apply_review_feedback (parallel)
     ↳ repeat until passed or max iterations reached
  7. TestingAgent         → TestingArtifact (stage: infrastructure)
     — live HTTP tests against running container
     — Cypress spec generation + optional run
  8. TestingAgent         → TestingArtifact (stage: review)  ← final sign-off
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agents import (
    ArchitectureAgent,
    DiscoveryAgent,
    EngineeringAgent,
    InfrastructureAgent,
    ReviewAgent,
    SpecAgent,
    TestingAgent,
)
from models.artifacts import (
    ArchitectureArtifact,
    DiscoveryArtifact,
    EngineeringArtifact,
    GeneratedSpecArtifact,
    InfrastructureArtifact,
    ReviewArtifact,
    SpecArtifact,
    TestingArtifact,
)

console = Console()

MAX_REVIEW_ITERATIONS = 3


@dataclass
class PipelineResult:
    requirements: str
    started_at: str
    completed_at: Optional[str] = None
    artifacts_dir: str = "./artifacts"

    intent: Optional[DiscoveryArtifact] = None
    architecture: Optional[ArchitectureArtifact] = None
    generated_spec: Optional[GeneratedSpecArtifact] = None
    engineering: Optional[EngineeringArtifact] = None
    infrastructure: Optional[InfrastructureArtifact] = None
    review_iterations: List[ReviewArtifact] = field(default_factory=list)

    test_architecture: Optional[TestingArtifact] = None
    test_infrastructure: Optional[TestingArtifact] = None
    test_review: Optional[TestingArtifact] = None

    errors: list = field(default_factory=list)

    @property
    def review(self) -> Optional[ReviewArtifact]:
        return self.review_iterations[-1] if self.review_iterations else None

    @property
    def passed(self) -> bool:
        return all([
            self.test_architecture and self.test_architecture.passed,
            self.test_infrastructure and self.test_infrastructure.passed,
            self.test_review and self.test_review.passed,
            self.review and self.review.passed,
        ])


class Pipeline:
    def __init__(self, artifacts_dir: str = "./artifacts"):
        self.artifacts_dir = artifacts_dir
        os.makedirs(artifacts_dir, exist_ok=True)
        self.discovery_agent = DiscoveryAgent(artifacts_dir)
        self.architecture_agent = ArchitectureAgent(artifacts_dir)
        self.spec_agent = SpecAgent(artifacts_dir)
        self.engineering_agent = EngineeringAgent(artifacts_dir)
        self.infrastructure_agent = InfrastructureAgent(artifacts_dir)
        self.review_agent = ReviewAgent(artifacts_dir)
        self.testing_agent = TestingAgent(artifacts_dir)

    async def run(
        self,
        requirements: str,
        spec: Optional[SpecArtifact] = None,
        existing_spec: Optional[SpecArtifact] = None,
    ) -> PipelineResult:
        result = PipelineResult(
            requirements=requirements,
            started_at=datetime.now().isoformat(),
            artifacts_dir=self.artifacts_dir,
        )

        console.print(Panel(
            "[bold]🚀 Multi-Agent Pipeline Starting[/bold]\n\n"
            "Intent → Architecture → [Test] → Spec → "
            "[Engineering ‖ Infrastructure] → "
            "Review loop (max " + str(MAX_REVIEW_ITERATIONS) + ") → "
            "[Live Test + Cypress] → [Final Test]",
            title="Pipeline",
            style="bold blue",
        ))

        try:
            # ── Step 1: Intent ──────────────────────────────────────────────
            self._step_header("Step 1", "Discovery Agent", "Analysing requirements, goals, constraints and risks")
            result.intent = await self.discovery_agent.run(requirements)
            self._step_done("Discovery", len(result.intent.requirements), "requirements extracted")

            # ── Step 2: Architecture ────────────────────────────────────────
            self._step_header("Step 2", "Architecture Agent", "Designing system architecture")
            result.architecture = await self.architecture_agent.run(result.intent, spec)
            self._step_done("Architecture", len(result.architecture.components), "components designed")

            # ── Step 3: Testing — architecture stage ────────────────────────
            self._step_header("Step 3", "Testing Agent", "Verifying architecture vs requirements")
            result.test_architecture = await self.testing_agent.run(
                stage="architecture",
                intent=result.intent,
                architecture=result.architecture,
            )
            self._testing_status("Architecture", result.test_architecture)

            # ── Step 4: Spec Agent — forward contract ───────────────────────
            self._step_header("Step 4", "Spec Agent", "Generating forward contract (OpenAPI + DDL)")
            result.generated_spec = await self.spec_agent.run(
                result.intent, result.architecture, existing_spec
            )
            services = ", ".join(result.generated_spec.monorepo_services)
            ports = ", ".join(
                f"{s}:{p}" for s, p in result.generated_spec.service_ports.items()
            )
            self._step_done(
                "Spec", len(result.generated_spec.generated_spec_files),
                f"spec files — services: [{services}]  ports: {ports}"
            )

            # ── Step 5: Engineering + Infrastructure in PARALLEL ────────────
            self._step_header(
                "Step 5", "Engineering + Infrastructure",
                "Generating code and IaC in parallel (Kotlin/React + Docker)"
            )
            result.engineering, result.infrastructure = await asyncio.gather(
                self.engineering_agent.run(result.intent, result.architecture, result.generated_spec),
                self.infrastructure_agent.run(
                    result.intent, result.architecture,
                    EngineeringArtifact(),
                    skip_start=True,
                ),
            )
            self._step_done("Engineering", len(result.engineering.generated_files), "files generated")
            self._step_done(
                "Infrastructure", len(result.infrastructure.iac_files),
                "IaC files written (containers start after review loop)"
            )

            # ── Step 6: Review loop ─────────────────────────────────────────
            previous_feedback = None
            for iteration in range(1, MAX_REVIEW_ITERATIONS + 1):
                self._step_header(
                    f"Step 6 (iter {iteration})", "Review Agent",
                    f"Reviewing code + IaC — iteration {iteration}/{MAX_REVIEW_ITERATIONS}"
                )
                review = await self.review_agent.run(
                    intent=result.intent,
                    architecture=result.architecture,
                    engineering=result.engineering,
                    infrastructure=result.infrastructure,
                    iteration=iteration,
                    previous_feedback=previous_feedback,
                )
                result.review_iterations.append(review)
                self._review_status(review)

                if review.passed:
                    console.print(
                        f"[bold green]✅ Review passed on iteration {iteration}![/bold green]\n"
                    )
                    break

                if iteration < MAX_REVIEW_ITERATIONS:
                    console.print(
                        f"[yellow]🔄 Review failed — applying feedback and re-generating "
                        f"(iteration {iteration + 1}/{MAX_REVIEW_ITERATIONS})…[/yellow]"
                    )
                    # Apply feedback to both agents in parallel
                    result.engineering, result.infrastructure = await asyncio.gather(
                        self.engineering_agent.apply_review_feedback(
                            result.intent, result.architecture,
                            result.engineering, review, result.generated_spec
                        ),
                        self.infrastructure_agent.apply_review_feedback(
                            result.intent, result.architecture,
                            result.engineering, result.infrastructure, review
                        ),
                    )
                    previous_feedback = review
                else:
                    console.print(
                        f"[red]⚠ Max review iterations ({MAX_REVIEW_ITERATIONS}) reached. "
                        "Continuing with best effort.[/red]\n"
                    )

            # ── Step 7: Start containers + live testing ─────────────────────
            self._step_header("Step 7", "Infrastructure Agent", "Building and starting containers")
            result.infrastructure = await self.infrastructure_agent.run(
                intent=result.intent,
                architecture=result.architecture,
                engineering=result.engineering,
            )
            if result.infrastructure.container_running:
                self._step_done(
                    "Infrastructure",
                    len(result.infrastructure.iac_files),
                    f"service live at {result.infrastructure.base_url}",
                )
            else:
                self._step_done(
                    "Infrastructure",
                    len(result.infrastructure.iac_files),
                    "IaC files written (container not running — live tests skipped)",
                )

            self._step_header(
                "Step 7b", "Testing Agent",
                "Live HTTP tests + Cypress e2e spec generation"
            )
            result.test_infrastructure = await self.testing_agent.run(
                stage="infrastructure",
                intent=result.intent,
                architecture=result.architecture,
                engineering=result.engineering,
                infrastructure=result.infrastructure,
            )
            self._testing_status("Infrastructure (live + Cypress)", result.test_infrastructure)

            # ── Step 8: Final testing ────────────────────────────────────────
            self._step_header("Step 8", "Testing Agent", "Final verification")
            result.test_review = await self.testing_agent.run(
                stage="review",
                intent=result.intent,
                architecture=result.architecture,
                engineering=result.engineering,
                review=result.review,
            )
            self._testing_status("Final", result.test_review)

        except Exception as e:
            result.errors.append(str(e))
            console.print_exception()
        finally:
            if result.infrastructure and result.infrastructure.container_running:
                await self.infrastructure_agent.stop_containers()

        result.completed_at = datetime.now().isoformat()
        self._save_report(result)
        return result

    # ─── Display helpers ─────────────────────────────────────────────────────

    def _step_header(self, step: str, agent: str, description: str) -> None:
        console.print(Panel(
            f"[bold]{agent}[/bold]\n{description}",
            title=f"[cyan]{step}[/cyan]",
            style="cyan",
        ))

    def _step_done(self, name: str, count: int, label: str) -> None:
        console.print(f"[green]✅ {name} complete — {count} {label}[/green]\n")

    def _testing_status(self, stage: str, artifact: TestingArtifact) -> None:
        icon = "✅" if artifact.passed else "❌"
        color = "green" if artifact.passed else "red"
        total = len(artifact.test_cases)
        passed = sum(1 for tc in artifact.test_cases if tc.status == "passed")
        failed = sum(1 for tc in artifact.test_cases if tc.status == "failed")
        cypress = len(artifact.cypress_spec_files)
        cypress_note = f", {cypress} Cypress spec(s)" if cypress else ""
        console.print(
            f"[{color}]{icon} Testing ({stage}): {passed}/{total} passed, "
            f"{failed} failed, {len(artifact.blocking_issues)} blocking{cypress_note}[/{color}]\n"
        )

    def _review_status(self, artifact: ReviewArtifact) -> None:
        icon = "✅" if artifact.passed else "❌"
        color = "green" if artifact.passed else "red"
        console.print(
            f"[{color}]{icon} Review (iter {artifact.iteration}): "
            f"score={artifact.overall_score}/100, "
            f"critical={len(artifact.critical_issues)}, "
            f"high={len(artifact.high_issues)}, "
            f"total_issues={len(artifact.issues)}[/{color}]\n"
        )

    # ─── Report ──────────────────────────────────────────────────────────────

    def _save_report(self, result: PipelineResult) -> None:
        report = {
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "passed": result.passed,
            "errors": result.errors,
            "review_iterations_count": len(result.review_iterations),
            "summary": {
                "requirements_count": len(result.intent.requirements) if result.intent else 0,
                "components_count": len(result.architecture.components) if result.architecture else 0,
                "spec_generated": bool(result.generated_spec),
                "monorepo_services": result.generated_spec.monorepo_services if result.generated_spec else [],
                "openapi_spec_lines": len((result.generated_spec.openapi_spec or "").splitlines()) if result.generated_spec else 0,
                "files_generated": len(result.engineering.generated_files) if result.engineering else 0,
                "iac_files_written": len(result.infrastructure.iac_files) if result.infrastructure else 0,
                "container_running": result.infrastructure.container_running if result.infrastructure else False,
                "container_url": result.infrastructure.base_url if result.infrastructure else None,
                "review_passed": result.review.passed if result.review else None,
                "review_score": result.review.overall_score if result.review else None,
                "test_architecture_passed": result.test_architecture.passed if result.test_architecture else None,
                "test_infrastructure_passed": result.test_infrastructure.passed if result.test_infrastructure else None,
                "cypress_specs": len(result.test_infrastructure.cypress_spec_files) if result.test_infrastructure else 0,
                "test_review_passed": result.test_review.passed if result.test_review else None,
            },
        }
        path = os.path.join(self.artifacts_dir, "00_pipeline_report.json")
        with open(path, "w") as f:
            json.dump(report, f, indent=2)
        console.print(f"\n[dim]📊 Pipeline report saved → {path}[/dim]")

    def print_summary(self, result: PipelineResult) -> None:
        table = Table(title="Pipeline Run Summary", show_header=True, header_style="bold magenta")
        table.add_column("Stage", style="cyan", no_wrap=True)
        table.add_column("Status", justify="center")
        table.add_column("Key Metrics")

        def status(ok):
            if ok is None:
                return "[dim]SKIPPED[/dim]"
            return "[green]PASSED[/green]" if ok else "[red]FAILED[/red]"

        if result.intent:
            table.add_row("Discovery", "[green]DONE[/green]",
                f"{len(result.intent.requirements)} reqs, {len(result.intent.key_features)} features")
        if result.architecture:
            table.add_row("Architecture", "[green]DONE[/green]",
                f"{len(result.architecture.components)} components, "
                f"style: {result.architecture.architecture_style}")
        if result.generated_spec:
            spec = result.generated_spec
            services = ", ".join(spec.monorepo_services)
            ports = ", ".join(f"{s}:{p}" for s, p in spec.service_ports.items())
            table.add_row("Spec (forward contract)", "[green]DONE[/green]",
                f"{len(spec.generated_spec_files)} files — [{services}]  {ports}")
        if result.test_architecture:
            tc = result.test_architecture
            passed = sum(1 for t in tc.test_cases if t.status == "passed")
            table.add_row("Testing (architecture)", status(tc.passed),
                f"{passed}/{len(tc.test_cases)} passed, {len(tc.blocking_issues)} blocking")
        if result.engineering:
            eng = result.engineering
            table.add_row("Engineering", "[green]DONE[/green]",
                f"{len(eng.generated_files)} files, "
                f"backend: {eng.backend_tech.framework if eng.backend_tech else '?'}, "
                f"review_iter={eng.review_iteration}")
        if result.infrastructure:
            infra = result.infrastructure
            container_status = f"live at {infra.base_url}" if infra.container_running else "not running"
            table.add_row("Infrastructure", "[green]DONE[/green]",
                f"{len(infra.iac_files)} IaC files, {container_status}, "
                f"review_iter={infra.review_iteration}")
        for i, rv in enumerate(result.review_iterations, 1):
            table.add_row(
                f"Review (iter {i})", status(rv.passed),
                f"score={rv.overall_score}/100, "
                f"critical={len(rv.critical_issues)}, "
                f"issues={len(rv.issues)}"
            )
        if result.test_infrastructure:
            tc = result.test_infrastructure
            live_total = len(tc.http_test_cases)
            live_passed = sum(1 for t in tc.http_test_cases if t.status == "passed")
            static_passed = sum(1 for t in tc.test_cases if t.status == "passed")
            cypress = len(tc.cypress_spec_files)
            table.add_row("Testing (infrastructure)", status(tc.passed),
                f"{static_passed}/{len(tc.test_cases)} plan, "
                f"{live_passed}/{live_total} live HTTP, "
                f"{cypress} Cypress specs, "
                f"{len(tc.blocking_issues)} blocking")
        if result.test_review:
            tc = result.test_review
            passed = sum(1 for t in tc.test_cases if t.status == "passed")
            table.add_row("Testing (final)", status(tc.passed),
                f"{passed}/{len(tc.test_cases)} passed, {len(tc.blocking_issues)} blocking")

        console.print("\n")
        console.print(table)
        style = "bold green" if result.passed else "bold red"
        text = "✅ PIPELINE PASSED" if result.passed else "❌ PIPELINE FAILED"
        console.print(Panel(
            f"[{style}]{text}[/{style}]\n\n"
            f"Review iterations: {len(result.review_iterations)}\n"
            f"Artifacts: {result.artifacts_dir}\n"
            f"Duration: {result.started_at} → {result.completed_at}",
            title="Result",
        ))
        if result.errors:
            console.print(Panel("\n".join(result.errors), title="[red]Errors[/red]"))
