# Multi-Agent Software Development Pipeline

A fully automated software development pipeline powered by **Claude** via the Claude Agent SDK. Five specialised AI agents collaborate to turn raw requirements into reviewed, tested code — with every decision documented and traceable.

## Pipeline Flow

```
Your Requirements
       │
       ▼
┌─────────────────┐
│  Intent Agent   │  ── understands goals, constraints, success criteria
└────────┬────────┘        → 01_intent_artifact.json
         │
         ▼
┌─────────────────────┐  ◄── optional: --spec (OpenAPI, DB schema, tech constraints)
│ Architecture Agent  │  ── designs components, data flow, API contracts, security
└────────┬────────────┘       → 02_architecture_artifact.json
         │
         ▼
┌──────────────────────────┐
│ Testing Agent [Stage 1]  │  ── verifies architecture satisfies requirements
└────────┬─────────────────┘       → 05a_testing_architecture.json
         │
         ▼
┌──────────────────────┐  ◄── optional: --spec (honours tech stack + API constraints)
│  Engineering Agent   │  ── selects tech stack, generates runnable code files
└────────┬─────────────┘       → 03_engineering_artifact.json + artifacts/generated/
         │
         ▼
┌──────────────────────────┐
│ Infrastructure Agent     │  ── writes Dockerfile + docker-compose.yml, builds and
│                          │     starts the full container stack (app + DB + cache)
└────────┬─────────────────┘       → 06_infrastructure_artifact.json
         │                          + artifacts/generated/{Dockerfile,docker-compose.yml}
         ▼
┌──────────────────────────┐
│ Testing Agent [Stage 2]  │  ── runs LIVE HTTP tests against the running container,
│                          │     verifying every requirement works end-to-end
└────────┬─────────────────┘       → 05b_testing_infrastructure.json
         │
         ▼
┌───────────────┐
│ Review Agent  │  ── audits for security (OWASP), reliability, code quality
└────────┬──────┘       → 04_review_artifact.json
         │
         ▼
┌──────────────────────────┐
│ Testing Agent [Stage 3]  │  ── final verification against original requirements
└──────────────────────────┘       → 05c_testing_review.json
```

> **Note:** The Testing Agent always derives test cases from the **Intent Artifact** (user requirements) only — never from technical specs. At Stage 2 (infrastructure), it executes real HTTP requests against the running container to verify every requirement end-to-end.

## Features

| Feature | Detail |
|---|---|
| **6 specialised agents** | Intent, Architecture, Engineering, Infrastructure, Review, Testing |
| **Spec-driven development** | Pass OpenAPI specs, DB schemas, tech constraints as hard constraints |
| **Containerised execution** | Infrastructure Agent writes Dockerfile + docker-compose and starts the stack |
| **Live HTTP testing** | Testing Agent makes real HTTP requests against the running container |
| **Persistent artifacts** | Every agent saves typed JSON artifacts to disk |
| **Decision traceability** | Every decision recorded with rationale and alternatives considered |
| **3-stage testing** | Testing Agent runs after Architecture, Infrastructure (live), and Review |
| **Retry logic** | Each agent retries up to 3 times on failure |
| **Claude Pro compatible** | Uses Claude Agent SDK — no separate API credits needed |

## Installation

```bash
git clone https://github.com/vb-diconium/multi-agent-pipeline.git
cd multi-agent-pipeline/multi_agent_pipeline
python3.11 -m pip install -r requirements.txt
```

**Requires:** Claude Code CLI installed and authenticated (Claude Pro subscription).

## Customising Prompts

Each agent's system prompt lives in a plain Markdown file under `prompts/`:

```
prompts/
├── intent_agent.md        # Requirements analyst persona + JSON schema
├── architecture_agent.md  # Principal architect persona + JSON schema
├── engineering_agent.md   # Full-stack engineer persona + JSON schema
├── review_agent.md        # Security/quality reviewer persona + JSON schema
└── testing_agent.md       # QA engineer persona + JSON schema
```

Edit any `.md` file to change how an agent behaves — no Python changes required.
The JSON schema at the bottom of each file defines the artifact structure; keep it intact.

## Usage

### Basic

```bash
# Run with the built-in Task Management API example
python3.11 main.py

# Use your own requirements
python3.11 main.py --requirements my_requirements.txt

# Enter requirements interactively
python3.11 main.py --interactive
```

### Spec-Driven Development via Config File (recommended)

Copy `pipeline.yaml`, fill in the `spec` section, then run:

```bash
python3.11 main.py --config pipeline.yaml
```

```yaml
# pipeline.yaml
requirements: my_requirements.txt
output_dir: ./artifacts

spec:
  tech_constraints: "Python FastAPI, PostgreSQL, Redis, Celery"
  arch_constraints: "Microservices on Kubernetes"
  files:
    - openapi.yaml
    - schema.sql
```

CLI flags always override values from the config file.

### Spec-Driven Development via CLI Flags

```bash
# Provide an OpenAPI spec — Engineering must implement it exactly
python3.11 main.py --requirements reqs.txt --spec openapi.yaml

# Provide a database schema
python3.11 main.py --requirements reqs.txt --spec schema.sql

# Constrain the tech stack
python3.11 main.py --requirements reqs.txt --tech-constraints "Python FastAPI, PostgreSQL, Redis, Celery"

# Architecture constraints
python3.11 main.py --requirements reqs.txt --arch-constraints "Microservices on Kubernetes"

# Combine everything
python3.11 main.py \
  --requirements reqs.txt \
  --spec openapi.yaml \
  --spec schema.sql \
  --tech-constraints "Python FastAPI, PostgreSQL" \
  --arch-constraints "Must run on AWS ECS" \
  --output-dir ./my_artifacts
```

## Output

Each run creates a timestamped directory under `artifacts/`:

```
artifacts/run_20260313_120000/
├── 00_pipeline_report.json          # overall pass/fail + summary metrics
├── 01_intent_artifact.json          # extracted requirements and goals
├── 02_architecture_artifact.json    # system design blueprint
├── 03_engineering_artifact.json     # tech stack + implementation plan
├── 04_review_artifact.json          # quality/security scores and issues
├── 05a_testing_architecture.json    # test cases: architecture stage
├── 05b_testing_infrastructure.json  # test cases: infrastructure stage (live HTTP results)
├── 05c_testing_review.json          # test cases: final stage
├── 06_infrastructure_artifact.json  # IaC files list + container runtime info
├── *_history.json                   # full conversation history per agent
└── generated/                       # generated source code + IaC files
    ├── main.py
    ├── models.py
    ├── routes/
    ├── Dockerfile
    ├── docker-compose.yml
    └── .env.example
```

## Artifact Schema

Every artifact is a validated Pydantic model. Key fields:

**IntentArtifact** — requirements, user_goals, constraints, success_criteria, key_features, risks, decisions

**ArchitectureArtifact** — system_overview, architecture_style, components, data_flow, api_design, database_design, security_design, spec_compliance_notes, design_decisions

**EngineeringArtifact** — backend_tech, frontend_tech, generated_files, implementation_steps, api_endpoints, data_models, spec_compliance_notes, decisions

**InfrastructureArtifact** — iac_files (Dockerfile, docker-compose.yml, .env.example), primary_service_port, health_check_path, service_dependencies, base_url (set at runtime), container_running

**ReviewArtifact** — overall_score (0-100), security_score, reliability_score, issues (with CWE IDs), strengths, critical_fixes_required, passed

**TestingArtifact** — test_cases (static, mapped to requirements), http_test_cases (live HTTP results at infrastructure stage), coverage_areas, uncovered_areas, blocking_issues, passed

## Project Structure

```
multi_agent_pipeline/
├── main.py                   # entry point + CLI argument parsing
├── pipeline.py               # orchestrator that runs all agents in sequence
├── pipeline.yaml             # spec-driven development config (copy & edit)
├── requirements.txt
├── prompts/                  # agent system prompts — edit without touching Python
│   ├── intent_agent.md
│   ├── architecture_agent.md
│   ├── engineering_agent.md
│   ├── infrastructure_agent.md
│   ├── review_agent.md
│   └── testing_agent.md
├── agents/
│   ├── base_agent.py         # shared: Agent SDK query, retry, compact context, artifact I/O
│   ├── intent_agent.py
│   ├── architecture_agent.py
│   ├── engineering_agent.py
│   ├── infrastructure_agent.py
│   ├── review_agent.py
│   └── testing_agent.py
└── models/
    ├── artifacts.py          # all Pydantic artifact models incl. SpecArtifact
    └── __init__.py
```

## How It Works

1. **Each agent gets a compact summary** of upstream artifacts (not raw JSON blobs) — keeps prompts lean and fast.
2. **Specs flow to Architecture + Engineering** as hard constraints via `SpecArtifact`.
3. **Testing Agent is spec-agnostic** — it always verifies against the original user intent.
4. **All decisions are recorded** — every agent appends `DecisionRecord` entries documenting what was decided, why, and what alternatives were rejected.
5. **History is persisted** — each agent saves its full conversation history alongside the artifact.

## Requirements

- Python 3.11+
- Claude Code CLI (`claude --version` should work)
- Claude Pro subscription (authenticated via `claude` CLI)
- **Docker** (Docker Desktop or Docker Engine) — required for the Infrastructure Agent to build and run containers
- Dependencies: `claude-agent-sdk`, `pydantic`, `rich`, `anyio`, `httpx`
