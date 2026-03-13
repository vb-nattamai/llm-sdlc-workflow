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

from models.artifacts import (
    ArchitectureArtifact,
    EngineeringArtifact,
    InfrastructureArtifact,
    IntentArtifact,
)
from .base_agent import BaseAgent, load_prompt

SYSTEM_PROMPT = load_prompt("infrastructure_agent.md")

console = Console()


class InfrastructureAgent(BaseAgent):
    def __init__(self, artifacts_dir: str = "./artifacts"):
        super().__init__(name="Infrastructure Agent", artifacts_dir=artifacts_dir)

    async def run(
        self,
        intent: IntentArtifact,
        architecture: ArchitectureArtifact,
        engineering: EngineeringArtifact,
    ) -> InfrastructureArtifact:
        """
        Generate IaC, write files, start containers, and wait for the service
        to be healthy. Returns an InfrastructureArtifact with base_url set if
        the container started successfully.
        """
        user_message = f"""Generate Infrastructure as Code to containerise this application.

## Intent Summary
{self._compact(intent)}

## Architecture Summary
{self._compact(architecture)}

## Engineering Summary
{self._compact(engineering)}

The generated application files already exist in the working directory.
Produce a Dockerfile and docker-compose.yml so the full stack starts with:
  docker compose up --build

Respond ONLY with the JSON block."""

        artifact = await self._query_and_parse(
            system=SYSTEM_PROMPT,
            user_message=user_message,
            model_class=InfrastructureArtifact,
        )

        # Write IaC files alongside the generated source code
        generated_dir = os.path.join(self.artifacts_dir, "generated")
        self._write_iac_files(artifact, generated_dir)

        # Build and start the containers
        started = await self._start_containers(generated_dir)
        if started:
            base_url = f"http://localhost:{artifact.primary_service_port}"
            healthy = await self._wait_for_health(
                base_url, artifact.health_check_path, artifact.startup_timeout_seconds
            )
            if healthy:
                artifact.base_url = base_url
                artifact.container_running = True
                console.print(
                    f"[bold green]✅ Application is live at {base_url}[/bold green]"
                )
            else:
                console.print(
                    f"[yellow]⚠ Containers are up but health check at "
                    f"{base_url}{artifact.health_check_path} did not respond within "
                    f"{artifact.startup_timeout_seconds}s. Live tests will be skipped.[/yellow]"
                )
        else:
            console.print(
                "[yellow]⚠ Container startup failed or Docker is not available. "
                "Live tests will be skipped.[/yellow]"
            )

        self.save_artifact(artifact, "06_infrastructure_artifact.json")
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
        generated_dir = os.path.join(self.artifacts_dir, "generated")
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
