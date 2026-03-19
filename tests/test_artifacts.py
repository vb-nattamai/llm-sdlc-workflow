"""
Unit tests for all Pydantic artifact data models.

Covers:
  - _coerce_str_list() edge cases
  - DiscoveryArtifact, ArchitectureArtifact, ComponentSpec
  - EngineeringArtifact, ServiceArtifact
  - InfrastructureArtifact, IaCFile
  - ReviewArtifact, ReviewFeedback, Issue
  - TestingArtifact, TestCase, HttpTestCase
  - GeneratedSpecArtifact, SpecArtifact, DecisionRecord
"""

from __future__ import annotations

import pytest

from llm_sdlc_workflow.models.artifacts import (
    ArchitectureArtifact,
    ComponentSpec,
    DecisionRecord,
    DiscoveryArtifact,
    EngineeringArtifact,
    FileSpec,
    GeneratedSpecArtifact,
    HttpTestCase,
    IaCFile,
    InfrastructureArtifact,
    Issue,
    ReviewArtifact,
    ReviewFeedback,
    ServiceArtifact,
    SpecArtifact,
    TechStack,
    TestCase,
    TestingArtifact,
    _coerce_str_list,
)


# ─── _coerce_str_list ─────────────────────────────────────────────────────────


class TestCoerceStrList:
    def test_plain_strings_pass_through_unchanged(self):
        assert _coerce_str_list(["a", "b", "c"]) == ["a", "b", "c"]

    def test_empty_list_returns_empty_list(self):
        assert _coerce_str_list([]) == []

    def test_none_returns_empty_list(self):
        assert _coerce_str_list(None) == []

    def test_dict_with_description_key_uses_description(self):
        result = _coerce_str_list([{"description": "User auth"}, "plain"])
        assert result == ["User auth", "plain"]

    def test_dict_with_name_key_uses_name(self):
        result = _coerce_str_list([{"name": "PostgreSQL constraint"}])
        assert result == ["PostgreSQL constraint"]

    def test_dict_with_value_key_uses_value(self):
        result = _coerce_str_list([{"value": "some value"}])
        assert result == ["some value"]

    def test_dict_prefers_description_over_name(self):
        result = _coerce_str_list([{"description": "desc", "name": "nm"}])
        assert result == ["desc"]

    def test_dict_without_known_keys_falls_back_to_str(self):
        result = _coerce_str_list([{"unknown_key": "data"}])
        assert result[0] == str({"unknown_key": "data"})

    def test_non_dict_non_string_items_are_stringified(self):
        result = _coerce_str_list([42, 3.14, True])
        assert result == ["42", "3.14", "True"]

    def test_scalar_non_list_wrapped_in_list(self):
        result = _coerce_str_list("single string")
        assert result == ["single string"]

    def test_mixed_types_all_become_strings(self):
        result = _coerce_str_list([{"description": "item 1"}, "item 2", 3])
        assert result == ["item 1", "item 2", "3"]


# ─── DecisionRecord ───────────────────────────────────────────────────────────


class TestDecisionRecord:
    def test_required_fields_only(self):
        d = DecisionRecord(decision="Use PostgreSQL", rationale="ACID compliance")
        assert d.decision == "Use PostgreSQL"
        assert d.rationale == "ACID compliance"
        assert d.alternatives_considered == []
        assert d.trade_offs == []

    def test_timestamp_is_set_automatically(self):
        d = DecisionRecord(decision="x", rationale="y")
        assert d.timestamp  # non-empty string

    def test_coerces_alternatives_from_dicts(self):
        d = DecisionRecord(
            decision="x",
            rationale="y",
            alternatives_considered=[{"description": "Redis"}, "MySQL"],
        )
        assert d.alternatives_considered == ["Redis", "MySQL"]


# ─── DiscoveryArtifact ────────────────────────────────────────────────────────


class TestDiscoveryArtifact:
    def _minimal(self, **kwargs) -> DiscoveryArtifact:
        base: dict = {
            "raw_requirements": "Build API",
            "requirements": ["r"],
            "user_goals": ["g"],
            "constraints": [],
            "success_criteria": [],
            "key_features": [],
            "domain_context": "x",
            "scope": "x",
        }
        base.update(kwargs)
        return DiscoveryArtifact(**base)

    def test_coerces_dict_requirements(self):
        a = self._minimal(requirements=[{"description": "User auth"}, "CRUD tasks"])
        assert a.requirements == ["User auth", "CRUD tasks"]

    def test_coerces_dict_user_goals(self):
        a = self._minimal(user_goals=[{"name": "Fast delivery"}])
        assert a.user_goals == ["Fast delivery"]

    def test_tech_preferences_defaults_to_none(self):
        assert self._minimal().tech_preferences is None

    def test_tech_preferences_can_be_list(self):
        a = self._minimal(tech_preferences=["Python", "FastAPI"])
        assert a.tech_preferences == ["Python", "FastAPI"]

    def test_risks_defaults_to_empty_list(self):
        assert self._minimal().risks == []

    def test_decisions_defaults_to_empty_list(self):
        assert self._minimal().decisions == []

    def test_all_string_fields_stored_correctly(self):
        a = self._minimal(
            raw_requirements="Build a REST API",
            domain_context="E-commerce",
            scope="Backend only",
        )
        assert a.raw_requirements == "Build a REST API"
        assert a.domain_context == "E-commerce"
        assert a.scope == "Backend only"

    # ── LLM coercion: dict/list returned for str fields ──────────────────────

    def test_scope_as_dict_with_in_scope_out_of_scope(self):
        """LLM returns scope as {in_scope:[...], out_of_scope:[...]} — must coerce to str."""
        a = self._minimal(scope={"in_scope": ["REST API endpoints", "CRUD ops"], "out_of_scope": ["Auth"]})
        assert isinstance(a.scope, str)
        assert "in_scope" in a.scope or "REST API" in a.scope

    def test_scope_as_plain_dict_with_description(self):
        a = self._minimal(scope={"description": "Backend only"})
        assert a.scope == "Backend only"

    def test_scope_as_list(self):
        a = self._minimal(scope=["Backend", "API"])
        assert isinstance(a.scope, str)
        assert "Backend" in a.scope

    def test_domain_context_as_dict(self):
        a = self._minimal(domain_context={"primary": "E-commerce", "secondary": "B2B"})
        assert isinstance(a.domain_context, str)
        assert "E-commerce" in a.domain_context

    def test_domain_context_as_list(self):
        a = self._minimal(domain_context=["E-commerce", "retail"])
        assert isinstance(a.domain_context, str)

    def test_scope_as_int_coerces(self):
        a = self._minimal(scope=42)
        assert a.scope == "42"

    def test_constraints_as_dicts_with_name_key(self):
        a = self._minimal(constraints=[{"name": "Must use H2"}, {"description": "Port 8080"}])
        assert a.constraints == ["Must use H2", "Port 8080"]

    def test_success_criteria_as_dicts(self):
        a = self._minimal(success_criteria=[{"description": "All tests pass"}, "200 OK"])
        assert a.success_criteria == ["All tests pass", "200 OK"]


# ─── ArchitectureArtifact ─────────────────────────────────────────────────────


class TestArchitectureArtifact:
    def _minimal(self, **kwargs) -> ArchitectureArtifact:
        base: dict = {
            "system_overview": "REST API",
            "architecture_style": "Monolith",
            "components": [],
            "data_flow": ["Client → API"],
            "api_design": ["GET /"],
            "database_design": "PostgreSQL",
            "security_design": "JWT",
            "deployment_strategy": "Docker",
            "patterns_used": ["MVC"],
            "scalability_considerations": ["Horizontal"],
            "trade_offs": ["Monolith simpler"],
        }
        base.update(kwargs)
        return ArchitectureArtifact(**base)

    def test_coerces_data_flow_dicts(self):
        a = self._minimal(data_flow=[{"description": "Client to API"}, "API to DB"])
        assert a.data_flow == ["Client to API", "API to DB"]

    def test_spec_compliance_notes_defaults_empty(self):
        assert self._minimal().spec_compliance_notes == []

    def test_design_decisions_defaults_empty(self):
        assert self._minimal().design_decisions == []

    def test_component_spec_stores_all_fields(self):
        comp = ComponentSpec(
            name="Auth Service",
            responsibility="Handle JWT issuance",
            interfaces=["REST"],
            dependencies=["DB"],
            technology_hint="FastAPI",
        )
        assert comp.name == "Auth Service"
        assert comp.technology_hint == "FastAPI"

    def test_component_spec_technology_hint_optional(self):
        comp = ComponentSpec(
            name="DB",
            responsibility="Persist data",
            interfaces=["SQL"],
            dependencies=[],
        )
        assert comp.technology_hint is None


# ─── SpecArtifact ─────────────────────────────────────────────────────────────


class TestSpecArtifact:
    def test_all_fields_optional_with_defaults(self):
        spec = SpecArtifact()
        assert spec.api_spec is None
        assert spec.database_schema is None
        assert spec.architecture_constraints is None
        assert spec.tech_stack_constraints is None
        assert spec.additional_specs == {}
        assert spec.source_files == []

    def test_stores_api_spec_string(self):
        spec = SpecArtifact(api_spec="openapi: '3.0.0'")
        assert spec.api_spec == "openapi: '3.0.0'"

    def test_stores_additional_specs_dict(self):
        spec = SpecArtifact(additional_specs={"style-guide": "Use snake_case"})
        assert spec.additional_specs["style-guide"] == "Use snake_case"


# ─── InfrastructureArtifact ───────────────────────────────────────────────────


class TestInfrastructureArtifact:
    def _minimal(self, **kwargs) -> InfrastructureArtifact:
        base: dict = {"iac_files": [], "primary_service_port": 8080}
        base.update(kwargs)
        return InfrastructureArtifact(**base)

    def test_phase_defaults_to_plan(self):
        assert self._minimal().phase == "plan"

    def test_phase_can_be_apply(self):
        assert self._minimal(phase="apply").phase == "apply"

    def test_container_running_defaults_to_false(self):
        assert self._minimal().container_running is False

    def test_base_url_defaults_to_none(self):
        assert self._minimal().base_url is None

    def test_health_check_path_default(self):
        assert self._minimal().health_check_path == "/health"

    def test_iac_file_stores_content(self):
        f = IaCFile(path="Dockerfile", content="FROM python:3.11", purpose="container")
        assert f.content == "FROM python:3.11"

    def test_service_dependencies_coercion(self):
        a = self._minimal(
            service_dependencies=[{"name": "postgres"}, "redis"]
        )
        assert a.service_dependencies == ["postgres", "redis"]

    def test_stores_multiple_iac_files(self):
        a = self._minimal(
            iac_files=[
                IaCFile(path="Dockerfile", content="FROM python:3.11", purpose="app"),
                IaCFile(path="docker-compose.yml", content="version: '3.8'", purpose="orchestration"),
            ]
        )
        assert len(a.iac_files) == 2
        assert a.iac_files[0].path == "Dockerfile"


# ─── ReviewArtifact ───────────────────────────────────────────────────────────


class TestReviewArtifact:
    def test_passed_defaults_to_false(self):
        r = ReviewArtifact()
        assert r.passed is False

    def test_overall_score_defaults_to_zero(self):
        assert ReviewArtifact().overall_score == 0

    def test_score_accepts_boundary_values(self):
        r_min = ReviewArtifact(overall_score=0)
        r_max = ReviewArtifact(overall_score=100)
        assert r_min.overall_score == 0
        assert r_max.overall_score == 100

    def test_score_rejects_above_100(self):
        with pytest.raises(Exception):
            ReviewArtifact(overall_score=101)

    def test_score_rejects_below_0(self):
        with pytest.raises(Exception):
            ReviewArtifact(overall_score=-1)

    def test_issue_stores_all_fields(self):
        issue = Issue(
            severity="critical",
            category="security",
            description="SQL injection via unsanitised input",
            location="GET /tasks",
            recommendation="Use parameterised queries",
            cwe_id="CWE-89",
        )
        assert issue.severity == "critical"
        assert issue.cwe_id == "CWE-89"

    def test_issue_cwe_id_optional(self):
        issue = Issue(
            severity="low",
            category="maintainability",
            description="Missing docstrings",
            location="utils.py",
            recommendation="Add docstrings",
        )
        assert issue.cwe_id is None

    def test_critical_issues_and_high_issues_stored(self):
        r = ReviewArtifact(
            critical_issues=["SQL injection"],
            high_issues=["No input validation", "Missing HTTPS"],
            passed=False,
        )
        assert len(r.critical_issues) == 1
        assert len(r.high_issues) == 2

    def test_review_feedback_passed_flag(self):
        rf = ReviewFeedback(passed=True, iteration=2)
        assert rf.passed is True
        assert rf.iteration == 2


# ─── TestingArtifact ─────────────────────────────────────────────────────────


class TestTestingArtifact:
    def _minimal(self, **kwargs) -> TestingArtifact:
        base: dict = {
            "stage": "architecture",
            "test_cases": [],
            "coverage_areas": ["Auth"],
            "uncovered_areas": [],
            "findings": [],
            "blocking_issues": [],
            "passed": True,
            "recommendations": [],
        }
        base.update(kwargs)
        return TestingArtifact(**base)

    def test_passed_flag_stored(self):
        assert self._minimal(passed=True).passed is True
        assert self._minimal(passed=False).passed is False

    def test_stage_stored(self):
        assert self._minimal(stage="infrastructure").stage == "infrastructure"

    def test_blocking_issues_populated(self):
        a = self._minimal(blocking_issues=["Cannot connect to DB"])
        assert a.blocking_issues == ["Cannot connect to DB"]

    def test_failed_services_defaults_empty(self):
        assert self._minimal().failed_services == []

    def test_http_test_cases_defaults_empty(self):
        assert self._minimal().http_test_cases == []

    def test_test_case_stores_all_fields(self):
        tc = TestCase(
            id="tc001",
            name="Auth flow",
            description="Test JWT auth",
            requirement_covered="User authentication",
            test_type="integration",
            steps=["POST /auth/login", "Extract JWT"],
            expected_outcome="200 OK with JWT",
            status="passed",
        )
        assert tc.id == "tc001"
        assert tc.status == "passed"
        assert len(tc.steps) == 2

    def test_http_test_case_stores_all_fields(self):
        htc = HttpTestCase(
            id="http001",
            name="GET tasks",
            description="Fetch all tasks",
            requirement_covered="CRUD",
            method="GET",
            path="/tasks",
            expected_status=200,
            response_contains=["id", "title"],
        )
        assert htc.method == "GET"
        assert htc.expected_status == 200
        assert htc.status is None  # not yet executed


# ─── GeneratedSpecArtifact ────────────────────────────────────────────────────


class TestGeneratedSpecArtifact:
    def test_all_defaults_are_empty(self):
        spec = GeneratedSpecArtifact()
        assert spec.openapi_spec == ""
        assert spec.database_schema == ""
        assert spec.monorepo_services == []
        assert spec.service_ports == {}
        assert spec.shared_models == []
        assert spec.generated_spec_files == []

    def test_stores_openapi_spec(self):
        spec = GeneratedSpecArtifact(openapi_spec="openapi: '3.0.0'")
        assert spec.openapi_spec == "openapi: '3.0.0'"

    def test_stores_service_ports(self):
        spec = GeneratedSpecArtifact(
            monorepo_services=["backend", "bff"],
            service_ports={"backend": 8081, "bff": 8080},
        )
        assert spec.service_ports["backend"] == 8081
        assert spec.service_ports["bff"] == 8080


# ─── EngineeringArtifact ─────────────────────────────────────────────────────


class TestEngineeringArtifact:
    def test_defaults_are_empty(self):
        eng = EngineeringArtifact()
        assert eng.generated_files == []
        assert eng.services == {}
        assert eng.review_iteration == 1

    def test_coerces_api_endpoints_dicts(self):
        eng = EngineeringArtifact(
            api_endpoints=[{"description": "GET /tasks"}, "POST /tasks"]
        )
        assert eng.api_endpoints == ["GET /tasks", "POST /tasks"]

    def test_file_spec_stores_content(self):
        fs = FileSpec(path="app/main.py", purpose="Entry point", content="# main\n")
        assert fs.path == "app/main.py"
        assert fs.content == "# main\n"

    def test_tech_stack_stores_all_fields(self):
        ts = TechStack(
            framework="FastAPI",
            language="Python",
            version="0.100.0",
            key_libraries=["pydantic", "sqlalchemy"],
            rationale="Fast, modern, type-safe",
        )
        assert ts.framework == "FastAPI"
        assert "pydantic" in ts.key_libraries
