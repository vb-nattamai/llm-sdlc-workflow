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
    design_decisions: List[DecisionRecord]


# ─── Engineering Agent ───────────────────────────────────────────────────────


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
    """Output of the Engineering Agent — tech stack and implementation plan."""

    backend_tech: TechStack
    frontend_tech: Optional[TechStack] = None
    infrastructure: str
    generated_files: List[FileSpec]
    implementation_steps: List[ImplementationStep]
    environment_variables: Dict[str, str] = {}
    api_endpoints: List[str] = []
    data_models: List[str] = []
    spec_compliance_notes: List[str] = []  # how user specs were applied
    decisions: List[DecisionRecord]


# ─── Infrastructure Agent ────────────────────────────────────────────────────


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
    decisions: List[DecisionRecord]

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


class ReviewArtifact(BaseModel):
    """Output of the Review Agent — quality assessment."""

    overall_score: int = Field(ge=0, le=100)
    security_score: int = Field(ge=0, le=100)
    reliability_score: int = Field(ge=0, le=100)
    maintainability_score: int = Field(ge=0, le=100)
    performance_score: int = Field(ge=0, le=100)
    issues: List[Issue]
    strengths: List[str]
    critical_fixes_required: List[str]
    recommendations: List[str]
    passed: bool
    decisions: List[DecisionRecord]


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
    coverage_areas: List[str]
    uncovered_areas: List[str]
    findings: List[str]
    blocking_issues: List[str]
    passed: bool
    recommendations: List[str]
    decisions: List[DecisionRecord]
