"""
Spec Agent — generates formal specifications BEFORE engineering runs.

Position in the pipeline: AFTER Architecture, BEFORE Engineering sub-agents.

Derives a binding contract (GeneratedSpecArtifact) from intent + architecture:
  - OpenAPI 3.0 YAML  (all endpoints, split BE-internal / BFF-exposed)
  - SQL DDL schema    (all tables, idempotent IF NOT EXISTS)
  - tech_stack_constraints string   → fed to BE/BFF/FE sub-agents
  - architecture_constraints string → monorepo topology, ports, Docker names
  - monorepo_services, service_ports, shared_models

--from-run mode: if an existing_spec is supplied, the new contract EXTENDS it
(new endpoints/tables only; existing ones get x-existing markers so sub-agents
cannot break a running API).

All spec files are written to generated/specs/ so future runs can load them:
    python main.py --requirements new-feature.txt --from-run artifacts/<run>
"""

from __future__ import annotations

import os
from typing import Optional

from models.artifacts import (
    ArchitectureArtifact,
    GeneratedSpecArtifact,
    DiscoveryArtifact,
    SpecArtifact,
)
from .base_agent import BaseAgent, load_prompt

SYSTEM_PROMPT = load_prompt("spec_agent.md")


class SpecAgent(BaseAgent):
    def __init__(self, artifacts_dir: str = "./artifacts", generated_dir_name: str = "generated"):
        super().__init__(name="Spec Agent", artifacts_dir=artifacts_dir, generated_dir_name=generated_dir_name)

    async def run(
        self,
        intent: DiscoveryArtifact,
        architecture: ArchitectureArtifact,
        existing_spec: Optional[SpecArtifact] = None,
    ) -> GeneratedSpecArtifact:
        """
        Derive a forward contract from intent + architecture.
        All engineering sub-agents implement against this contract.
        If existing_spec is provided (--from-run), the new contract EXTENDS
        the existing OpenAPI and DDL rather than replacing them.
        """
        existing_section = self._build_existing_section(existing_spec)

        plan_message = f"""Derive formal specifications from intent and architecture.

## Discovery Summary
{self._compact(intent)}

## Architecture Summary
{self._compact(architecture)}
{existing_section}
Monorepo topology (mandatory):
- backend/   Kotlin Spring Boot 3.3, internal REST API, port 8081
- bff/       Kotlin Spring Boot 3.3 WebFlux, reactive gateway, port 8080
- frontend/  React 18 + TypeScript 5 + Vite 5 → Nginx, host port 3000
Docker Compose service names: backend, bff, frontend

Produce JSON plan with every file's content = "__PENDING__". Valid json."""

        fill_message_tmpl = (
            "Write the COMPLETE content for the spec file: {path}\n"
            "Purpose: {purpose}\n\n"
            "Monorepo: backend (port 8081) + bff (port 8080) + frontend (host 3000)\n"
            "Architecture: {arch_style}\n"
            "Requirements summary: {requirements_summary}\n\n"
            "Return JSON: {{\"content\": \"<full spec text>\"}}\n"
            "Must be complete, valid, and directly usable. Valid json response."
        )

        artifact = await self._query_and_parse_chunked(
            system=SYSTEM_PROMPT,
            plan_message=plan_message,
            file_keys=["generated_spec_files"],
            model_class=GeneratedSpecArtifact,
            fill_message_tmpl=fill_message_tmpl,
            fill_context={
                "arch_style": getattr(architecture, "architecture_style", "three-tier monorepo"),
                "requirements_summary": "; ".join(intent.requirements[:5]),
            },
        )

        # Populate convenience scalar fields from the generated files
        for f in artifact.generated_spec_files:
            if f.path.endswith("openapi.yaml") and f.content not in ("__PENDING__", ""):
                artifact.openapi_spec = f.content
            elif f.path.endswith("schema.sql") and f.content not in ("__PENDING__", ""):
                artifact.database_schema = f.content

        # Guarantee monorepo topology defaults
        if not artifact.monorepo_services:
            artifact.monorepo_services = ["backend", "bff", "frontend"]
        if not artifact.service_ports:
            artifact.service_ports = {"backend": 8081, "bff": 8080, "frontend": 3000}

        self._write_spec_files(artifact)
        self.save_artifact(artifact, "04_generated_spec_artifact.json")
        self.save_history()
        return artifact

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _build_existing_section(self, existing_spec: Optional[SpecArtifact]) -> str:
        if not existing_spec:
            return ""
        parts = [
            "\n\n## EXISTING SPEC (from previous run — MUST be preserved)",
            "Mark existing OpenAPI paths as `x-existing: true` — sub-agents MUST NOT modify them.\n"
            "Mark existing SQL tables as `-- EXISTING: DO NOT ALTER`.\n"
            "Add only NEW endpoints and tables required by the new requirements.",
        ]
        if existing_spec.api_spec:
            parts.append(f"### Existing OpenAPI\n```yaml\n{existing_spec.api_spec[:3000]}\n```")
        if existing_spec.database_schema:
            parts.append(f"### Existing DDL\n```sql\n{existing_spec.database_schema[:2000]}\n```")
        if existing_spec.tech_stack_constraints:
            parts.append(f"### Existing tech\n{existing_spec.tech_stack_constraints}")
        return "\n\n".join(parts)

    def _write_spec_files(self, artifact: GeneratedSpecArtifact) -> None:
        from rich.console import Console
        con = Console()
        specs_dir = os.path.join(self.artifacts_dir, self.generated_dir_name, "specs")
        os.makedirs(specs_dir, exist_ok=True)
        for spec_file in artifact.generated_spec_files:
            if spec_file.content in ("__PENDING__", ""):
                continue
            safe_path = os.path.normpath(spec_file.path).lstrip(os.sep)
            full_path = os.path.join(self.artifacts_dir, self.generated_dir_name, safe_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as fh:
                fh.write(spec_file.content)
            con.print(f"[dim]  📐 Spec: {full_path}[/dim]")
        con.print(
            f"[bold green]📐 Contract ready → {specs_dir}[/bold green]\n"
            f"[dim]Re-use: python main.py --requirements new.txt "
            f"--from-run {self.artifacts_dir}[/dim]"
        )
