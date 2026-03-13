"""
Pipeline Orchestrator — coordinates all agents in sequence.

Flow:
  1. IntentAgent          → IntentArtifact
  2. ArchitectureAgent    → ArchitectureArtifact  (+ optional SpecArtifact)
  3. TestingAgent         → TestingArtifact (stage: architecture)  [intent only]
  4. EngineeringAgent     → EngineeringArtifact   (+ optional SpecArtifact)
  5. TestingAgent         → TestingArtifact (stage: engineering)   [intent only]
  6. ReviewAgent          → ReviewArtifact
  7. TestingAgent         → TestingArtifact (stage: review)        [intent only]

Spec-driven development:
  Pass a SpecArtifact to Pipeline.run() to provide technical specs
  (OpenAPI, DB schema, tech constraints) to Architecture and Engineering.
  Testing Agent always derives test cases from IntentArtifact only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agents import (
    ArchitectureAgent,
    EngineeringAgent,
    InfrastructureAgent,
    IntentAgent,
    ReviewAgent,
    TestingAgent,
)
from models.artifacts import (
    ArchitectureArtifact,
    EngineeringArtifact,
    InfrastructureArtifact,
    IntentArtifact,
    ReviewArtifact,
    SpecArtifact,
    TestingArtifact,
)

console = Console()


@dataclass
class PipelineResult:
    requirements: str
    started_at: str
    completed_at: Optional[str] = None
    artifacts_dir: str = "./artifacts"

    intent: Optional[IntentArtifact] = None
    architecture: Optional[ArchitectureArtifact] = None
    engineering: Optional[EngineeringArtifact] = None
    infrastructure: Optional[InfrastructureArtifact] = None
    review: Optional[ReviewArtifact] = None

    test_architecture: Optional[TestingArtifact] = None
    test_infrastructure: Optional[TestingArtifact] = None
    test_review: Optional[TestingArtifact] = None

    errors: list = field(default_factory=list)

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
        self.intent_agent = IntentAgent(artifacts_dir)
        self.architecture_agent = ArchitectureAgent(artifacts_dir)
        self.engineering_agent = EngineeringAgent(artifacts_dir)
        self.infrastructure_agent = InfrastructureAgent(artifacts_dir)
        self.review_agent = ReviewAgent(artifacts_dir)
        self.testing_agent = TestingAgent(artifacts_dir)

    async def run(
        self,
        requirements: str,
        spec: Optional[SpecArtifact] = None,
    ) -> PipelineResult:
        result = PipelineResult(
            requirements=requirements,
            started_at=datetime.now().isoformat(),
            artifacts_dir=self.artifacts_dir,
        )

        spec_note = ""
        if spec:
            spec_parts = []
            if spec.api_spec:
                spec_parts.append("API spec")
            if spec.database_schema:
                spec_parts.append("DB schema")
            if spec.tech_stack_constraints:
                spec_parts.append("tech constraints")
            if spec.architecture_constraints:
                spec_parts.append("architecture constraints")
            spec_parts += list(spec.additional_specs.keys())
            spec_note = f"\nSpecs provided: {', '.join(spec_parts)}" if spec_parts else ""

        console.print(Panel(
            "[bold]🚀 Multi-Agent Pipeline Starting[/bold]\n\n"
            "Intent → Architecture → [Test] → Engineering → Infrastructure → [Live Test] → Review → [Test]"
            + spec_note,
            title="Pipeline",
            style="bold blue",
        ))

        try:
            # Step 1: Intent
            self._step_header("Step 1/8", "Intent Agent", "Analysing requirements")
            result.intent = await self.intent_agent.run(requirements)
            self._step_done("Intent", len(result.intent.requirements), "requirements extracted")

            # Step 2: Architecture (+ optional spec)
            self._step_header("Step 2/8", "Architecture Agent", "Designing system architecture")
            result.architecture = await self.architecture_agent.run(result.intent, spec)
            self._step_done("Architecture", len(result.architecture.components), "components designed")

            # Step 3: Testing — architecture stage (intent only)
            self._step_header("Step 3/8", "Testing Agent", "Verifying architecture vs requirements")
            result.test_architecture = await self.testing_agent.run(
                stage="architecture",
                intent=result.intent,
                architecture=result.architecture,
            )
            self._testing_status("Architecture", result.test_architecture)

            # Step 4: Engineering (+ optional spec)
            self._step_header("Step 4/8", "Engineering Agent", "Selecting stack and generating code")
            result.engineering = await self.engineering_agent.run(
                result.intent, result.architecture, spec
            )
            self._step_done("Engineering", len(result.engineering.generated_files), "files generated")

            # Step 5: Infrastructure — generate IaC, build and start containers
            self._step_header("Step 5/8", "Infrastructure Agent", "Writing IaC and starting containers")
            result.infrastructure = await self.infrastructure_agent.run(
                result.intent, result.architecture, result.engineering
            )
            if result.infrastructure.container_running:
                self._step_done(
                    "Infrastructure",
                    len(result.infrastructure.iac_files),
                    f"IaC files written — service live at {result.infrastructure.base_url}",
                )
            else:
                self._step_done(
                    "Infrastructure",
                    len(result.infrastructure.iac_files),
                    "IaC files written (container not running — live tests will be skipped)",
                )

            # Step 6: Testing — infrastructure stage (live HTTP tests against running container)
            self._step_header("Step 6/8", "Testing Agent", "Running live HTTP tests against container")
            result.test_infrastructure = await self.testing_agent.run(
                stage="infrastructure",
                intent=result.intent,
                architecture=result.architecture,
                engineering=result.engineering,
                infrastructure=result.infrastructure,
            )
            self._testing_status("Infrastructure (live)", result.test_infrastructure)

            # Step 7: Review
            self._step_header("Step 7/8", "Review Agent", "Reviewing quality, security, reliability")
            result.review = await self.review_agent.run(
                result.intent, result.architecture, result.engineering
            )
            self._review_status(result.review)

            # Step 8: Testing — review stage (final verification)
            self._step_header("Step 8/8", "Testing Agent", "Final verification")
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
            # Always stop containers, even if a later step failed
            if result.infrastructure and result.infrastructure.container_running:
                await self.infrastructure_agent.stop_containers()

        result.completed_at = datetime.now().isoformat()
        self._save_report(result)
        return result

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
        console.print(
            f"[{color}]{icon} Testing ({stage}): {passed}/{total} passed, "
            f"{failed} failed, {len(artifact.blocking_issues)} blocking[/{color}]\n"
        )

    def _review_status(self, artifact: ReviewArtifact) -> None:
        icon = "✅" if artifact.passed else "❌"
        color = "green" if artifact.passed else "red"
        critical = sum(1 for i in artifact.issues if i.severity == "critical")
        console.print(
            f"[{color}]{icon} Review: score={artifact.overall_score}/100, "
            f"security={artifact.security_score}, reliability={artifact.reliability_score}, "
            f"critical={critical}, issues={len(artifact.issues)}[/{color}]\n"
        )

    def _save_report(self, result: PipelineResult) -> None:
        report = {
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "passed": result.passed,
            "errors": result.errors,
            "summary": {
                "requirements_count": len(result.intent.requirements) if result.intent else 0,
                "components_count": len(result.architecture.components) if result.architecture else 0,
                "files_generated": len(result.engineering.generated_files) if result.engineering else 0,
                "iac_files_written": len(result.infrastructure.iac_files) if result.infrastructure else 0,
                "container_running": result.infrastructure.container_running if result.infrastructure else False,
                "container_url": result.infrastructure.base_url if result.infrastructure else None,
                "review_score": result.review.overall_score if result.review else None,
                "review_passed": result.review.passed if result.review else None,
                "test_architecture_passed": result.test_architecture.passed if result.test_architecture else None,
                "test_infrastructure_passed": result.test_infrastructure.passed if result.test_infrastructure else None,
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
            table.add_row("Intent", "[green]DONE[/green]",
                f"{len(result.intent.requirements)} reqs, {len(result.intent.key_features)} features")
        if result.architecture:
            table.add_row("Architecture", "[green]DONE[/green]",
                f"{len(result.architecture.components)} components, style: {result.architecture.architecture_style}")
        if result.test_architecture:
            tc = result.test_architecture
            passed = sum(1 for t in tc.test_cases if t.status == "passed")
            table.add_row("Testing (architecture)", status(tc.passed),
                f"{passed}/{len(tc.test_cases)} passed, {len(tc.blocking_issues)} blocking")
        if result.engineering:
            eng = result.engineering
            table.add_row("Engineering", "[green]DONE[/green]",
                f"{len(eng.generated_files)} files, backend: {eng.backend_tech.framework}")
        if result.infrastructure:
            infra = result.infrastructure
            container_status = f"live at {infra.base_url}" if infra.container_running else "not running"
            table.add_row("Infrastructure", "[green]DONE[/green]",
                f"{len(infra.iac_files)} IaC files, container: {container_status}")
        if result.test_infrastructure:
            tc = result.test_infrastructure
            live_total = len(tc.http_test_cases)
            live_passed = sum(1 for t in tc.http_test_cases if t.status == "passed")
            static_passed = sum(1 for t in tc.test_cases if t.status == "passed")
            table.add_row("Testing (infrastructure)", status(tc.passed),
                f"{static_passed}/{len(tc.test_cases)} plan passed, "
                f"{live_passed}/{live_total} live HTTP passed, "
                f"{len(tc.blocking_issues)} blocking")
        if result.review:
            rv = result.review
            critical = sum(1 for i in rv.issues if i.severity == "critical")
            table.add_row("Review", status(rv.passed),
                f"score={rv.overall_score}/100, security={rv.security_score}, "
                f"critical={critical}, total={len(rv.issues)}")
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
            f"Artifacts: {result.artifacts_dir}\n"
            f"Duration: {result.started_at} → {result.completed_at}",
            title="Result",
        ))
        if result.errors:
            console.print(Panel("\n".join(result.errors), title="[red]Errors[/red]"))
