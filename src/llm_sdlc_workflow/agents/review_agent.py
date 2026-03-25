"""
Review Agent — audits engineering + infrastructure for security, reliability,
code quality, and performance.

Runs in an iterative loop:
  - First call: full review of all code and IaC.
  - Subsequent calls: re-review of areas flagged as critical/high in previous rounds.

Returns ReviewArtifact (which extends ReviewFeedback) so the pipeline can
check .passed and pass .critical_issues / .high_issues back to agents.
"""

from __future__ import annotations

from llm_sdlc_workflow.models.artifacts import (
    ArchitectureArtifact,
    EngineeringArtifact,
    InfrastructureArtifact,
    DiscoveryArtifact,
    ReviewArtifact,
    ReviewFeedback,
)
from .base_agent import BaseAgent, load_prompt

SYSTEM_PROMPT = load_prompt("review_agent.md")

# Files whose full content is critical for a meaningful code review.
# All others are listed path-only to keep context size manageable.
_KEY_FILE_PATTERNS = (
    # Generic / framework-agnostic
    "controller", "service", "config", "handler", "exception",
    "docker-compose", "nginx.conf", "dockerfile", "security",
    # Python / FastAPI
    "router", "schema", "crud", "deps", "main.py",
    "database", "models.py", "middleware", "settings",
    # Kotlin / Spring (retained for full-stack runs)
    "application.yml", "webclient", "interceptor",
    "appconfig", "webconfig",
    # React / TypeScript frontend
    "useeffect", "usefetch", "app.tsx", "index.tsx",
    "client.ts", "homepage", "backendclient",
)
_MAX_CONTENT_CHARS = 5000   # per file — increased to avoid truncating key config files
_MAX_CONTENT_FILES = 30     # max files whose content we embed


class ReviewAgent(BaseAgent):
    def __init__(self, artifacts_dir: str = "./artifacts", generated_dir_name: str = "generated"):
        super().__init__(name="Review Agent", artifacts_dir=artifacts_dir, generated_dir_name=generated_dir_name)

    # ─── Rich context helpers ────────────────────────────────────────────────

    def _engineering_review_context(self, engineering: EngineeringArtifact) -> str:
        """Build a review-friendly summary that includes actual file content
        for implementation-critical files.

        Key files (controllers, services, configs, etc.) get their full source
        included (truncated at _MAX_CONTENT_CHARS).  All other files are listed
        by path + purpose only so the context stays manageable.
        """
        files = engineering.generated_files
        key, other = [], []
        for f in files:
            path_lower = f.path.lower()
            if any(pat in path_lower for pat in _KEY_FILE_PATTERNS):
                key.append(f)
            else:
                other.append(f)

        lines = [
            f"### EngineeringArtifact — {len(files)} files total",
            f"Backend  : {engineering.backend_tech.framework if engineering.backend_tech else '?'}",
            f"Frontend : {engineering.frontend_tech.framework if engineering.frontend_tech else '?'}",
            "",
            f"#### Implementation-critical files ({min(len(key), _MAX_CONTENT_FILES)} of {len(key)} shown with content)",
        ]
        for f in key[:_MAX_CONTENT_FILES]:
            content = f.content
            if len(content) > _MAX_CONTENT_CHARS:
                content = content[:_MAX_CONTENT_CHARS] + "\n... [truncated]"
            lines.append(f"\n--- {f.path} ---")
            lines.append(content)

        if other:
            lines.append(f"\n#### Other files (path/purpose only, {len(other)} files)")
            for f in other:
                lines.append(f"  - {f.path} — {f.purpose[:80]}")

        if engineering.environment_variables:
            lines.append("\n#### Environment variables")
            for k, v in list(engineering.environment_variables.items())[:20]:
                lines.append(f"  {k}={v}")

        return "\n".join(lines)

    def _infra_review_context(self, infrastructure: InfrastructureArtifact) -> str:
        """Include full content for all IaC files (they are usually few and small)."""
        files = infrastructure.iac_files
        lines = [f"### InfrastructureArtifact — {len(files)} IaC files"]
        for f in files:
            content = f.content
            if len(content) > _MAX_CONTENT_CHARS:
                content = content[:_MAX_CONTENT_CHARS] + "\n... [truncated]"
            lines.append(f"\n--- {f.path} ---")
            lines.append(content)
        if infrastructure.environment_variables:
            lines.append("\n#### Infrastructure env vars")
            for k, v in list(infrastructure.environment_variables.items())[:20]:
                lines.append(f"  {k}={v}")
        return "\n".join(lines)

    # ─── Main run ────────────────────────────────────────────────────────────

    async def run(
        self,
        intent: DiscoveryArtifact,
        architecture: ArchitectureArtifact,
        engineering: EngineeringArtifact,
        infrastructure: InfrastructureArtifact,
        iteration: int = 1,
        previous_feedback: ReviewFeedback | None = None,
    ) -> ReviewArtifact:
        prev_section = ""
        if previous_feedback and iteration > 1:
            prev_section = (
                f"\n\n## Issues flagged in the PREVIOUS iteration (for reference only)\n"
                "IMPORTANT: You MUST review the CURRENT code shown above independently.\n"
                "Do NOT assume these issues are still present — verify each one against the\n"
                "actual file content shown above BEFORE including it in your report.\n"
                "Only flag an issue if you can cite the EXACT line in the CURRENT code.\n"
                "If the code was fixed, do NOT re-report it.\n\n"
                "### Previous critical issues (verify in CURRENT code before flagging)\n"
                + "\n".join(f"- {i}" for i in previous_feedback.critical_issues)
                + "\n### Previous high issues (verify in CURRENT code before flagging)\n"
                + "\n".join(f"- {i}" for i in previous_feedback.high_issues)
            )

        # Single comprehensive context — sent in one call
        review_context = f"""Review iteration {iteration}.

## Discovery Summary
{self._compact(intent)}

## Architecture Summary
{self._compact(architecture)}

## Engineering Artifact (source code)
{self._engineering_review_context(engineering)}

## Infrastructure Artifact (IaC files)
{self._infra_review_context(infrastructure)}
{prev_section}"""

        message = (
            review_context
            + "\n\nReview ALL dimensions: security, reliability, maintainability, and performance.\n"
            "Produce the complete ReviewArtifact including:\n"
            "  - issues: all Issue objects across every dimension\n"
            "  - critical_issues, high_issues, suggestions: lists of strings\n"
            "  - security_score, reliability_score, maintainability_score, performance_score (0-100)\n"
            "  - overall_score: weighted avg (security×0.35 + reliability×0.25 + "
            "maintainability×0.25 + performance×0.15)\n"
            "  - passed: true ONLY if critical_issues is empty\n"
            "  - strengths, recommendations, decisions, critical_fixes_required\n"
            "Respond ONLY with the JSON block."
        )

        artifact = await self._query_and_parse(SYSTEM_PROMPT, message, ReviewArtifact)

        artifact.iteration = iteration

        filename = f"04_review_artifact_iter{iteration}.json"
        self.save_artifact(artifact, filename)
        self.save_history()
        return artifact
