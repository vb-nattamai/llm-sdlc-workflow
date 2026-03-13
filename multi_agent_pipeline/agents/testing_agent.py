"""
Testing Agent — verifies the application at each pipeline stage.

IMPORTANT: The Testing Agent ONLY uses IntentArtifact to derive test cases.
It does NOT receive SpecArtifact — specs are an implementation concern for
Architecture and Engineering; testing must validate against user intent only.

Runs at three stages:
  architecture  — does the design satisfy requirements?
  engineering   — does the implementation match the architecture and requirements?
  review        — final check after review findings
"""

from __future__ import annotations

from typing import Optional

from models.artifacts import (
    ArchitectureArtifact,
    EngineeringArtifact,
    InfrastructureArtifact,
    IntentArtifact,
    ReviewArtifact,
    TestingArtifact,
)
from .base_agent import BaseAgent, load_prompt

SYSTEM_PROMPT = load_prompt("testing_agent.md")


class TestingAgent(BaseAgent):
    def __init__(self, artifacts_dir: str = "./artifacts"):
        super().__init__(name="Testing Agent", artifacts_dir=artifacts_dir)

    async def run(
        self,
        stage: str,
        intent: IntentArtifact,
        architecture: Optional[ArchitectureArtifact] = None,
        engineering: Optional[EngineeringArtifact] = None,
        infrastructure: Optional[InfrastructureArtifact] = None,
        review: Optional[ReviewArtifact] = None,
    ) -> TestingArtifact:
        if stage not in ("architecture", "infrastructure", "review"):
            raise ValueError(f"Invalid stage: {stage!r}")

        # Intent is always the source of truth for test cases
        context = f"## Intent (source of truth for all test cases)\n{self._compact(intent)}"

        if architecture:
            context += f"\n\n## Architecture (what was designed)\n{self._compact(architecture)}"
        if engineering:
            context += f"\n\n## Engineering (what was built)\n{self._compact(engineering)}"
        if infrastructure:
            context += f"\n\n## Infrastructure\n{self._compact(infrastructure)}"
            if infrastructure.base_url:
                context += f"\n\n**Live service URL: {infrastructure.base_url}**"
        if review:
            context += f"\n\n## Review findings\n{self._compact(review)}"

        if stage == "infrastructure":
            base_url = (
                infrastructure.base_url
                if infrastructure and infrastructure.base_url
                else "http://localhost:8000"
            )
            stage_instruction = (
                f"The application is LIVE and running at {base_url}. "
                "Generate http_test_cases with real, executable HTTP requests for every "
                "functional requirement from the Intent. Cover: authentication flows, all "
                "CRUD operations, filtering, pagination, sharing, error handling, and "
                "security checks (e.g. accessing another user's resources). "
                "Also populate test_cases with the full test plan."
            )
        else:
            stage_instruction = {
                "architecture": (
                    "Verify the Architecture satisfies ALL requirements and success criteria "
                    "from the Intent. Flag any requirement the architecture ignores or contradicts."
                ),
                "review": (
                    "Final verification: does the full system — intent + architecture + "
                    "implementation — deliver what was originally requested? "
                    "Are review findings addressed?"
                ),
            }[stage]

        user_message = f"""Perform {stage.upper()} stage testing.

{stage_instruction}

{context}

Test cases must be derived from the Intent's requirements and success criteria.
Respond ONLY with the JSON block."""

        artifact = await self._query_and_parse(
            system=SYSTEM_PROMPT,
            user_message=user_message,
            model_class=TestingArtifact,
        )

        # Infrastructure stage: execute the generated HTTP test cases against the live container
        if (
            stage == "infrastructure"
            and infrastructure
            and infrastructure.container_running
            and infrastructure.base_url
        ):
            await self._run_live_tests(artifact, infrastructure.base_url)

        filename = {
            "architecture": "05a_testing_architecture.json",
            "infrastructure": "05b_testing_infrastructure.json",
            "review": "05c_testing_review.json",
        }[stage]

        self.save_artifact(artifact, filename)
        self.save_history()
        return artifact

    # ─── Live HTTP test execution ────────────────────────────────────────────

    async def _run_live_tests(self, artifact: TestingArtifact, base_url: str) -> None:
        """
        Execute each HttpTestCase against the running container, updating
        status / actual_status / actual_response on each case in-place.
        Also updates artifact.passed and artifact.blocking_issues.
        """
        import httpx
        from rich.console import Console
        con = Console()

        if not artifact.http_test_cases:
            con.print("[yellow]No HTTP test cases generated — skipping live execution.[/yellow]")
            return

        con.print(
            f"[cyan]🧪 Executing {len(artifact.http_test_cases)} live HTTP tests "
            f"against {base_url} …[/cyan]"
        )
        passed_count = 0
        failed_count = 0

        async with httpx.AsyncClient(
            base_url=base_url, timeout=30.0, follow_redirects=True
        ) as client:
            for tc in artifact.http_test_cases:
                try:
                    response = await client.request(
                        method=tc.method.upper(),
                        url=tc.path,
                        headers=tc.headers,
                        json=tc.request_body if tc.request_body else None,
                    )
                    tc.actual_status = response.status_code
                    tc.actual_response = response.text[:1000]

                    status_ok = response.status_code == tc.expected_status
                    body_ok = all(s in response.text for s in tc.response_contains)
                    tc.status = "passed" if (status_ok and body_ok) else "failed"

                    if tc.status == "passed":
                        passed_count += 1
                        con.print(f"  [green]✅ [{tc.id}] {tc.name}[/green]")
                    else:
                        failed_count += 1
                        con.print(
                            f"  [red]❌ [{tc.id}] {tc.name} — "
                            f"expected HTTP {tc.expected_status}, got {tc.actual_status}[/red]"
                        )

                except Exception as e:
                    tc.status = "error"
                    tc.error = str(e)
                    failed_count += 1
                    con.print(f"  [red]💥 [{tc.id}] {tc.name} — {e}[/red]")

        con.print(
            f"[cyan]Live test results: [green]{passed_count} passed[/green], "
            f"[red]{failed_count} failed[/red] "
            f"out of {len(artifact.http_test_cases)} total[/cyan]"
        )

        # Propagate failures into the artifact
        if failed_count > 0:
            artifact.passed = False
            failing = [tc for tc in artifact.http_test_cases if tc.status != "passed"]
            artifact.blocking_issues.extend([
                f"Live test FAILED: [{tc.id}] {tc.name} — "
                f"expected HTTP {tc.expected_status}, got {tc.actual_status or 'error'}"
                for tc in failing
            ])
