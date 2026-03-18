"""
Artifact data models for all agents in the multi-agent pipeline.
Each agent produces a typed artifact that is persisted to disk and
passed downstream as context.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class DecisionRecord(BaseModel):
    """Captures a single architectural or implementation decision with full rationale."""

    decision: str
    rationale: str
    alternatives_considered: List[str]
    trade_offs: List[str] = []
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ─── Spec Artifact (optional user-provided technical specs) ──────────────────


class SpecArtifact(BaseModel):
    """
    Optional technical specifications provided by the user.
    Passed to Architecture and Engineering agents as constraints.
    Testing Agent does NOT use this — it verifies against IntentArtifact only.
    """

    api_spec: Optional[str] = None          # OpenAPI / Swagger YAML or JSON
    database_schema: Optional[str] = None   # SQL DDL, ER diagram description, etc.
    architecture_constraints: Optional[str] = None  # e.g. "must use PostgreSQL, Redis"
    tech_stack_constraints: Optional[str] = None    # e.g. "Python FastAPI, React"
    additional_specs: Dict[str, str] = {}   # name -> content for any other specs
    source_files: List[str] = []            # paths to spec files that were loaded


# ─── Intent Agent ───────────────────────────────────────────────────────────


class IntentArtifact(BaseModel):
    """Output of the Intent Agent — the distilled understanding of what needs to be built."""

    raw_requirements: str
    requirements: List[str]
    user_goals: List[str]
    constraints: List[str]
    success_criteria: List[str]
    key_features: List[str]
    tech_preferences: Optional[List[str]] = None
    domain_context: str
    scope: str
    risks: List[str] = []
    decisions: List[DecisionRecord] = []


# ─── Architecture Agent ──────────────────────────────────────────────────────


class ComponentSpec(BaseModel):
    name: str
    responsibility: str
    interfaces: List[str]
    dependencies: List[str]
    technology_hint: Optional[str] = None


class ArchitectureArtifact(BaseModel):
    """Output of the Architecture Agent — the system design blueprint."""

    system_overview: str
    architecture_style: str
    components: List[ComponentSpec]
    data_flow: List[str]
    api_design: List[str]
    database_design: str
    security_design: str
    deployment_strategy: str
    patterns_used: List[str]
    scalability_considerations: List[str]
    trade_offs: List[str]
    spec_compliance_notes: List[str] = []  # how user specs were applied
    design_decisions: List[DecisionRecord] = []


# ─── Engineering Agent ───────────────────────────────────────────────────────


class ReviewFeedback(BaseModel):
    """
    Structured feedback from the Review Agent directed at Engineering or Infrastructure.
    Passed back so each agent can apply fixes in the review loop.
    """
    iteration: int = 1
    critical_issues: List[str] = []      # must fix before passing
    high_issues: List[str] = []          # should fix
    suggestions: List[str] = []          # nice-to-have
    passed: bool = False                 # True only when no critical issues remain


class TechStack(BaseModel):
    framework: str
    language: str
    version: str
    key_libraries: List[str]
    rationale: str


class FileSpec(BaseModel):
    path: str
    purpose: str
    content: str  # full file content or detailed implementation spec


class ImplementationStep(BaseModel):
    step: int
    description: str
    files_involved: List[str]
    acceptance_criteria: List[str] = []


class EngineeringArtifact(BaseModel):
    """Combined output from all engineering sub-agents (monorepo)."""

    # Set by sub-agents; None on the combined artifact from the orchestrator
    service_name: Optional[str] = None   # "backend" | "bff" | "frontend" | None

    # Per-service outputs (keyed by service name: "backend" | "bff" | "frontend")
    services: Dict[str, "ServiceArtifact"] = {}

    # Flat convenience fields (merged from services by EngineeringAgent.assemble())
    backend_tech: Optional[TechStack] = None
    frontend_tech: Optional[TechStack] = None
    infrastructure: str = ""
    generated_files: List[FileSpec] = []     # all files across all services
    implementation_steps: List[ImplementationStep] = []
    environment_variables: Dict[str, str] = {}
    api_endpoints: List[str] = []
    data_models: List[str] = []
    spec_compliance_notes: List[str] = []
    decisions: List[DecisionRecord] = []
    review_iteration: int = 1
    review_feedback_applied: List[str] = []


class ServiceArtifact(BaseModel):
    """Output of one engineering sub-agent: Backend, BFF, or Frontend."""

    service: str   # "backend" | "bff" | "frontend"
    tech_stack: Optional[TechStack] = None
    generated_files: List[FileSpec] = []
    api_endpoints: List[str] = []
    data_models: List[str] = []
    environment_variables: Dict[str, str] = {}
    implementation_steps: List[ImplementationStep] = []
    spec_compliance_notes: List[str] = []
    decisions: List[DecisionRecord] = []
    review_iteration: int = 1
    review_feedback_applied: List[str] = []


# Resolve forward reference
EngineeringArtifact.model_rebuild()


class IaCFile(BaseModel):
    """A single Infrastructure-as-Code file (Dockerfile, docker-compose.yml, etc.)."""

    path: str       # relative path inside the generated/ directory, e.g. "Dockerfile"
    content: str    # full file content
    purpose: str    # one-line description


class InfrastructureArtifact(BaseModel):
    """Output of the Infrastructure Agent — IaC files and container runtime info."""

    iac_files: List[IaCFile]              # Dockerfile, docker-compose.yml, .env.example, …
    primary_service_port: int             # host port the app is exposed on
    health_check_path: str = "/health"    # endpoint polled to confirm readiness
    startup_timeout_seconds: int = 90     # seconds to wait before declaring startup failed
    environment_variables: Dict[str, str] = {}   # VAR_NAME → default / description
    service_dependencies: List[str] = []  # e.g. ["postgres", "redis"]
    build_notes: List[str] = []
    spec_compliance_notes: List[str] = []
    decisions: List[DecisionRecord] = []
    review_iteration: int = 1
    review_feedback_applied: List[str] = []

    # Runtime fields — populated by the pipeline after the container starts (not from LLM)
    base_url: Optional[str] = None
    container_running: bool = False


# ─── Review Agent ────────────────────────────────────────────────────────────


class Issue(BaseModel):
    severity: str   # critical | high | medium | low
    category: str   # security | reliability | performance | maintainability | correctness
    description: str
    location: str
    recommendation: str
    cwe_id: Optional[str] = None


class ReviewArtifact(ReviewFeedback):
    """Output of the Review Agent — quality assessment with structured loop-feedback fields."""

    overall_score: int = Field(default=0, ge=0, le=100)
    security_score: int = Field(default=0, ge=0, le=100)
    reliability_score: int = Field(default=0, ge=0, le=100)
    maintainability_score: int = Field(default=0, ge=0, le=100)
    performance_score: int = Field(default=0, ge=0, le=100)
    issues: List[Issue] = []
    strengths: List[str] = []
    critical_fixes_required: List[str] = []   # kept for backward compat
    recommendations: List[str] = []
    decisions: List[DecisionRecord] = []


# ─── Testing Agent ───────────────────────────────────────────────────────────


class HttpTestCase(BaseModel):
    """A live HTTP test case executed against the running container."""

    id: str
    name: str
    description: str
    requirement_covered: str
    method: str                         # GET | POST | PUT | DELETE | PATCH
    path: str                           # e.g. /api/v1/tasks
    headers: Dict[str, str] = {}
    request_body: Optional[Dict] = None
    expected_status: int
    response_contains: List[str] = []   # substrings / keys that must appear in body
    # Populated after execution
    status: Optional[str] = None        # passed | failed | error
    actual_status: Optional[int] = None
    actual_response: Optional[str] = None
    error: Optional[str] = None


class TestCase(BaseModel):
    id: str
    name: str
    description: str
    requirement_covered: str
    test_type: str   # unit | integration | e2e | security | performance
    steps: List[str]
    expected_outcome: str
    actual_outcome: Optional[str] = None
    status: Optional[str] = None   # passed | failed | skipped | pending


class TestingArtifact(BaseModel):
    """Output of the Testing Agent at a given pipeline stage."""

    stage: str
    test_cases: List[TestCase]
    http_test_cases: List[HttpTestCase] = []   # live HTTP tests (infrastructure stage)
    cypress_spec_files: List[FileSpec] = []    # Cypress e2e specs written to disk
    coverage_areas: List[str]
    uncovered_areas: List[str]
    findings: List[str]
    blocking_issues: List[str]
    passed: bool
    recommendations: List[str]
    decisions: List[DecisionRecord] = []


# ─── Spec Agent (forward contract for spec-driven development) ───────────────


class GeneratedSpecArtifact(BaseModel):
    """
    Forward-generated formal specifications derived from intent + architecture.

    Produced by SpecAgent BEFORE engineering runs. All engineering sub-agents
    (BE, BFF, FE) implement against this shared contract, ensuring they stay
    consistent with each other.

    The spec files are also written to generated/specs/ so future pipeline runs
    can load them with --from-run for spec-driven incremental development:

      Run 1 (greenfield):
        python main.py --requirements hello-world.txt
        → generates code + generated/specs/

      Run 2+ (spec-driven, adds a new feature):
        python main.py --requirements new-feature.txt --from-run artifacts/run_20260318_XYZ
        → loads existing OpenAPI + DDL, extends rather than replaces
    """

    # Formal contracts consumed by engineering sub-agents
    openapi_spec: str = ""           # full OpenAPI 3.0 YAML
    database_schema: str = ""        # full SQL DDL (all services share one DB or separate schemas)
    tech_stack_constraints: str = "" # "Must use Kotlin Spring Boot 3, React 18 TS Vite …"
    architecture_constraints: str = ""  # "Must follow three-tier monorepo pattern …"

    # Monorepo topology
    monorepo_services: List[str] = []         # ["backend", "bff", "frontend"]
    service_ports: Dict[str, int] = {}        # {"backend": 8081, "bff": 8080, "frontend": 3000}
    shared_models: List[str] = []             # DTO / entity names referenced by multiple services

    # Spec files written to generated/specs/
    generated_spec_files: List[FileSpec] = []

    # Short human-readable summary for the usage guide
    usage_guide: str = ""

