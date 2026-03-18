"""
Testing Agent — verifies the application at each pipeline stage.

IMPORTANT: The Testing Agent ONLY uses IntentArtifact to derive test cases.
It does NOT receive SpecArtifact — specs are an implementation concern for
Architecture and Engineering; testing must validate against user intent only.

Runs at three stages:
  architecture  — does the design satisfy requirements?
  infrastructure — live HTTP tests + Cypress e2e spec generation + optional run
  review        — final check after review/fix iterations
"""

from __future__ import annotations

import os
import shutil
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
    def __init__(self, artifacts_dir: str = "./artifacts", generated_dir_name: str = "generated"):
        super().__init__(name="Testing Agent", artifacts_dir=artifacts_dir, generated_dir_name=generated_dir_name)

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
                else "http://localhost:8080"
            )
            stage_instruction = (
                f"The application is LIVE and running at {base_url}. "
                "Generate http_test_cases with real, executable HTTP requests for every "
                "functional requirement from the Intent. "
                "Also generate cypress_spec_files (TypeScript .cy.ts) covering every user journey. "
                "cypress_spec_files baseUrl should match: " + base_url
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
Respond ONLY with the JSON object."""

        artifact = await self._query_and_parse(
            system=SYSTEM_PROMPT,
            user_message=user_message,
            model_class=TestingArtifact,
        )

        # Infrastructure stage: execute live HTTP tests + write/run Cypress specs
        if stage == "infrastructure":
            if infrastructure and infrastructure.container_running and infrastructure.base_url:
                await self._run_live_tests(artifact, infrastructure.base_url)
            self._write_cypress_specs(artifact)
            await self._run_cypress(artifact)

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

        if failed_count > 0:
            artifact.passed = False
            failing = [tc for tc in artifact.http_test_cases if tc.status != "passed"]
            artifact.blocking_issues.extend([
                f"Live test FAILED: [{tc.id}] {tc.name} — "
                f"expected HTTP {tc.expected_status}, got {tc.actual_status or 'error'}"
                for tc in failing
            ])

    # ─── Cypress spec file writing ───────────────────────────────────────────

    def _write_cypress_specs(self, artifact: TestingArtifact) -> None:
        from rich.console import Console
        con = Console()

        if not artifact.cypress_spec_files:
            return

        cypress_root = os.path.join(self.artifacts_dir, "generated", "cypress")
        os.makedirs(cypress_root, exist_ok=True)

        # Write a cypress.config.ts at the generated root if not present
        config_path = os.path.join(self.artifacts_dir, "generated", "cypress.config.ts")
        if not os.path.exists(config_path):
            with open(config_path, "w") as f:
                f.write(
                    'import { defineConfig } from "cypress";\n\n'
                    "export default defineConfig({\n"
                    '  e2e: { baseUrl: "http://localhost:8080", supportFile: false },\n'
                    "});\n"
                )

        for spec in artifact.cypress_spec_files:
            safe_path = os.path.normpath(spec.path).lstrip(os.sep)
            full_path = os.path.join(self.artifacts_dir, "generated", safe_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as f:
                f.write(spec.content)
            con.print(f"[dim]  🌲 Cypress spec: {full_path}[/dim]")

    # ─── Optional Cypress run ────────────────────────────────────────────────

    async def _run_cypress(self, artifact: TestingArtifact) -> None:
        """Run `npx cypress run` if Cypress is available. Non-blocking — failures logged only."""
        from rich.console import Console
        import asyncio
        con = Console()

        if not artifact.cypress_spec_files:
            return

        cypress_binary = shutil.which("cypress") or shutil.which("npx")
        if not cypress_binary:
            con.print("[dim]Cypress / npx not found — skipping Cypress run.[/dim]")
            return

        generated_dir = os.path.join(self.artifacts_dir, self.generated_dir_name)
        config_file = os.path.join(generated_dir, "cypress.config.ts")
        if not os.path.exists(config_file):
            con.print("[dim]No cypress.config.ts — skipping Cypress run.[/dim]")
            return

        # Check if node_modules/cypress is installed
        cypress_bin = os.path.join(generated_dir, "node_modules", ".bin", "cypress")
        if not os.path.exists(cypress_bin):
            con.print(f"[dim]Cypress not installed in {self.generated_dir_name}/ — skipping run. "
                      f"Run `npm install cypress` in artifacts/{self.generated_dir_name}/ to enable.[/dim]")
            return

        con.print("[cyan]🌲 Running Cypress e2e tests…[/cyan]")
        try:
            proc = await asyncio.create_subprocess_exec(
                cypress_bin, "run", "--headless",
                cwd=generated_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            except asyncio.TimeoutError:
                proc.kill()
                con.print("[yellow]Cypress timed out after 5 minutes.[/yellow]")
                return

            output = (stdout or b"").decode(errors="replace")
            if proc.returncode == 0:
                con.print("[green]✅ Cypress tests passed.[/green]")
            else:
                con.print(f"[red]❌ Cypress tests failed (exit {proc.returncode}).[/red]")
                con.print(f"[dim]{output[-2000:]}[/dim]")
                artifact.blocking_issues.append(
                    f"Cypress e2e tests failed (exit {proc.returncode})"
                )
                artifact.passed = False
        except Exception as e:
            con.print(f"[yellow]Cypress run error: {e}[/yellow]")
