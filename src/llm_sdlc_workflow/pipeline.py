"""
Pipeline Orchestrator — coordinates all agents.

Flow:
  1. DiscoveryAgent       → DiscoveryArtifact
  2. ArchitectureAgent    → ArchitectureArtifact
  3. SpecAgent             → GeneratedSpecArtifact (forward contract: OpenAPI + DDL)
  4. TestingAgent         → TestingArtifact (stage: architecture+spec)
  5. EngineeringAgent  ┐
     InfrastructureAgent ┘  ← run in PARALLEL (asyncio.gather)  [infra plan only]
  6. ReviewAgent          → ReviewArtifact (loop up to MAX_REVIEW_ITERATIONS)
     ↳ if not passed → EngineeringAgent.apply_review_feedback
                      + InfrastructureAgent.apply_review_feedback (parallel)
     ↳ repeat until passed or max iterations reached
     ↳ raises PipelineHaltError if still failing after max iterations
  7. InfrastructureAgent  → InfrastructureArtifact (infra apply: start containers)
  7b. TestingAgent        → TestingArtifact (stage: infrastructure)
      — live HTTP tests against running container
      — Cypress spec generation + optional run
      — retry loop (max 2) for failed_services
  8. TestingAgent         → TestingArtifact (stage: review)  ← final sign-off
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from llm_sdlc_workflow.agents import (
    ArchitectureAgent,
    DeploymentAgent,
    DiscoveryAgent,
    EngineeringAgent,
    InfrastructureAgent,
    ReviewAgent,
    SpecAgent,
    TestingAgent,
)
from llm_sdlc_workflow.config import PipelineConfig
from llm_sdlc_workflow.models.artifacts import (
    ArchitectureArtifact,
    DeploymentArtifact,
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
MAX_ARCH_ITERATIONS = 3      # max architecture re-design iterations before giving up
MAX_INFRA_TEST_RETRIES = 2   # max re-runs of failed services after Stage 2 testing


class PipelineHaltError(Exception):
    """Raised when the pipeline cannot continue due to unresolved failures."""


class HumanDecision(str, Enum):
    """Decision returned by _await_human checkpoints.

    CONTINUE   — proceed to the next pipeline stage (default / Enter)
    FORCE_LOOP — human wants another loop iteration even if the check passed (r)
    STOP_LOOP  — human wants to exit the loop early even if still failing  (f)
    ABORT      — stop the entire pipeline immediately                       (a)
    """
    CONTINUE   = "continue"
    FORCE_LOOP = "force_loop"
    STOP_LOOP  = "stop_loop"
    ABORT      = "abort"


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
    infra_plan: Optional[InfrastructureArtifact] = None    # Step 5 — IaC plan (no containers)
    infra_apply: Optional[InfrastructureArtifact] = None   # Step 7 — containers started
    review_iterations: List[ReviewArtifact] = field(default_factory=list)

    test_architecture: Optional[TestingArtifact] = None
    test_infrastructure: Optional[TestingArtifact] = None
    test_review: Optional[TestingArtifact] = None
    deployment: Optional[DeploymentArtifact] = None

    errors: list = field(default_factory=list)

    @property
    def review(self) -> Optional[ReviewArtifact]:
        return self.review_iterations[-1] if self.review_iterations else None

    @property
    def infrastructure(self) -> Optional[InfrastructureArtifact]:
        """Most recent infra artifact — apply phase if available, else plan."""
        return self.infra_apply or self.infra_plan

    @property
    def passed(self) -> bool:
        return all([
            self.test_architecture and self.test_architecture.passed,
            self.test_infrastructure and self.test_infrastructure.passed,
            self.test_review and self.test_review.passed,
            self.review and self.review.passed,
        ])


class Pipeline:
    def __init__(
        self,
        artifacts_dir: str = "./artifacts",
        human_checkpoints: bool = True,
        project_name: str = "generated",
        config: Optional[PipelineConfig] = None,
    ):
        self.artifacts_dir = artifacts_dir
        self.human_checkpoints = human_checkpoints
        self.project_name = project_name
        self.config = config or PipelineConfig()
        os.makedirs(artifacts_dir, exist_ok=True)
        self.discovery_agent = DiscoveryAgent(artifacts_dir)
        self.architecture_agent = ArchitectureAgent(artifacts_dir)
        self.spec_agent = SpecAgent(artifacts_dir, generated_dir_name=project_name)
        self.engineering_agent = EngineeringAgent(
            artifacts_dir, generated_dir_name=project_name, config=self.config
        )
        self.infrastructure_agent = InfrastructureAgent(artifacts_dir, generated_dir_name=project_name)
        self.deployment_agent = DeploymentAgent(artifacts_dir, generated_dir_name=project_name)
        self.review_agent = ReviewAgent(artifacts_dir)
        self.testing_agent = TestingAgent(artifacts_dir, generated_dir_name=project_name)

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
            "[bold]🚀 LLM SDLC Workflow Starting[/bold]\n\n"
            "Discovery → Architecture → [Test] → Spec → "
            "[Engineering ‖ Infrastructure] → "
            "Review loop (max " + str(MAX_REVIEW_ITERATIONS) + ") → "
            "[Containers ‖ Deployment CI/CD] → [Live Test + Cypress] → [Final Test]\n\n"
            f"[dim]{self.config.summary()}[/dim]",
            title="Pipeline",
            style="bold blue",
        ))

        try:
            # ── Step 1: Discovery ──────────────────────────────────────────────
            self._step_header("Step 1", "Discovery Agent", "Analysing requirements, goals, constraints and risks")
            result.intent = await self.discovery_agent.run(requirements)
            self._step_done("Discovery", len(result.intent.requirements), "requirements extracted")
            await self._await_human(
                checkpoint="Checkpoint 1 — Requirements Validated",
                details=[
                    f"Requirements extracted : {len(result.intent.requirements)}",
                    f"Goals identified       : {len(result.intent.user_goals)}",
                    f"Constraints            : {len(result.intent.constraints)}",
                    f"Risks surfaced         : {len(result.intent.risks)}",
                    f"Scope                  : {result.intent.scope[:120]}{'...' if len(result.intent.scope) > 120 else ''}",
                    "",
                    "Top requirements:",
                    *[f"  · {r[:100]}" for r in result.intent.requirements[:4]],
                ],
                artifact_path=os.path.join(self.artifacts_dir, "01_discovery_artifact.json"),
                edit_hint="If requirements were misunderstood, update your requirements file and restart.",
            )
            # ── Step 2: Architecture fix loop ──────────────────────────────────
            # Runs Architecture Agent → Testing Stage 1 repeatedly until the
            # architecture is clean (no blocking issues) or MAX_ARCH_ITERATIONS hit.
            # Human can force another iteration (r) or stop the loop early (f).
            _arch_test_feedback: Optional[TestingArtifact] = None
            for _arch_iter in range(1, MAX_ARCH_ITERATIONS + 1):
                _redesign_sfx = (
                    f" (re-design {_arch_iter}/{MAX_ARCH_ITERATIONS})"
                    if _arch_iter > 1 else ""
                )
                if _arch_test_feedback is None:
                    self._step_header(
                        f"Step 2{_redesign_sfx}", "Architecture Agent",
                        "Designing system architecture",
                    )
                    result.architecture = await self.architecture_agent.run(result.intent, spec)
                else:
                    self._step_header(
                        f"Step 2{_redesign_sfx}", "Architecture Agent",
                        f"Re-designing architecture — {len(_arch_test_feedback.blocking_issues)} blocker(s) to fix",
                    )
                    result.architecture = await self.architecture_agent.apply_test_feedback(
                        result.intent, result.architecture, _arch_test_feedback, spec
                    )
                self._step_done(
                    "Architecture", len(result.architecture.components), "components designed"
                )

                self._step_header(
                    f"Testing [Stage 1, iter {_arch_iter}]", "Testing Agent",
                    "Verifying architecture satisfies all requirements",
                )
                result.test_architecture = await self.testing_agent.run(
                    stage="architecture",
                    intent=result.intent,
                    architecture=result.architecture,
                )
                self._testing_status(f"Architecture Stage 1 (iter {_arch_iter})", result.test_architecture)

                _arch_blockers = result.test_architecture.blocking_issues
                if result.test_architecture.passed:
                    _decision = await self._await_human(
                        checkpoint=f"✅ Architecture Validated — iteration {_arch_iter}",
                        details=[
                            f"Components  : {len(result.architecture.components)}",
                            f"Style       : {result.architecture.architecture_style}",
                            f"Test cases  : {len(result.test_architecture.test_cases)} — all passing",
                            f"Coverage    : {', '.join(result.test_architecture.coverage_areas[:5]) or 'n/a'}",
                            "",
                            "↵ Enter — continue to spec generation",
                            "r — force another architecture review iteration",
                        ],
                        artifact_path=os.path.join(self.artifacts_dir, "05a_testing_architecture.json"),
                        loop_controls=True,
                    )
                    if _decision == HumanDecision.FORCE_LOOP and _arch_iter < MAX_ARCH_ITERATIONS:
                        console.print(
                            "[yellow]🔄 Human requested additional architecture iteration…[/yellow]\n"
                        )
                        _arch_test_feedback = None
                        continue
                    break  # architecture clean — exit loop
                else:
                    _decision = await self._await_human(
                        checkpoint=(
                            f"❌ Architecture Testing Failed"
                            f" — iteration {_arch_iter}/{MAX_ARCH_ITERATIONS}"
                        ),
                        details=[
                            f"Blockers    : {len(_arch_blockers)}",
                            *[f"  ⛔ {b[:100]}" for b in _arch_blockers[:5]],
                            "",
                            "↵ Enter — auto re-design and re-test",
                            "f — stop loop and continue with current architecture",
                            "a — abort pipeline",
                        ],
                        artifact_path=os.path.join(self.artifacts_dir, "05a_testing_architecture.json"),
                        loop_controls=True,
                    )
                    if _decision == HumanDecision.STOP_LOOP:
                        console.print(
                            "[yellow]⏩ Human stopped architecture fix loop — "
                            "continuing with current architecture.[/yellow]\n"
                        )
                        break
                    if _arch_iter < MAX_ARCH_ITERATIONS:
                        console.print(
                            f"[yellow]🔄 Architecture blockers found — re-designing "
                            f"(iteration {_arch_iter + 1}/{MAX_ARCH_ITERATIONS})…[/yellow]\n"
                        )
                        _arch_test_feedback = result.test_architecture
                    else:
                        console.print(
                            f"[red]⚠  Max architecture iterations ({MAX_ARCH_ITERATIONS}) reached. "
                            "Continuing with best effort.[/red]\n"
                        )

            # ── Step 3: Spec Agent — forward contract ───────────────────────
            # Runs after architecture is locked in by the fix loop above.
            self._step_header("Step 3", "Spec Agent", "Generating forward contract (OpenAPI + DDL)")
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

            _spec_dir = os.path.join(self.artifacts_dir, self.project_name, "specs")
            _openapi_lines = len((result.generated_spec.openapi_spec or "").splitlines())
            _schema_lines  = len((result.generated_spec.database_schema or "").splitlines())
            _shared = ", ".join(result.generated_spec.shared_models[:6]) or "none"
            await self._await_human(
                checkpoint="Checkpoint 2 — Architecture & API Contract Approved  [MOST CRITICAL]",
                details=[
                    f"Architecture style : {result.architecture.architecture_style}",
                    f"Components         : {len(result.architecture.components)}",
                    f"Services           : {', '.join(result.generated_spec.monorepo_services)}",
                    f"Ports              : {ports}",
                    f"OpenAPI spec       : {_openapi_lines} lines  →  {_spec_dir}/openapi.yaml",
                    f"SQL schema         : {_schema_lines} lines  →  {_spec_dir}/schema.sql",
                    f"Shared models      : {_shared}",
                ],
                artifact_path=os.path.join(self.artifacts_dir, "04_generated_spec_artifact.json"),
                edit_hint=(
                    "This is the public contract. Edit openapi.yaml + schema.sql freely.\n"
                    "  Engineering will implement exactly what is in those files.\n"
                    "  Once downstream teams depend on these paths, changes are expensive."
                ),
            )

            # ── Step 5: Engineering + Infrastructure plan in PARALLEL ───────
            self._step_header(
                "Step 5", "Engineering + Infrastructure",
                "Generating code and IaC in parallel (Kotlin/React + Docker)"
            )
            result.engineering, result.infra_plan = await asyncio.gather(
                self.engineering_agent.run(result.intent, result.architecture, result.generated_spec),
                self.infrastructure_agent.run(
                    result.intent, result.architecture,
                    EngineeringArtifact(),
                    skip_start=True,
                ),
            )
            self._step_done("Engineering", len(result.engineering.generated_files), "files generated")
            self._step_done(
                "Infrastructure (plan)", len(result.infra_plan.iac_files),
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
                    infrastructure=result.infra_plan,
                    iteration=iteration,
                    previous_feedback=previous_feedback,
                )
                result.review_iterations.append(review)
                self._review_status(review)

                if review.passed:
                    console.print(
                        f"[bold green]✅ Review passed on iteration {iteration}![/bold green]\n"
                    )
                    _rdecision = await self._await_human(
                        checkpoint=f"✅ Review Passed — iteration {iteration}",
                        details=[
                            f"Score       : {review.overall_score}/100",
                            f"Critical    : {len(review.critical_issues)} (none)",
                            f"High        : {len(review.high_issues)}",
                            f"Total issues: {len(review.issues)}",
                            "",
                            "↵ Enter — continue to infrastructure",
                            "r — force another review iteration",
                        ],
                        artifact_path=os.path.join(
                            self.artifacts_dir, f"05_review_artifact_iter{iteration}.json"
                        ),
                        loop_controls=True,
                    )
                    if _rdecision == HumanDecision.FORCE_LOOP and iteration < MAX_REVIEW_ITERATIONS:
                        console.print(
                            "[yellow]🔄 Human requested additional review iteration…[/yellow]\n"
                        )
                        previous_feedback = review
                        continue
                    break

                if iteration < MAX_REVIEW_ITERATIONS:
                    _rdecision = await self._await_human(
                        checkpoint=(
                            f"❌ Review Failed — iteration {iteration}/{MAX_REVIEW_ITERATIONS}"
                        ),
                        details=[
                            f"Score       : {review.overall_score}/100",
                            f"Critical    : {len(review.critical_issues)}",
                            *[f"  ⛔ {i[:100]}" for i in review.critical_issues[:4]],
                            f"High        : {len(review.high_issues)}",
                            "",
                            "↵ Enter — apply feedback and re-generate automatically",
                            "f — stop review loop and continue with current code",
                            "a — abort pipeline",
                        ],
                        artifact_path=os.path.join(
                            self.artifacts_dir, f"05_review_artifact_iter{iteration}.json"
                        ),
                        loop_controls=True,
                    )
                    if _rdecision == HumanDecision.STOP_LOOP:
                        console.print(
                            "[yellow]⏩ Human stopped review loop — "
                            "continuing with current code.[/yellow]\n"
                        )
                        break
                    console.print(
                        f"[yellow]🔄 Review failed — applying feedback and re-generating "
                        f"(iteration {iteration + 1}/{MAX_REVIEW_ITERATIONS})…[/yellow]"
                    )
                    # Apply feedback to both agents in parallel
                    result.engineering, result.infra_plan = await asyncio.gather(
                        self.engineering_agent.apply_review_feedback(
                            result.intent, result.architecture,
                            result.engineering, review, result.generated_spec
                        ),
                        self.infrastructure_agent.apply_review_feedback(
                            result.intent, result.architecture,
                            result.engineering, result.infra_plan, review
                        ),
                    )
                    previous_feedback = review
                else:
                    console.print(
                        f"[red]⚠ Max review iterations ({MAX_REVIEW_ITERATIONS}) reached. "
                        "Continuing with best effort.[/red]\n"
                    )

            # Halt if review still failing after max iterations
            if result.review and not result.review.passed:
                crit = result.review.critical_issues
                raise PipelineHaltError(
                    f"Review failed after {MAX_REVIEW_ITERATIONS} iteration(s). "
                    f"Unresolved critical issues: {crit or '[none flagged]'}"
                )

            if result.review:
                _crit = result.review.critical_issues
                _high = result.review.high_issues
                _review_status = "✅ Passed" if result.review.passed else "⚠️  Did not fully pass"
                await self._await_human(
                    checkpoint="Checkpoint 4 — Security & Quality Review",
                    details=[
                        f"Review score     : {result.review.overall_score}/100",
                        f"Critical issues  : {len(_crit)}",
                        f"High issues      : {len(_high)}",
                        f"Status           : {_review_status}",
                        *(["", "Critical issues:", *[f"  ⚠ {i[:100]}" for i in _crit[:4]]] if _crit else []),
                    ],
                    artifact_path=os.path.join(self.artifacts_dir, "05_review_artifact.json"),
                    edit_hint=(
                        "Abort here and add org-specific security constraints via "
                        "--arch-constraints, then re-run with --from-run."
                    ) if _crit else None,
                )

            # ── Step 7: Start containers + generate CI/CD package (parallel) ──
            self._step_header(
                "Step 7", "Infrastructure + Deployment Agent",
                "Building containers and generating CI/CD + K8s/Helm package in parallel"
            )
            result.infra_apply, result.deployment = await asyncio.gather(
                self.infrastructure_agent.run(
                    intent=result.intent,
                    architecture=result.architecture,
                    engineering=result.engineering,
                ),
                self.deployment_agent.run(
                    intent=result.intent,
                    architecture=result.architecture,
                    engineering=result.engineering,
                    contract=result.generated_spec,
                    iteration=result.engineering.review_iteration,
                ),
            )
            if result.infra_apply.container_running:
                self._step_done(
                    "Infrastructure (apply)",
                    len(result.infra_apply.iac_files),
                    f"service live at {result.infra_apply.base_url}",
                )
            else:
                self._step_done(
                    "Infrastructure (apply)",
                    len(result.infra_apply.iac_files),
                    "IaC files written (container not running — live tests skipped)",
                )
            self._step_done(
                "Deployment",
                len(result.deployment.deployment_files),
                f"CI/CD + K8s/Helm files ({result.deployment.deployment_strategy} strategy)",
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
                infrastructure=result.infra_apply,
            )
            self._testing_status("Infrastructure (live + Cypress)", result.test_infrastructure)

            # ── Stage-2 retry loop for failed services ───────────────────────
            # Human can inspect the initial Stage-2 result before any retry begins.
            _infra_force_retry = False  # True → enter retry even when initial test passed
            _infra_stopped = False       # True → human pressed f to exit the loop early

            _init_blockers = result.test_infrastructure.blocking_issues
            _init_failed   = result.test_infrastructure.failed_services
            if result.test_infrastructure.passed:
                _idecision = await self._await_human(
                    checkpoint="✅ Infrastructure Tests Passed (Stage 2)",
                    details=[
                        f"HTTP passed : {sum(1 for t in result.test_infrastructure.http_test_cases if t.status == 'passed')}/{len(result.test_infrastructure.http_test_cases)}",
                        f"Cypress     : {len(result.test_infrastructure.cypress_spec_files)} spec(s)",
                        "Blockers    : 0",
                        "",
                        "↵ Enter — continue to final testing",
                        "r — force a service re-run",
                    ],
                    artifact_path=os.path.join(self.artifacts_dir, "07b_testing_infra.json"),
                    loop_controls=True,
                )
                if _idecision == HumanDecision.FORCE_LOOP:
                    console.print(
                        "[yellow]🔄 Human requested infrastructure service re-run…[/yellow]\n"
                    )
                    _infra_force_retry = True
            else:
                _idecision = await self._await_human(
                    checkpoint="❌ Infrastructure Tests Failed (Stage 2)",
                    details=[
                        f"Failed svcs : {', '.join(_init_failed) or 'n/a'}",
                        f"Blockers    : {len(_init_blockers)}",
                        *[f"  ⛔ {b[:100]}" for b in _init_blockers[:5]],
                        "",
                        "↵ Enter — auto-retry failed services",
                        "f — stop retry loop and continue with current state",
                        "a — abort pipeline",
                    ],
                    artifact_path=os.path.join(self.artifacts_dir, "07b_testing_infra.json"),
                    loop_controls=True,
                )
                if _idecision == HumanDecision.STOP_LOOP:
                    console.print(
                        "[yellow]⏩ Human stopped infra retry loop — "
                        "continuing with current state.[/yellow]\n"
                    )
                    _infra_stopped = True

            for _retry in range(1, MAX_INFRA_TEST_RETRIES + 1):
                if _infra_stopped:
                    break
                if result.test_infrastructure.passed and not _infra_force_retry:
                    break
                _was_forced = _infra_force_retry
                _infra_force_retry = False  # consume one-shot flag
                failed_svcs = result.test_infrastructure.failed_services
                if not failed_svcs and not _was_forced:
                    break   # no specific services to target — don't retry blindly
                console.print(
                    f"[yellow]🔄 Stage-2 retry {_retry}/{MAX_INFRA_TEST_RETRIES} — "
                    f"re-generating failed services: {failed_svcs}…[/yellow]"
                )
                result.engineering = await self.engineering_agent.run(
                    result.intent, result.architecture, result.generated_spec,
                    iteration=result.engineering.review_iteration + 1,
                )
                result.infra_apply = await self.infrastructure_agent.run(
                    intent=result.intent,
                    architecture=result.architecture,
                    engineering=result.engineering,
                )
                result.test_infrastructure = await self.testing_agent.run(
                    stage="infrastructure",
                    intent=result.intent,
                    architecture=result.architecture,
                    engineering=result.engineering,
                    infrastructure=result.infra_apply,
                )
                self._testing_status(
                    f"Infrastructure retry {_retry} (live + Cypress)",
                    result.test_infrastructure,
                )
                # Human checkpoint after each retry result
                _retry_blockers = result.test_infrastructure.blocking_issues
                _retry_failed   = result.test_infrastructure.failed_services
                if result.test_infrastructure.passed:
                    _idecision = await self._await_human(
                        checkpoint=f"✅ Infrastructure Tests Passed (retry {_retry})",
                        details=[
                            f"HTTP passed : {sum(1 for t in result.test_infrastructure.http_test_cases if t.status == 'passed')}/{len(result.test_infrastructure.http_test_cases)}",
                            f"Cypress     : {len(result.test_infrastructure.cypress_spec_files)} spec(s)",
                            "",
                            "↵ Enter — continue to final testing",
                            "r — force another service re-run",
                        ],
                        artifact_path=os.path.join(
                            self.artifacts_dir, f"07b_testing_infra_retry{_retry}.json"
                        ),
                        loop_controls=True,
                    )
                    if _idecision == HumanDecision.FORCE_LOOP and _retry < MAX_INFRA_TEST_RETRIES:
                        console.print(
                            "[yellow]🔄 Human requested another infrastructure re-run…[/yellow]\n"
                        )
                        _infra_force_retry = True
                        continue
                    break  # tests clean — exit loop
                else:
                    _idecision = await self._await_human(
                        checkpoint=(
                            f"❌ Infrastructure Tests Still Failing"
                            f" (retry {_retry}/{MAX_INFRA_TEST_RETRIES})"
                        ),
                        details=[
                            f"Failed svcs : {', '.join(_retry_failed) or 'n/a'}",
                            f"Blockers    : {len(_retry_blockers)}",
                            *[f"  ⛔ {b[:100]}" for b in _retry_blockers[:5]],
                            "",
                            *(["↵ Enter — retry again"] if _retry < MAX_INFRA_TEST_RETRIES
                              else ["↵ Enter — continue with failures (best effort)"]),
                            "f — stop retry loop and continue with current state",
                            "a — abort pipeline",
                        ],
                        artifact_path=os.path.join(
                            self.artifacts_dir, f"07b_testing_infra_retry{_retry}.json"
                        ),
                        loop_controls=True,
                    )
                    if _idecision == HumanDecision.STOP_LOOP:
                        console.print(
                            "[yellow]⏩ Human stopped infra retry loop — "
                            "continuing with current state.[/yellow]\n"
                        )
                        _infra_stopped = True
                        break
                    if _retry < MAX_INFRA_TEST_RETRIES:
                        console.print(
                            f"[yellow]🔄 Infrastructure failures remain — retrying "
                            f"({_retry + 1}/{MAX_INFRA_TEST_RETRIES})…[/yellow]\n"
                        )
                    else:
                        console.print(
                            f"[red]⚠  Max infra retries ({MAX_INFRA_TEST_RETRIES}) reached. "
                            "Continuing with best effort.[/red]\n"
                        )
            else:
                if not result.test_infrastructure.passed and not _infra_stopped:
                    raise PipelineHaltError(
                        f"Infrastructure tests still failing after {MAX_INFRA_TEST_RETRIES} "
                        f"retries. Blocking: {result.test_infrastructure.blocking_issues}"
                    )

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

    async def _await_human(
        self,
        checkpoint: str,
        details: list,
        artifact_path: str,
        edit_hint: Optional[str] = None,
        loop_controls: bool = False,
    ) -> HumanDecision:
        """Pause the pipeline and wait for human review.

        Returns a HumanDecision so callers can act on the human's choice:
          CONTINUE   — proceed normally (Enter or s)
          FORCE_LOOP — human wants another loop iteration even if passing (r)
          STOP_LOOP  — human wants to exit the current loop early (f)
          ABORT      — stop the pipeline immediately (a)

        Skipped automatically (returns CONTINUE) when:
          - human_checkpoints=False  (--auto flag)
          - stdin is not a TTY      (CI/CD / piped input)

        loop_controls=True adds the r / f options for use inside retry loops.
        """
        if not self.human_checkpoints or not sys.stdin.isatty():
            return HumanDecision.CONTINUE

        body = "\n".join(f"  {d}" for d in details)
        hint_block = (
            f"\n\n  [dim]💡 {edit_hint.replace(chr(10), chr(10) + '  ')}[/dim]"
            if edit_hint else ""
        )
        if loop_controls:
            controls = (
                f"  [bold]↵ Enter[/bold] — proceed    "
                f"[bold]r[/bold] — force re-run    "
                f"[bold]f[/bold] — finish/stop loop    "
                f"[bold]a[/bold] — abort pipeline"
            )
        else:
            controls = (
                f"  [bold]↵ Enter[/bold] — proceed    "
                f"[bold]s[/bold] — skip checkpoint    "
                f"[bold]a[/bold] — abort pipeline"
            )
        console.print(Panel(
            f"[bold yellow]⏸  Pipeline paused — human review required[/bold yellow]\n\n"
            f"{body}"
            f"{hint_block}\n\n"
            f"  [dim]Artifact → {artifact_path}[/dim]\n\n"
            f"{controls}",
            title=f"[bold yellow]🔍 {checkpoint}[/bold yellow]",
            border_style="yellow",
        ))

        try:
            response = await asyncio.to_thread(input, "  ▶ ")
            response = response.strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[red]⛔ Pipeline aborted.[/red]")
            raise SystemExit(0)

        if response in ("a", "abort"):
            console.print("[red]⛔ Pipeline aborted by user at checkpoint.[/red]")
            raise SystemExit(0)
        elif response in ("r", "rerun", "re-run") and loop_controls:
            console.print("[yellow]  🔄 Forcing another loop iteration…[/yellow]\n")
            return HumanDecision.FORCE_LOOP
        elif response in ("f", "finish", "stop") and loop_controls:
            console.print("[yellow]  ⏩ Stopping loop — continuing with current state…[/yellow]\n")
            return HumanDecision.STOP_LOOP
        elif response in ("s", "skip") and not loop_controls:
            console.print("[dim]  ↩ Checkpoint skipped.[/dim]\n")
            return HumanDecision.CONTINUE
        else:
            console.print("[green]  ▶ Continuing pipeline…[/green]\n")
            return HumanDecision.CONTINUE

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
            "project_name": self.project_name,
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
                "deployment_files": len(result.deployment.deployment_files) if result.deployment else 0,
                "deployment_strategy": result.deployment.deployment_strategy if result.deployment else None,
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
        if result.deployment:
            dep = result.deployment
            table.add_row(
                "Deployment (CI/CD + K8s + Helm)", "[green]DONE[/green]",
                f"{len(dep.deployment_files)} files, "
                f"strategy: {dep.deployment_strategy}, "
                f"services: {', '.join(dep.services_deployed)}"
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
