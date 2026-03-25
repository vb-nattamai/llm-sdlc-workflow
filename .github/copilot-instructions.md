# GitHub Copilot Instructions — LLM SDLC Workflow

This is a **spec-driven, multi-agent AI pipeline** that turns plain requirements text into a
running full-stack application (code + Dockerfiles + CI/CD). Every contribution must preserve
the pipeline's end-to-end correctness and the contract between agents.

---

## 1. Codebase Map

```
main.py                             CLI entry-point (argparse + async_main)
pipeline.yaml                       Project-level config (auto-loaded from CWD)
llm_sdlc_workflow/
  pipeline.py                       Orchestrator — runs all agents in sequence/parallel
  config.py                         PipelineConfig, ComponentConfig, TechConfig, TopologyContract
  agents/
    base_agent.py                   BaseAgent: _run_with_retry, _self_heal, _query_and_parse_chunked,
                                    _patch_files_chunked, _emit_event, save_artifact
    discovery_agent.py              Phase 1: requirements → DiscoveryArtifact
    architecture_agent.py           Phase 2: design → ArchitectureArtifact
    spec_agent.py                   Phase 3: OpenAPI + DDL → GeneratedSpecArtifact
    engineering_agent.py            Phase 4 (orchestrator): spawns BE/BFF/FE/Mobile sub-agents
    backend_agent.py                Sub-agent: configurable backend code
    bff_agent.py                    Sub-agent: BFF layer (opt-in)
    frontend_agent.py               Sub-agent: configurable frontend (opt-in)
    mobile_agent.py                 Sub-agent: configurable mobile platforms (opt-in)
    infrastructure_agent.py         IaC: Dockerfile + docker-compose (tech-stack-aware)
    deployment_agent.py             GitHub Actions, K8s manifests, Helm
    review_agent.py                 Security + quality review loop
    testing_agent.py                3-stage: arch plan → live tests (tool-adaptive) → final sign-off
  models/
    artifacts.py                    All Pydantic v2 models — DiscoveryArtifact … DeploymentArtifact
  prompts/
    <agent_name>.md                 System prompts — one file per agent
  config.py                         PipelineConfig / ComponentConfig / TechConfig
tests/
  test_agents.py, test_base_agent.py, test_more_agents.py, test_service_agents.py
  test_artifacts.py                 Pydantic model validation and coercion tests
  test_pipeline.py                  Pipeline orchestration and decision log tests
  test_topology_contract.py         TopologyContract.from_config() tests
```

> **Note on package path**: the Python package root is `llm_sdlc_workflow/` (no `src/` prefix).
> All imports use `from llm_sdlc_workflow.agents.xxx import ...` — never `src.llm_sdlc_workflow`.

---

## 2. Agent Pattern

Every agent follows this pattern:

```python
class MyAgent(BaseAgent):
    async def run(self, intent: DiscoveryArtifact, ...) -> MyArtifact:
        artifact = await self._query_and_parse_chunked(
            system=SYSTEM_PROMPT,
            plan_message="...",           # ask LLM to list files with __PENDING__ content
            file_keys=["generated_files"],
            model_class=MyArtifact,
            fill_message_tmpl="...",       # ask LLM to fill one file at a time
            fill_context={...},
        )
        self.save_artifact(artifact, "XX_my_artifact.json")  # always before save_history()
        self.save_history()
        return artifact
```

**Call order**: `save_artifact()` must always be called before `save_history()`. If the process
crashes between the two, the artifact is preserved and the run can be resumed.

**Chunked generation** (plan → fill per file) prevents token-limit failures.  
**`_self_heal()`** inside `_query_and_parse()` re-asks the LLM on JSON/validation failure.  
**`_patch_files_chunked()`** is used during review iterations — sends *current file content*
plus *specific issues* so the LLM makes surgical fixes instead of full rewrites.  
**`_patch_files_chunked()` is also valid outside the review loop** — any agent that needs to
incrementally update previously generated files may use it (e.g. infrastructure patching after
an engineering sub-agent completes).

---

## 3. Key Models (artifacts.py)

All artifacts are **Pydantic v2** models with `_coerce_str_list` validators.

| Model | JSON file | Key fields |
|---|---|---|
| `DiscoveryArtifact` | `01_discovery_artifact.json` | `requirements`, `features`, `decisions` |
| `ArchitectureArtifact` | `02_architecture_artifact.json` | `components`, `architecture_style` |
| `EngineeringArtifact` | `03_engineering_artifact.json` | `generated_files`, `services`, `review_iteration` |
| `GeneratedSpecArtifact` | `04_generated_spec_artifact.json` | `spec_files`, `service_ports` |
| `InfrastructureArtifact` | `06a/b_infrastructure_*_artifact.json` | `iac_files`, `base_url`, `container_running` |
| `ReviewArtifact` | `04_review_artifact_iter<N>.json` | `critical_issues`, `high_issues`, `passed`, `overall_score` |
| `TestingArtifact` | `05a/b/c_testing_*.json` | `http_test_cases`, `blocking_issues`, `passed` |

> **Artifact numbering**: Engineering (03) is generated before the OpenAPI spec (04) because the
> spec is derived from the discovered architecture, not produced first. The numbering reflects
> pipeline sequence, not logical dependency order.

**Coercion rule**: Any field that might come back from the LLM as a list of dicts (instead of
strings) must have a `_coerce_str_list` validator. See `ReviewFeedback` base class for the
pattern — subclasses inherit it automatically.

**`test_tool_files`** holds whatever test artifacts the testing agent produces. The specific
tools used (httpx, pytest, Playwright, or others) are determined by `TestingArtifact` at
runtime based on the generated stack — there is no fixed test runner. Do not hardcode any
specific framework in the testing agent or its prompts.

---

## 4. Configuration System

```
pipeline.yaml  ──►  _apply_config(args)  ──►  PipelineConfig
CLI flags      ──►  parse_args()         ──►  PipelineConfig
```

### pipeline.yaml schema

`pipeline.yaml` is auto-loaded from the current working directory. Valid keys:

```yaml
components:
  bff: false          # bool — enables BFF sub-agent
  frontend: false     # bool — enables frontend sub-agent
  mobile: false       # bool — enables mobile sub-agent

tech:
  backend_language: python          # str — passed to BackendAgent and InfrastructureAgent
  backend_framework: fastapi        # str — passed to BackendAgent and InfrastructureAgent

pipeline:
  max_review_iterations: 3         # int — max review/patch cycles
  model: claude-haiku-4-5-20251001 # str — overrides PIPELINE_MODEL env var
```

All keys are optional. Missing keys fall back to CLI flags, then to code defaults.

### CLI defaults (API-only by default)
- BFF disabled unless `--bff` flag or `pipeline.yaml: components.bff: true`
- Frontend disabled unless `--frontend` flag or `pipeline.yaml: components.frontend: true`
- `--no-bff` and `--no-frontend` still accepted for backward compatibility

### Python API defaults (full-stack)
`ComponentConfig(bff=True, frontend=True)` — the Python API is backward-compatible.
The API-only default lives only in `main.py`'s CLI layer **and** in `PipelineConfig.from_dict()`
(which is used when loading `pipeline.yaml`).  Calling `PipelineConfig()` directly (Python API)
still defaults to full-stack via the `ComponentConfig` dataclass defaults.

### Tech stack propagation
1. `TechConfig.backend_language / backend_framework` → `BackendAgent(language=..., framework=...)`
2. `PipelineConfig` is passed to `InfrastructureAgent(config=...)` so Dockerfiles match the stack
3. `InfrastructureAgent._tech_hint` is injected into **every** IaC file prompt and **every**
   patch feedback prompt — without it, the LLM may drift from the specified tech stack

### TopologyContract
Computed from `PipelineConfig` by `TopologyContract.from_config()`. Injected into agent prompts
to give the LLM an authoritative view of ports, inter-service URLs, and which services exist.

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `PIPELINE_BASE_URL` | Yes | Anthropic-compatible API base URL |
| `PIPELINE_API_KEY` | Yes | API key |
| `PIPELINE_MODEL` | Yes | Model string (e.g. `claude-haiku-4-5-20251001`) |

No other environment variables drive agent behaviour. Rate limiting, timeouts, and retry counts
are configured in code via `BaseAgent` constants.

---

## 5. Engineering Sub-Agent Coordination

`EngineeringAgent` is the orchestrator for Phase 4. It spawns sub-agents based on active
`ComponentConfig` flags:

```
EngineeringAgent
  ├── BackendAgent          (always runs)
  ├── BffAgent              (runs if config.components.bff is True)
  ├── FrontendAgent         (runs if config.components.frontend is True)
  └── MobileAgent           (runs if config.components.mobile is True)
```

Each sub-agent produces its own partial `generated_files` dict. `EngineeringAgent` merges
them into a single `EngineeringArtifact` after all sub-agents complete. If a sub-agent is
disabled, its files are simply absent from the merged artifact — no placeholders are written.

---

## 6. Review Loop

```python
for iteration in range(1, self.config.max_review_iterations + 1):   # default 3, overridable
    review = await review_agent.run(...)
    if review.passed: break
    engineering, infra = await asyncio.gather(
        engineering_agent.apply_review_feedback(...),
        infrastructure_agent.apply_review_feedback(...),
    )
```

### Pass/fail definition
`review.passed` is computed **deterministically** by a `@model_validator` on `ReviewArtifact`
— the LLM-provided value is overridden immediately on deserialization:
```python
def _enforce_passed(self) -> "ReviewArtifact":
    self.passed = (self.overall_score >= 70) and (len(self.critical_issues) == 0)
```
The two required conditions:
- `overall_score >= 70`
- `critical_issues == []`

`overall_score` is a **deterministic formula**: start 100, deduct 15/critical, 8/high,
3/medium, 1/low per dimension, weighted average (security×0.35, reliability×0.25,
maintainability×0.25, performance×0.15).

### Patching behaviour
`apply_review_feedback` uses `_patch_files_chunked` — it always includes the **current file
content** so the LLM does surgical fixes, not rewrites. `spec_context` in
`_patch_files_chunked` injects the OpenAPI spec and tech stack hint so the LLM never forgets
the target language/framework between iterations.

---

## 7. Testing Agent

The testing agent is **adaptive** — it does not require or assume any specific test framework.
The test tools used are determined by what `TestingArtifact` specifies, which in turn depends
on what the engineering and infrastructure agents produced.

**Stage flow**:
1. **Arch plan** — determine which services exist and what endpoints to cover
2. **Live tests** — execute tests against the running stack using whatever tool fits (e.g.
   `httpx` for pure API projects, Playwright for frontend, pytest for unit tests)
3. **Final sign-off** — evaluate blocking issues and set `passed`

**Do not hardcode `cypress_spec_files`** or any other framework-specific field in the testing
agent or its prompts. If a field like `cypress_spec_files` exists in the model for backward
compatibility, it must always be set to `[]` and must never be populated.

`TestingArtifact.passed` is `True` when `blocking_issues == []`.

---

## 8. Adding a New Agent

1. Create `llm_sdlc_workflow/agents/my_agent.py` extending `BaseAgent`
2. Create `llm_sdlc_workflow/prompts/my_agent.md` system prompt (see prompt contract below)
3. Add artifact model(s) in `models/artifacts.py` with `_coerce_str_list` validators
4. Wire it into `pipeline.py` at the correct step
5. Add tests in `tests/test_agents.py` and/or `tests/test_more_agents.py`

### System prompt contract

Each `prompts/<agent_name>.md` must include:

- `## Role` — one-sentence description of the agent's responsibility
- `## Output format` — exact JSON schema the agent must return (matches the Pydantic model)
- `## Constraints` — hard rules (e.g. "never output Kotlin unless explicitly requested", "always use the provided ports")

The following template variables are injected at runtime by the agent and **must not** be
hardcoded in the prompt file:

| Variable | Source |
|---|---|
| `{topology_contract}` | `TopologyContract.from_config()` |
| `{tech_hint}` | `InfrastructureAgent._tech_hint` (infra prompts only) |
| `{spec_context}` | OpenAPI spec + tech stack (patch prompts only) |

---

## 9. Running the Pipeline

```bash
# Minimal (API-only, configurable tech stack)
PIPELINE_BASE_URL="https://api.anthropic.com/v1" \
PIPELINE_API_KEY="$ANTHROPIC_API_KEY" \
PIPELINE_MODEL="claude-haiku-4-5-20251001" \
python3.11 main.py --requirements examples/status_api_requirements.txt \
  --project-name my_project --auto

# Full stack (BFF + frontend enabled)
python3.11 main.py --requirements reqs.txt --bff --frontend --auto

# Resume a failed run from spec stage
# The directory must contain the JSON artifacts from all completed stages
python3.11 main.py --resume-from artifacts/my_run_20260324_123456 --resume-stage spec

# Load a custom config file explicitly
python3.11 main.py --config my_pipeline.yaml --requirements reqs.txt
```

`pipeline.yaml` is **auto-loaded from the current working directory** — no `--config` flag needed.

### Resume directory requirements
The `--resume-from` directory must contain the JSON artifact files for every stage that
completed before the failure. For example, resuming from `--resume-stage spec` requires
`01_discovery_artifact.json` and `02_architecture_artifact.json` to be present. The pipeline
will not re-run completed stages.

---

## 10. Testing the Codebase

```bash
# All tests
python3.11 -m pytest tests/ -q

# Only topology contract tests
python3.11 -m pytest tests/test_topology_contract.py -v

# Only a specific class
python3.11 -m pytest tests/test_more_agents.py::TestInfrastructureAgent -v
```

- Total: **325 tests** — all must pass before committing
- Tests use `unittest.mock.AsyncMock` for LLM API calls — no real API calls in CI
- `conftest.py` patches `_run_with_retry` globally with a fixture that returns fixture JSON.
  If you add a new agent and its tests are making real API calls, check that your test class
  inherits the conftest fixture correctly.
- Topology contract tests use explicit `ComponentConfig(bff=True/False)` — do not rely on
  the default value, as defaults differ between CLI and Python API contexts.

---

## 11. Invariants — Never Break These

| Rule | Where enforced |
|---|---|
| `save_artifact()` called before `save_history()` | Every agent's `run()` method |
| `InfrastructureAgent` uses `self._tech_hint` in **all** prompts | `infrastructure_agent.py` plan_message + fill_message_tmpl + apply_review_feedback spec_context |
| Review feedback patch includes current file content | `_patch_files_chunked` in `base_agent.py` |
| Every Pydantic model has `_coerce_str_list` for list-of-str fields | `models/artifacts.py` |
| `_self_heal()` is called on JSON/validation parse failure | `base_agent._query_and_parse()` |
| `_write_decision_log()` called after every stage | `pipeline.py` after each `_print_decisions()` |
| `pipeline.yaml` is auto-loaded from CWD | `main.py _apply_config()` |
| Testing agent does not hardcode a test framework | `testing_agent.py` + `prompts/testing_agent.md` |
| `cypress_spec_files` (if present in model) always `[]` | `testing_agent.py` stage_instruction + `_patch_files_chunked` spec_context |
| All imports use `llm_sdlc_workflow.*` (no `src.` prefix) | All source files and tests |
| `ReviewArtifact.passed` is always computed by `_enforce_passed` | `models/artifacts.py` — never set manually |
| Review loop uses `self.config.max_review_iterations` not a hard-coded constant | `pipeline.py` |

---

## 12. Common Mistakes

- **`PipelineConfig.from_dict()` defaults to API-only**: `from_dict()` sets `bff=False,
  frontend=False` when those keys are absent in the YAML. Do NOT change these defaults;
  they mirror the CLI API-only behaviour. Only `ComponentConfig()` (direct Python API)
  defaults to full-stack.

- **`max_review_iterations` is now in `PipelineConfig`**: use `self.config.max_review_iterations`
  in pipeline code, never the old module-level `MAX_REVIEW_ITERATIONS` constant.

- **Only edit `ReviewArtifact.passed` via `_enforce_passed`**: do not set `passed` manually.
  The validator runs on every deserialization and overrides any LLM-provided value.

- **Tech stack drift between iterations**: if `InfrastructureAgent` doesn't receive `config=`,
  `self._tech_hint` defaults to empty string. Always pass `config=self.config`
  from `Pipeline.__init__`.

- **LLM returns list of dicts for a str field**: add `_coerce_str_list` validator; see
  `ReviewFeedback` for the pattern.

- **BFF/frontend appearing unexpectedly**: check whether `_apply_config()` is being called
  before `PipelineConfig` is built. The `async_main` pipeline config uses
  `bff=getattr(args, "bff", False)` — not `True` — when running via CLI.

- **`_patch_files_chunked` regenerating instead of patching**: the `spec_context` must include
  both the OpenAPI spec *and* the tech stack hint, otherwise the LLM ignores the existing code.

- **Test failures after changing `ComponentConfig` defaults**: the Python direct API defaults
  are `bff=True, frontend=True` (set in the `ComponentConfig` dataclass). `from_dict()` now
  defaults to `bff=False, frontend=False`. Tests that call `PipelineConfig.from_dict({})` will
  get API-only config. Tests calling `PipelineConfig()` get full-stack. Be explicit in tests.

- **Wrong import path**: the package is `llm_sdlc_workflow`, not `src.llm_sdlc_workflow`.
  Any import using the `src.` prefix will fail at runtime and in tests.

- **New test making real API calls**: ensure your test class picks up the `conftest.py`
  `_run_with_retry` patch. The patch is applied globally, but class-level mocking that
  re-patches the method without the fixture will bypass it.

- **Assuming a specific test tool in the testing agent**: the testing agent must remain
  tool-agnostic. Use `TestingArtifact.test_tool_files` and let the artifact specify the
  runner. Do not reference `cypress`, `jest`, or any other specific framework in agent
  code or prompts.