"""Backend sub-agent — generates the backend/ service in the monorepo."""
from __future__ import annotations
from typing import List, Optional
from llm_sdlc_workflow.models.artifacts import (
    ArchitectureArtifact, EngineeringArtifact, GeneratedSpecArtifact,
    DiscoveryArtifact, ReviewFeedback,
)
from .base_agent import BaseAgent, load_prompt

SYSTEM_PROMPT = load_prompt("backend_agent.md")


class BackendAgent(BaseAgent):
    def __init__(
        self,
        artifacts_dir: str = "./artifacts",
        generated_dir_name: str = "generated",
        language: Optional[str] = None,
        framework: Optional[str] = None,
    ):
        super().__init__(name="Backend Agent", artifacts_dir=artifacts_dir, generated_dir_name=generated_dir_name)
        parts = [p for p in [language, framework] if p]
        # None means "agent freely decides from requirements" — no default imposed
        self.tech_hint: Optional[str] = " / ".join(parts) if parts else None
        # Use the generated_dir_name (project name) as the Python module/package name
        self._module_name = generated_dir_name.replace("-", "_") if generated_dir_name != "generated" else "app"

    async def run(
        self,
        intent: DiscoveryArtifact,
        architecture: ArchitectureArtifact,
        contract: GeneratedSpecArtifact,
        review_feedback: Optional[ReviewFeedback] = None,
        iteration: int = 1,
        current_artifact: Optional[EngineeringArtifact] = None,
    ) -> EngineeringArtifact:
        spec_section = self._build_contract_section(contract)
        feedback_section = self._build_feedback_section(review_feedback)

        if review_feedback and current_artifact:
            # Targeted patch mode: preserve chosen stack from artifact, never let LLM drift
            chosen = self._stack_from_artifact(current_artifact)
            _spec_ctx = f"Tech stack: {chosen}\n"
            _spec_ctx += "CRITICAL: Do NOT change the tech stack. Fix only the issues listed.\n\n"
            if contract.openapi_spec:
                _spec_ctx += contract.openapi_spec[:3000]
            artifact = await self._patch_files_chunked(
                system=SYSTEM_PROMPT,
                existing_artifact=current_artifact,
                feedback=review_feedback,
                model_class=EngineeringArtifact,
                file_keys=["generated_files"],
                spec_context=_spec_ctx,
            )
        else:
            backend_port = contract.service_ports.get("backend", 8080) if contract.service_ports else 8080
            is_internal = bool(contract.service_ports and (
                contract.service_ports.get("bff") or contract.service_ports.get("frontend")
            ))
            port_role = "internal (sits behind BFF or frontend)" if is_internal else "external (directly exposed to clients)"

            # Only constrain the stack when the user explicitly configured one
            if self.tech_hint:
                tech_line = (
                    f"Tech stack: {self.tech_hint}\n"
                    f"IMPORTANT: ALL source files MUST use {self.tech_hint}."
                )
                fill_tech = (
                    f"Write COMPLETE, RUNNABLE {self.tech_hint} content for: {{path}}\n"
                    f"Tech stack: {self.tech_hint} — do NOT switch languages or frameworks.\n"
                )
            else:
                tech_line = (
                    "Tech stack: choose the most appropriate stack based on the requirements.\n"
                    "Justify your choice in backend_tech.rationale."
                )
                fill_tech = (
                    "Write COMPLETE, RUNNABLE content for: {path}\n"
                    "Use the same tech stack you chose in the plan phase — do NOT change it.\n"
                )

            plan_message = f"""Plan and list every file for the backend/ service.

{tech_line}
Module / package name: {self._module_name}  (place source under backend/{self._module_name}/)

## Discovery
{self._compact(intent)}

## Architecture
{self._compact(architecture)}
{spec_section}{feedback_section}

Return JSON with every file's content = "__PENDING__". Valid json."""

            fill_tmpl = (
                fill_tech
                + "Purpose: {purpose}\n"
                + f"Service: backend  |  port: {backend_port}  ({port_role})\n"
                + f"Module: {self._module_name}  (imports: from {self._module_name}.xxx import ...)\n"
                + f"EXPOSE {backend_port} in Dockerfile\n"
                + f"HEALTHCHECK must target port {backend_port} — use /health for lightweight APIs\n"
                + "All response/request models must be defined ONCE in a single models file and imported elsewhere\n"
                + "Architecture: {arch_style}\n"
                + "Endpoints: {endpoints_summary}\n\n"
                + "Return JSON: {{\"content\": \"<full file>\"}}\n"
                + "No TODOs. Valid json."
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
        artifact.service_name = "backend"
        artifact.review_iteration = iteration
        if review_feedback:
            artifact.review_feedback_applied = list(review_feedback.critical_issues) + list(review_feedback.high_issues)
        self.save_artifact(artifact, "03a_backend_artifact.json")
        self._write_service_files(artifact)
        self.save_history()
        return artifact

    def _stack_from_artifact(self, artifact: EngineeringArtifact) -> str:
        """Derive the tech stack string from a previously generated artifact.
        Used during patch iterations to anchor the LLM to what was already built,
        rather than letting it drift based on system prompt priors."""
        if artifact.backend_tech:
            return f"{artifact.backend_tech.language} / {artifact.backend_tech.framework}"
        if self.tech_hint:
            return self.tech_hint
        return "the same tech stack used in the existing files"

    def _build_contract_section(self, contract: GeneratedSpecArtifact) -> str:
        parts = ["\n\n## Contract (source of truth — implement exactly)"]
        if contract.openapi_spec:
            parts.append(f"### OpenAPI spec (BE endpoints)\n```yaml\n{contract.openapi_spec[:4000]}\n```")
        if contract.database_schema:
            parts.append(f"### SQL DDL\n```sql\n{contract.database_schema[:3000]}\n```")
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
        base = os.path.join(self.artifacts_dir, self.generated_dir_name)
        os.makedirs(base, exist_ok=True)
        for f in artifact.generated_files:
            safe = os.path.normpath(f.path).lstrip(os.sep)
            full = os.path.join(base, safe)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as fh:
                fh.write(f.content)
            con.print(f"[dim]  📄 {full}[/dim]")
