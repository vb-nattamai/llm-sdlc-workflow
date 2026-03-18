# Multi-Agent SDLC Pipeline

> Turn raw requirements into a running full-stack monorepo application — automatically.
> Spec-driven, contract-first, and designed to extend incrementally across your entire SDLC.

A fully automated software development pipeline where specialised AI agents collaborate across every phase: from requirements discovery through system architecture, contract-first spec generation, parallel code generation (Kotlin backend + BFF + React frontend), infrastructure-as-code, automated testing with Cypress, and iterative code review with a feedback loop.

Runs on **GitHub Models** via your **GitHub Copilot licence** — no separate API credits required.

---

## Pipeline Flow

```
  Your Requirements
         │
         ▼
┌──────────────────┐
│ Discovery Agent  │  Analyses goals, constraints, success criteria, risks, scope
└────────┬─────────┘        → 01_intent_artifact.json
         │
         ▼
┌─────────────────────┐  ◄── optional: --spec / --config (OpenAPI, SQL, tech/arch constraints)
│ Architecture Agent  │  Designs components, data flow, API contracts, security model
└────────┬────────────┘        → 02_architecture_artifact.json
         │
         ▼
┌──────────────────────────┐
│ Testing Agent [Stage 1]  │  Verifies architecture satisfies all stated requirements
└────────┬─────────────────┘        → 05a_testing_architecture.json
         │
         ▼
┌─────────────────────┐  ◄── optional: --from-run (extends existing contract)
│    Spec Agent       │  Generates forward contract: OpenAPI 3.0 YAML + SQL DDL
└────────┬────────────┘        → 04_generated_spec_artifact.json + generated/specs/
         │
         ├──────────────────────────────────────────────────┐
         ▼                                                  ▼
┌────────────────────────┐                    ┌────────────────────────┐
│   Engineering Agent    │                    │  Infrastructure Agent  │
│    (orchestrator)      │                    │  (IaC plan, parallel)  │
│                        │                    └────────────────────────┘
│  ┌──────────────────┐  │  Kotlin Spring Boot 3.3, Gradle, JPA, JWT
│  │  Backend Agent   │  │       → backend/
│  └──────────────────┘  │
│  ┌──────────────────┐  │  Kotlin Spring WebFlux, coroutines, calls backend:8081
│  │    BFF Agent     │  │       → bff/
│  └──────────────────┘  │
│  ┌──────────────────┐  │  React 18 + TypeScript 5 + Vite → Nginx, calls bff:8080
│  │ Frontend Agent   │  │       → frontend/
│  └──────────────────┘  │
└────────┬───────────────┘        → 03_engineering_artifact.json
         │
         ▼
┌─────────────────────────────────────────────────┐
│  Review Agent  (loop, up to 3 iterations)       │
│  ↳ critical issues → re-gen Engineering + Infra │
│    in parallel → repeat until passed            │
└────────┬────────────────────────────────────────┘
         │         → 04_review_artifact.json
         ▼
┌──────────────────────────┐
│  Infrastructure Agent    │  Starts containers: docker compose up --build
└────────┬─────────────────┘        → 06_infrastructure_artifact.json
         │
         ▼
┌──────────────────────────┐
│ Testing Agent [Stage 2]  │  Live HTTP tests + Cypress e2e spec generation
└────────┬─────────────────┘        → 05b_testing_infrastructure.json + generated/cypress/
         │
         ▼
┌──────────────────────────┐
│ Testing Agent [Stage 3]  │  Final verification against original requirements
└──────────────────────────┘        → 05c_testing_review.json
```

---

## Agents

| Agent | Role | Output |
|---|---|---|
| **Discovery Agent** | Extracts requirements, goals, constraints, scope, risks, and success criteria from raw text | `IntentArtifact` |
| **Architecture Agent** | Designs the system: components, data flow, API contracts, security model | `ArchitectureArtifact` |
| **Spec Agent** | Generates the **forward contract** (OpenAPI 3.0 + SQL DDL) that all engineering implements against | `GeneratedSpecArtifact` |
| **Engineering Agent** | Orchestrates BE + BFF + FE sub-agents in parallel via `asyncio.gather` | `EngineeringArtifact` |
| ↳ **Backend Agent** | Kotlin 1.9 + Spring Boot 3.3 + Gradle + JPA + JWT — files under `backend/` | `ServiceArtifact` |
| ↳ **BFF Agent** | Kotlin Spring WebFlux + coroutines, calls `backend:8081` — files under `bff/` | `ServiceArtifact` |
| ↳ **Frontend Agent** | React 18 + TypeScript 5 + Vite → Nginx, calls `bff:8080` — files under `frontend/` | `ServiceArtifact` |
| **Infrastructure Agent** | Dockerfiles + docker-compose for the full monorepo stack | `InfrastructureArtifact` |
| **Review Agent** | Security (OWASP), reliability, code quality — feedback loop up to 3× | `ReviewArtifact` |
| **Testing Agent** | 3-stage: architecture plan → live HTTP + Cypress e2e → final sign-off | `TestingArtifact` |

---

## SDLC Coverage

| SDLC Phase | Agent | Status |
|---|---|---|
| Requirements Discovery | Discovery Agent | ✅ Active |
| System Architecture | Architecture Agent | ✅ Active |
| API Contract & Database Design | Spec Agent | ✅ Active |
| Backend Development | Backend Agent | ✅ Active |
| BFF Development | BFF Agent | ✅ Active |
| Frontend Development | Frontend Agent | ✅ Active |
| Infrastructure / IaC | Infrastructure Agent | ✅ Active |
| Code Review & Security Audit | Review Agent | ✅ Active |
| Testing (plan + live HTTP + Cypress e2e) | Testing Agent | ✅ Active |
| API Documentation (Swagger UI, ADRs, runbooks) | Documentation Agent | 🔜 Planned |
| Observability (Prometheus, OpenTelemetry, Grafana) | Observability Agent | 🔜 Planned |
| CI/CD Pipelines (GitHub Actions, K8s, Helm) | Deployment Agent | 🔜 Planned |
| Database Migrations (Flyway / Liquibase) | Migration Agent | 🔜 Planned |
| Performance & Load Testing (k6 / Gatling) | Performance Agent | 🔜 Planned |
| Compliance Checks (GDPR, SOC2, HIPAA) | Compliance Agent | 🔜 Planned |
| Dependency & Vulnerability Scanning (SAST, CVE) | Security Scan Agent | 🔜 Planned |
| Technical Debt & Refactoring | Maintenance Agent | 🔜 Planned |

---

## Human Intelligence Checkpoints

The pipeline is fully automated, but these are the natural **human-in-the-loop** checkpoints where human review adds the most value:

| # | Checkpoint | After Agent | Why Human Input Matters |
|---|---|---|---|
| 1 | **Requirements Validation** | Discovery Agent | Confirm the agent correctly interpreted ambiguous requirements; add tacit domain knowledge the LLM can't know |
| 2 | **Architecture Sign-off** | Architecture Agent | Review strategic technology choices and trade-offs against team expertise, org constraints, and existing systems |
| 3 | **API Contract Approval** | Spec Agent | The OpenAPI + DDL is a **public contract** — once downstream services depend on it, changes are expensive |
| 4 | **Security Review** | Review Agent | LLMs miss context-specific threat models, business-logic exploits, and organisation-specific compliance requirements |
| 5 | **Infrastructure Cost Check** | Infrastructure Agent | Review resource sizing, cloud costs, and network topology before committing to production infrastructure |
| 6 | **User Acceptance Testing** | Testing Agent (Stage 3) | Does the generated system actually solve the original business problem from a user perspective? |
| 7 | **Incremental Contract Approval** | Spec Agent (--from-run) | Before extending a live API contract, a human must confirm which additions are backwards-compatible |

> **Future:** The pipeline will emit a `HUMAN_CHECKPOINT` event at each of these stages so a CI/CD system can pause and request review via GitHub PR comment, Slack message, or JIRA ticket.

---

## Multi-Project Support

The pipeline is **project-agnostic at the specification layer**. The Spec Agent generates a `GeneratedSpecArtifact` (OpenAPI + DDL + constraints) that drives all engineering. The sub-agents implement against this contract.

### Option 1 — Tech constraints flag (no file changes needed)

```bash
python3.11 main.py \
  --requirements reqs.txt \
  --tech-constraints "Python FastAPI, PostgreSQL, Next.js frontend"
```

The Spec Agent propagates these constraints; all sub-agents honour them.

### Option 2 — Edit sub-agent prompts per project

Each agent's behaviour is fully controlled by a plain Markdown file in `prompts/`. No Python changes required.

```
prompts/backend_agent.md     # change Kotlin → Python / Go / Node.js
prompts/bff_agent.md         # change WebFlux → Express / Fastify
prompts/frontend_agent.md    # change React → Vue / Angular / Svelte
```

### Option 3 — Dedicated config file per project (recommended for teams)

```yaml
# my_project/pipeline.yaml
requirements: requirements.txt
output_dir: ./artifacts/my_project

spec:
  tech_constraints: "Go + Gin, React 18, PostgreSQL 16, Redis"
  arch_constraints: "12-factor app, horizontal scaling, JWT auth"
  files:
    - existing_api.yaml    # optional: existing OpenAPI spec to honour
    - schema.sql           # optional: existing DB schema
```

```bash
python3.11 main.py --config my_project/pipeline.yaml
```

Keep one `pipeline.yaml` per project — each file is completely self-contained.

---

## Installation

**Prerequisites:** Python 3.11+, Docker, GitHub account with a Copilot licence, GitHub CLI (`gh`).

```bash
git clone https://github.com/vb-diconium/multi-agent-pipeline.git
cd multi-agent-pipeline
pip install -r requirements.txt
```

### Authentication

The pipeline uses the **GitHub Models API** (OpenAI-compatible endpoint, model: `gpt-4o`) authenticated via your GitHub Copilot token. No `.env` file or additional API credits are needed.

```bash
# One-time: authenticate with GitHub CLI
gh auth login

# Verify (pipeline calls this automatically at startup)
gh auth token
```

---

## Usage

### New Project — from scratch

```bash
# Quickstart: uses the built-in Task Management API example
python3.11 main.py

# Your own requirements file
python3.11 main.py --requirements my_requirements.txt

# With tech-stack constraints
python3.11 main.py \
  --requirements my_requirements.txt \
  --tech-constraints "Kotlin Spring Boot, React 18, PostgreSQL" \
  --output-dir ./artifacts/my_project

# Enter requirements interactively
python3.11 main.py --interactive

# Via config file (recommended for teams)
python3.11 main.py --config pipeline.yaml
```

### Incremental Development — extending an existing contract

Use `--from-run` to load the OpenAPI + DDL from a previous run and extend it rather than generating from scratch. The Spec Agent will:

- Mark all existing API paths with `x-existing: true` — sub-agents must not break them
- Mark existing DB tables `-- EXISTING: DO NOT ALTER`
- Add only new endpoints and tables from the new requirements

```bash
# Run 1 — initial build
python3.11 main.py \
  --requirements v1_requirements.txt \
  --output-dir ./artifacts/run_v1

# Run 2 — add a new feature without breaking the live API
python3.11 main.py \
  --requirements v2_new_feature.txt \
  --from-run ./artifacts/run_v1 \
  --output-dir ./artifacts/run_v2

# Run 3 — another increment on top of run 2
python3.11 main.py \
  --requirements v3_requirements.txt \
  --from-run ./artifacts/run_v2 \
  --output-dir ./artifacts/run_v3
```

The chain is fully composable — every run reads `generated/specs/` from the previous run.

### All CLI Flags

```
--requirements FILE     Path to a requirements text file
--interactive           Type requirements at the terminal (stdin)
--config FILE           Load configuration from a pipeline.yaml file
--spec FILE             Pass a spec file (OpenAPI YAML, SQL DDL, etc.) — repeatable
--tech-constraints STR  Tech stack constraints, e.g. "Python FastAPI, PostgreSQL, Redis"
--arch-constraints STR  Architecture constraints, e.g. "Microservices on Kubernetes"
--from-run DIR          Extend the existing OpenAPI + DDL contract from a previous run directory
--output-dir DIR        Where to write artifacts (default: artifacts/run_YYYYMMDD_HHMMSS)
```

---

## Output Structure

Each run creates a timestamped directory under `artifacts/`:

```
artifacts/run_20260318_120000/
├── 00_pipeline_report.json              # overall pass/fail + summary metrics
├── 01_intent_artifact.json              # Discovery Agent output
├── 02_architecture_artifact.json        # Architecture Agent output
├── 03_engineering_artifact.json         # Engineering Agent (merged) output
├── 03a_backend_artifact.json            # Backend sub-agent output
├── 03b_bff_artifact.json                # BFF sub-agent output
├── 03c_frontend_artifact.json           # Frontend sub-agent output
├── 04_generated_spec_artifact.json      # Spec Agent — forward contract
├── 04_review_artifact.json              # Review Agent output
├── 05a_testing_architecture.json        # Testing: architecture stage
├── 05b_testing_infrastructure.json      # Testing: live HTTP + Cypress stage
├── 05c_testing_review.json              # Testing: final sign-off
├── 06_infrastructure_artifact.json      # Infrastructure Agent output
├── *_agent_history.json                 # full LLM conversation history per agent
└── generated/                           # ← all generated source code + IaC
    ├── backend/                         # Kotlin Spring Boot 3.3 (Gradle)
    │   ├── build.gradle.kts
    │   ├── src/main/kotlin/...
    │   └── Dockerfile
    ├── bff/                             # Kotlin Spring WebFlux
    │   ├── build.gradle.kts
    │   ├── src/main/kotlin/...
    │   └── Dockerfile
    ├── frontend/                        # React 18 + TypeScript 5 + Vite
    │   ├── package.json
    │   ├── src/
    │   ├── nginx.conf
    │   └── Dockerfile
    ├── specs/                           # Forward contract (use with --from-run)
    │   ├── openapi.yaml                 # OpenAPI 3.0 — all endpoints
    │   └── schema.sql                   # SQL DDL — all tables
    ├── cypress/                         # Cypress e2e specs
    │   ├── cypress.config.ts
    │   └── e2e/*.cy.ts
    └── docker-compose.yml               # starts the full monorepo stack
```

The `generated/specs/` directory is what `--from-run` reads on the next run.

---

## Project Structure

```
multi_agent_pipeline/
├── main.py                     # CLI entry point — all flags including --from-run
├── pipeline.py                 # 8-step orchestrator
├── pipeline.yaml               # project config template — copy and edit per project
├── requirements.txt
├── prompts/                    # agent system prompts — edit without touching Python
│   ├── discovery_agent.md      # requirements analyst + product manager persona
│   ├── architecture_agent.md
│   ├── spec_agent.md           # forward contract: OpenAPI + DDL
│   ├── backend_agent.md        # Kotlin Spring Boot 3.3 persona
│   ├── bff_agent.md            # Kotlin Spring WebFlux persona
│   ├── frontend_agent.md       # React 18 + TypeScript 5 persona
│   ├── infrastructure_agent.md
│   ├── review_agent.md
│   └── testing_agent.md
├── agents/
│   ├── base_agent.py           # shared: GitHub Models query, retry, chunked gen, I/O
│   ├── discovery_agent.py      # DiscoveryAgent → IntentArtifact
│   ├── architecture_agent.py
│   ├── spec_agent.py           # forward contract generator
│   ├── engineering_agent.py    # orchestrator → runs BE + BFF + FE in parallel
│   ├── backend_agent.py
│   ├── bff_agent.py
│   ├── frontend_agent.py
│   ├── infrastructure_agent.py
│   ├── review_agent.py
│   └── testing_agent.py
└── models/
    ├── artifacts.py            # all Pydantic models: IntentArtifact, GeneratedSpecArtifact, etc.
    └── __init__.py
```

---

## Customising Prompts

Every agent's behaviour is defined entirely by a Markdown file in `prompts/`. Edit any `.md` file to change persona, output style, or constraints — no Python changes required.

The JSON schema at the bottom of each prompt file defines the artifact structure the agent must return. Keep those schemas intact or update the matching Pydantic model in `models/artifacts.py`.

---

## Roadmap — Planned Agents

| Agent | SDLC Phase | Description |
|---|---|---|
| **DocumentationAgent** | Docs | API docs (Swagger UI config), Architecture Decision Records, runbooks, onboarding guides |
| **ObservabilityAgent** | Ops | Prometheus metrics endpoints, structured logging config, OpenTelemetry tracing setup |
| **DeploymentAgent** | CI/CD | GitHub Actions workflows, Kubernetes manifests, Helm charts, ArgoCD configs |
| **MigrationAgent** | Database | Flyway / Liquibase migration scripts with rollback procedures |
| **PerformanceAgent** | Testing | k6 / Gatling load test scripts, SLA budgets, bottleneck analysis |
| **ComplianceAgent** | Governance | GDPR data map, SOC2 controls checklist, HIPAA PHI handling guide |
| **SecurityScanAgent** | Security | SAST output triage, dependency CVE report, secrets detection |
| **MaintenanceAgent** | Maintenance | Dependency update PRs, technical debt scoring, refactoring recommendations |

---

## How It Works

1. **Chunked LLM generation** — each agent generates files in two LLM calls: first a plan with all content `__PENDING__`, then one call per file to fill it. Prevents token-limit failures on large codebases.

2. **Contract-first spec** — the Spec Agent generates an OpenAPI + DDL contract *before* any code is written. All three engineering sub-agents implement against this single source of truth, ensuring consistency from day one.

3. **Parallel sub-agents** — Backend, BFF, and Frontend agents run via `asyncio.gather`. Infrastructure planning also runs in parallel with Engineering to save time.

4. **Review feedback loop** — the Review Agent runs up to 3 times. If critical issues are found, Engineering and Infrastructure both re-generate in parallel with the feedback applied.

5. **Compact context** — each agent receives a compact summary of upstream artifacts, not raw JSON blobs. Keeps prompts lean and LLM calls fast.

6. **Incremental contracts** — `--from-run` marks existing API paths `x-existing: true` so new runs only add endpoints, never silently break a live API.

7. **Full decision traceability** — every agent appends `DecisionRecord` entries documenting what was decided, why, and what alternatives were rejected. All records are persisted to `*_history.json`.

---

## Requirements

- Python 3.11+
- GitHub CLI (`gh`) authenticated with a GitHub Copilot licence
- Docker (Docker Desktop or Docker Engine) — for the Infrastructure Agent to build and start containers
- Node.js 18+ + `npx` — optional, only needed for running Cypress e2e tests locally
- Python packages: `openai`, `pydantic`, `rich`, `anyio`, `httpx`, `pyyaml`
