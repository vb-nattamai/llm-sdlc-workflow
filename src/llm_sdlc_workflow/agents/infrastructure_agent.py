"""
Infrastructure Agent — generates IaC to containerise the application, then builds
and starts the Docker stack so the Testing Agent can run live HTTP tests against it.

Responsibilities:
  - Generate Dockerfile, docker-compose.yml, and .env.example for the generated app
  - Write those files into the artifacts/generated/ directory
  - Build and start the container stack with `docker compose up --build`
  - Poll the health-check endpoint to confirm the service is ready
  - Expose base_url and container_running on the artifact for downstream consumers
  - Tear down containers when the pipeline is done via stop_containers()
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

from rich.console import Console

from llm_sdlc_workflow.models.artifacts import (
    ArchitectureArtifact,
    EngineeringArtifact,
    InfrastructureArtifact,
    DiscoveryArtifact,
    ReviewFeedback,
)
from .base_agent import BaseAgent, load_prompt

SYSTEM_PROMPT = load_prompt("infrastructure_agent.md")

console = Console()


class InfrastructureAgent(BaseAgent):
    def __init__(self, artifacts_dir: str = "./artifacts", generated_dir_name: str = "generated"):
        super().__init__(name="Infrastructure Agent", artifacts_dir=artifacts_dir, generated_dir_name=generated_dir_name)

    async def run(
        self,
        intent: DiscoveryArtifact,
        architecture: ArchitectureArtifact,
        engineering: EngineeringArtifact,
        review_feedback: Optional[ReviewFeedback] = None,
        iteration: int = 1,
        skip_start: bool = False,
    ) -> InfrastructureArtifact:
        """
        Generate IaC via chunked LLM calls, write files, start containers,
        and wait for the service to be healthy.
        """
        feedback_section = ""
        if review_feedback:
            lines = [
                f"\n\n## Review Feedback (iteration {review_feedback.iteration}) — MUST be addressed"
            ]
            if review_feedback.critical_issues:
                lines.append("### CRITICAL:")
                lines.extend(f"- {i}" for i in review_feedback.critical_issues)
            if review_feedback.high_issues:
                lines.append("### HIGH:")
                lines.extend(f"- {i}" for i in review_feedback.high_issues)
            feedback_section = "\n".join(lines)

        plan_message = f"""Generate Infrastructure as Code to containerise this application.

## Discovery Summary
{self._compact(intent)}

## Architecture Summary
{self._compact(architecture)}

## Engineering Summary (stack already generated)
{self._compact(engineering)}
{feedback_section}

The generated application files already exist in the working directory.
Produce Dockerfiles and docker-compose.yml so the full stack starts with:
  docker compose up --build

Return JSON with iac_files where every file's content is set to \"__PENDING__\".
This is a json response."""

        fill_message_tmpl = (
            "Write the COMPLETE content for the IaC file at path: {path}\n"
            "Purpose: {purpose}\n\n"
            "## Context\n"
            "Backend: Kotlin/Java Spring Boot 3 (Gradle) | Frontend: React 18 + Vite (Node)\n"
            "Architecture: {arch_style}\n\n"
            "Return JSON: {{\"content\": \"<full file text>\"}}\n"
            "No truncation, no placeholders. Valid json response."
        )

        artifact = await self._query_and_parse_chunked(
            system=SYSTEM_PROMPT,
            plan_message=plan_message,
            file_keys=["iac_files"],
            model_class=InfrastructureArtifact,
            fill_message_tmpl=fill_message_tmpl,
            fill_context={
                "arch_style": getattr(architecture, "architecture_style", "microservices"),
            },
        )

        artifact.review_iteration = iteration
        if review_feedback:
            artifact.review_feedback_applied = (
                list(review_feedback.critical_issues) + list(review_feedback.high_issues)
            )

        # Tag the artifact with its deployment phase (Fix 4)
        artifact.phase = "plan" if skip_start else "apply"

        # Write IaC files alongside the generated source code
        generated_dir = os.path.join(self.artifacts_dir, self.generated_dir_name)
        self._write_iac_files(artifact, generated_dir)

        if not skip_start:
            artifact = await self.start_service(artifact)

        # Phase-named artifact files so plan and apply are never overwritten
        filename = (
            "06a_infrastructure_plan_artifact.json"
            if artifact.phase == "plan"
            else "06b_infrastructure_apply_artifact.json"
        )
        self.save_artifact(artifact, filename)
        self.save_history()
        return artifact

    async def start_service(self, artifact: InfrastructureArtifact) -> InfrastructureArtifact:
        """Start containers for an already-generated IaC artifact."""
        generated_dir = os.path.join(self.artifacts_dir, self.generated_dir_name)
        started = await self._start_containers(generated_dir)
        if started:
            base_url = f"http://localhost:{artifact.primary_service_port}"
            healthy = await self._wait_for_health(
                base_url, artifact.health_check_path, artifact.startup_timeout_seconds
            )
            if healthy:
                artifact.base_url = base_url
                artifact.container_running = True
                console.print(f"[bold green]✅ Application is live at {base_url}[/bold green]")
            else:
                console.print(
                    f"[yellow]⚠ Health check at {base_url}{artifact.health_check_path} "
                    f"did not respond within {artifact.startup_timeout_seconds}s.[/yellow]"
                )
        else:
            console.print(
                "[yellow]⚠ Container startup failed or Docker is not available.[/yellow]"
            )
        return artifact

    async def apply_review_feedback(
        self,
        intent: DiscoveryArtifact,        # noqa: ARG002 — kept for call-site API compat
        architecture: ArchitectureArtifact,  # noqa: ARG002
        engineering: EngineeringArtifact,   # noqa: ARG002
        current: InfrastructureArtifact,
        feedback: ReviewFeedback,
    ) -> InfrastructureArtifact:
        """Re-generate IaC with targeted patching from existing file content.

        Each IaC file (Dockerfile, docker-compose.yml, nginx.conf…) is sent to
        the LLM together with the specific review issues so it can make surgical
        fixes rather than re-imagining everything from scratch.
        """
        next_iter = current.review_iteration + 1
        console.print(
            f"[yellow]🔄 Infrastructure: applying review feedback "
            f"(iteration {current.review_iteration} → {next_iter})[/yellow]"
        )
        if current.container_running:
            await self.stop_containers()

        artifact = await self._patch_files_chunked(
            system=SYSTEM_PROMPT,
            existing_artifact=current,
            feedback=feedback,
            model_class=InfrastructureArtifact,
            file_keys=["iac_files"],
        )

        artifact.review_iteration = next_iter
        artifact.review_feedback_applied = (
            list(feedback.critical_issues) + list(feedback.high_issues)
        )
        # Always skip container start during review iterations —
        # containers start once after the review loop completes.
        artifact.phase = "plan"

        generated_dir = os.path.join(self.artifacts_dir, self.generated_dir_name)
        self._write_iac_files(artifact, generated_dir)

        self.save_artifact(artifact, "06a_infrastructure_plan_artifact.json")
        self.save_history()
        return artifact

    # ─── IaC file writing ────────────────────────────────────────────────────

    def _write_iac_files(self, artifact: InfrastructureArtifact, generated_dir: str) -> None:
        """Write each IaC file into the generated/ directory."""
        os.makedirs(generated_dir, exist_ok=True)
        for iac_file in artifact.iac_files:
            # Prevent path traversal
            safe_path = os.path.normpath(iac_file.path).lstrip(os.sep)
            full_path = os.path.join(generated_dir, safe_path)
            os.makedirs(os.path.dirname(full_path) or generated_dir, exist_ok=True)
            with open(full_path, "w") as f:
                f.write(iac_file.content)
            console.print(f"[dim]  🐳 IaC written: {full_path}[/dim]")

    # ─── Docker operations ───────────────────────────────────────────────────

    async def _start_containers(self, generated_dir: str) -> bool:
        """
        Run `docker compose up --build -d` in generated_dir.
        Returns True if containers started successfully, False otherwise.
        """
        compose_file = os.path.join(generated_dir, "docker-compose.yml")
        if not os.path.exists(compose_file):
            console.print(
                "[yellow]No docker-compose.yml found in generated/ — skipping startup.[/yellow]"
            )
            return False

        try:
            console.print("[cyan]🐳 Building and starting containers (this may take a while)…[/cyan]")
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "up", "--build", "-d", "--force-recreate",
                cwd=generated_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            except asyncio.TimeoutError:
                proc.kill()
                console.print("[red]docker compose up timed out after 5 minutes.[/red]")
                return False

            if proc.returncode != 0:
                err_output = stderr.decode(errors="replace")[-2000:]
                console.print(
                    f"[red]docker compose up failed (exit {proc.returncode}):[/red]\n{err_output}"
                )
                return False

            console.print("[green]Containers started.[/green]")
            return True

        except FileNotFoundError:
            console.print(
                "[yellow]'docker' command not found — "
                "install Docker Desktop or Docker Engine to enable live container tests.[/yellow]"
            )
            return False
        except Exception as e:
            console.print(f"[yellow]Container startup error: {e}[/yellow]")
            return False

    async def _wait_for_health(self, base_url: str, path: str, timeout: int) -> bool:
        """
        Poll `base_url + path` until it returns a non-5xx response or timeout expires.
        Returns True if the service became healthy, False on timeout.
        """
        import httpx

        health_url = f"{base_url}{path}"
        console.print(f"[cyan]Waiting for service at {health_url} …[/cyan]")
        deadline = time.monotonic() + timeout

        async with httpx.AsyncClient(follow_redirects=True) as client:
            while time.monotonic() < deadline:
                try:
                    resp = await client.get(health_url, timeout=5.0)
                    if resp.status_code < 500:
                        console.print(
                            f"[green]Health check passed (HTTP {resp.status_code})[/green]"
                        )
                        return True
                except Exception:
                    pass
                await asyncio.sleep(3)

        console.print(f"[red]Health check timed out after {timeout}s.[/red]")
        return False

    async def stop_containers(self) -> None:
        """Tear down the container stack. Called by the pipeline in a finally block."""
        generated_dir = os.path.join(self.artifacts_dir, self.generated_dir_name)
        compose_file = os.path.join(generated_dir, "docker-compose.yml")
        if not os.path.exists(compose_file):
            return
        try:
            console.print("[cyan]🐳 Stopping containers…[/cyan]")
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "down", "-v", "--remove-orphans",
                cwd=generated_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=60)
            console.print("[green]Containers stopped.[/green]")
        except Exception as e:
            console.print(f"[yellow]Warning: could not stop containers: {e}[/yellow]")
