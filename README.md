# LLM SDLC Workflow

> Turn raw requirements into a running full-stack monorepo application — automatically.
> Spec-driven, contract-first, and designed to extend incrementally across your entire SDLC.

A fully automated software development pipeline where specialised AI agents collaborate across every phase: from requirements discovery through system architecture, contract-first spec generation, parallel code generation, infrastructure-as-code, automated testing with Cypress, and iterative code review with a feedback loop.

The pipeline is **fully configurable**: choose which services to generate (backend, BFF, frontend, mobile), override the language and framework for each service, and tune everything from a single `pipeline.yaml` or via CLI flags — no Python changes required.

Runs on **GitHub Models** via your **GitHub Copilot licence** — no separate API credits required.

---

## Pipeline Flow

```
  Your Requirements
         │
         ▼
┌──────────────────────┐
│   Discovery Agent    │  Extracts requirements, goals, constraints, risks, scope
└──────────┬───────────┘  → 01_discovery_artifact.json
           │
           ▼
┌──────────────────────┐  ◄── optional: --spec / --config (OpenAPI, SQL, constraints)
│  Architecture Agent  │  Designs components, data flow, API contracts, security model
└──────────┬───────────┘  → 02_architecture_artifact.json
           │
           ▼
  ┌─────────────────────────────────────────────────────────────┐
  │           Testing Agent  [Stage 1 — Architecture]           │
  │  Verifies architecture + spec satisfy all requirements      │
  └─────────────────────────────────────────────────────────────┘
           │  → 05a_testing_architecture.json
           │
           │  ✗ blocking issues found?
           │  ╔═══════════════════════════════════════════════════════╗
           │  ║  Architecture fix loop                                ║
           │  ║  Testing finds gaps → Architecture Agent              ║
           │  ║  redesigns affected components and re-runs Stage 1    ║
           │  ║  until no blockers remain                             ║
           │  ╚═══════════════════╤═════════════════════════════════╝ ║
           │  ✓ all clear         │ (feedback applied, loop back)      ║
           ▼                      └────────────────────────────────────╝
           │
           ▼
┌──────────────────────┐  ◄── optional: --from-run (extends existing contract)
│     Spec Agent       │  Generates forward contract: OpenAPI 3.0 YAML + SQL DDL
└──────────┬───────────┘  → 04_generated_spec_artifact.json + generated/specs/
           │
           ├────────────────────────────────────────────┐
           ▼                                            ▼
┌────────────────────────────────┐     ┌───────────────────────────┐
│      Engineering Agent         │     │   Infrastructure Agent    │
│       (orchestrator)           │     │   (IaC plan — parallel)   │
│                                │     └───────────────────────────┘
│  ┌──────────────────────────┐  │
│  │  Backend Agent           │  │  Language/framework — configurable
│  └──────────────────────────┘  │  → backend/
│  ┌──────────────────────────┐  │
│  │  BFF Agent   [optional]  │  │  Configurable
│  └──────────────────────────┘  │  → bff/
│  ┌──────────────────────────┐  │
│  │  Frontend Agent[optional]│  │  Configurable
│  └──────────────────────────┘  │  → frontend/
│  ┌──────────────────────────┐  │
│  │  Mobile Agent  [opt-in]  │  │  React Native / Flutter / Swift / Kotlin
│  └──────────────────────────┘  │  → mobile_<platform>/
└───────────────┬────────────────┘  → 03_engineering_artifact.json
                │
                ▼
  ╔═════════════════════════════════════════════════════════════════╗
  ║                    Review Loop                                  ║
  ║                                                                 ║
  ║   ┌─────────────────────────────────────────────────────────┐  ║
  ║   │                   Review Agent                           │  ║
  ║   │   Security (OWASP) · Reliability · Code Quality · Perf  │  ║
  ║   │          → 04_review_artifact_iter<N>.json              │  ║
  ║   └────────────────────────┬────────────────────────────────┘  ║
  ║                            │                                    ║
  ║             ┌──────────────┴────────────────┐                  ║
  ║             ▼                               ▼                  ║
  ║   ✓ passed                      ✗ critical or high issues      ║
  ║   (no critical/high)                        │                  ║
  ║             │                               ▼                  ║
  ║             │              ┌────────────────────────────────┐  ║
  ║             │              │  Engineering Agent  (re-gen)   │  ║
  ║             │              │  + Infrastructure Agent (plan) │  ║
  ║             │              │    both run in parallel        │  ║
  ║             │              └───────────────┬────────────────┘  ║
  ║             │                              │ feedback applied   ║
  ║             │                              └──► Review Agent    ║
  ║             │                                  (next iteration) ║
  ╚═════════════╪═════════════════════════════════════════════════╝ ║
                │  ✓ review clean (no critical/high issues left)    ║
                ▼                                                   ║
  ┌─────────────────────────────────────────────────────────────┐  ║
  │   Infrastructure Agent  ┐                                   │  ║
  │   Deployment Agent      ┘   parallel                        │  ║
  │                                                             │  ║
  │  • Infrastructure: docker compose up --build                │  ║
  │  • Deployment: GitHub Actions CI/CD + K8s manifests + Helm  │  ║
  │                canary (10 → 25 → 50 → 100 %)               │  ║
  │                blue-green (atomic kubectl patch switch)     │  ║
  └──────────────────────────┬──────────────────────────────────┘  ║
    → 06b_infrastructure_apply_artifact.json                        ║
    → 07_deployment_artifact.json + generated/deployment/           ║
                             │                                      ║
                             ▼                                      ║
  ╔═════════════════════════════════════════════════════════════════╣
  ║            Testing Loop  [Stage 2 — Infrastructure]            ║
  ║                                                                 ║
  ║   ┌─────────────────────────────────────────────────────────┐  ║
  ║   │                   Testing Agent                          │  ║
  ║   │     Live HTTP tests + Cypress e2e spec generation        │  ║
  ║   │           → 05b_testing_infrastructure.json             │  ║
  ║   └────────────────────────┬────────────────────────────────┘  ║
  ║                            │                                    ║
  ║             ┌──────────────┴────────────────┐                  ║
  ║             ▼                               ▼                  ║
  ║   ✓ all services pass           ✗ services failing             ║
  ║             │                               │                  ║
  ║             │                               ▼                  ║
  ║             │              ┌────────────────────────────────┐  ║
  ║             │              │  Engineering Agent             │  ║
  ║             │              │  (re-gen failed services only) │  ║
  ║             │              │  + Infrastructure Agent        │  ║
  ║             │              │  (restart containers)          │  ║
  ║             │              └───────────────┬────────────────┘  ║
  ║             │                              │ retry (up to 2×)  ║
  ║             │                              └──► Testing Stage 2 ║
  ╚═════════════╪═════════════════════════════════════════════════╝
                │  ✓ live tests pass
                │    + generated/cypress/ Cypress e2e specs written
                ▼
  ┌─────────────────────────────────────────────────────────────┐
  │         Testing Agent  [Stage 3 — Final Sign-off]           │
  │   Final verification against original requirements          │
  └─────────────────────────────────────────────────────────────┘
                   → 05c_testing_review.json
```

---

## Agents

| Agent | Role | Output |
|---|---|---|
| **Discovery Agent** | Extracts requirements, goals, constraints, scope, risks, and success criteria from raw text | `DiscoveryArtifact` |
| **Architecture Agent** | Designs the system: components, data flow, API contracts, security model | `ArchitectureArtifact` |
| **Spec Agent** | Generates the **forward contract** (OpenAPI 3.0 + SQL DDL) that all engineering implements against | `GeneratedSpecArtifact` |
| **Engineering Agent** | Orchestrates BE + BFF + FE sub-agents in parallel via `asyncio.gather` | `EngineeringArtifact` |
| ↳ **Backend Agent** | Kotlin 1.9 + Spring Boot 3.3 + Gradle + JPA + JWT — files under `backend/` | `ServiceArtifact` |
| ↳ **BFF Agent** | Kotlin Spring WebFlux + coroutines, calls `backend:8081` — files under `bff/` | `ServiceArtifact` |
| ↳ **Frontend Agent** | React 18 + TypeScript 5 + Vite → Nginx, calls `bff:8080` — files under `frontend/` | `ServiceArtifact` |
| ↳ **Mobile Agent** | React Native (Expo SDK 51) by default; supports Flutter, Swift, Kotlin — files under `mobile/`. Opt-in via `--mobile` or `components.mobile: true` | `ServiceArtifact` |
| **Infrastructure Agent** | Dockerfiles + docker-compose for the full monorepo stack | `InfrastructureArtifact` |
| **Deployment Agent** | GitHub Actions CI/CD workflows, Kubernetes manifests, Helm chart, blue-green + canary strategies, rollback scripts | `DeploymentArtifact` |
| **Review Agent** | Security (OWASP), reliability, code quality — feedback loop until no critical/high issues | `ReviewArtifact` |
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
| Mobile Development (React Native, Flutter, Swift, Kotlin) | Mobile Agent | ✅ Active (opt-in) |
| Infrastructure / IaC | Infrastructure Agent | ✅ Active |
| Code Review & Security Audit | Review Agent | ✅ Active |
| Testing (plan + live HTTP + Cypress e2e) | Testing Agent | ✅ Active |
| API Documentation (Swagger UI, ADRs, runbooks) | Documentation Agent | 🔜 Planned |
| Observability (Prometheus, OpenTelemetry, Grafana) | Observability Agent | 🔜 Planned |
| CI/CD Pipelines (GitHub Actions, K8s, Helm, canary + blue-green) | Deployment Agent | ✅ Active |
| Database Migrations (Flyway / Liquibase) | Migration Agent | 🔜 Planned |
| Performance & Load Testing (k6 / Gatling) | Performance Agent | 🔜 Planned |
| Compliance Checks (GDPR, SOC2, HIPAA) | Compliance Agent | 🔜 Planned |
| Dependency & Vulnerability Scanning (SAST, CVE) | Security Scan Agent | 🔜 Planned |
| Technical Debt & Refactoring | Maintenance Agent | 🔜 Planned |

---

## Configuring the Pipeline

By default the pipeline generates a full Kotlin/Spring Boot backend, Kotlin/Spring WebFlux BFF, and React 18/TypeScript frontend. Everything is overridable — with CLI flags, `pipeline.yaml`, or Python API — and no code changes are ever required.

### Component Toggles

Control which service sub-agents run:

| Flag | pipeline.yaml | Effect |
|---|---|---|
| _(default)_ | `components.bff: true` | BFF sub-agent enabled |
| `--no-bff` | `components.bff: false` | BFF disabled — useful for API-only or mobile-first projects |
| _(default)_ | `components.frontend: true` | Frontend sub-agent enabled |
| `--no-frontend` | `components.frontend: false` | Frontend disabled — API-only or mobile project |
| `--mobile` | `components.mobile_platforms: ["React Native"]` | Single React Native mobile app |
| `--mobile-platform P` | `components.mobile_platforms: [P]` | Single platform of your choice |
| `--mobile-platform P1 --mobile-platform P2` | `components.mobile_platforms: [P1, P2]` | **Multiple platforms in parallel** |

### Tech-Stack Preferences

Override the language and/or framework for any service:

| Flag | pipeline.yaml key | Default |
|---|---|---|
| `--backend-lang LANG` | `tech.backend_language` | Kotlin |
| `--backend-framework FW` | `tech.backend_framework` | Spring Boot 3.3 |
| `--bff-lang LANG` | `tech.bff_language` | Kotlin |
| `--bff-framework FW` | `tech.bff_framework` | Spring WebFlux |
| `--frontend-framework FW` | `tech.frontend_framework` | React 18 |
| `--frontend-lang LANG` | `tech.frontend_language` | TypeScript |
| `--mobile-platform PLAT` | `components.mobile_platforms: [PLAT]` | React Native (when `--mobile` is set) |

### Common Configurations

#### Pure API project (no BFF, no frontend)

```bash
python3.11 main.py \
  --requirements reqs.txt \
  --no-bff \
  --no-frontend
```

or in `pipeline.yaml`:

```yaml
components:
  bff: false
  frontend: false
```

#### Python/FastAPI backend

```bash
python3.11 main.py \
  --requirements reqs.txt \
  --backend-lang Python \
  --backend-framework FastAPI
```

#### Go + Gin backend, Vue frontend

```bash
python3.11 main.py \
  --requirements reqs.txt \
  --backend-lang Go \
  --backend-framework Gin \
  --frontend-framework Vue
```

#### Full stack + React Native mobile app

```bash
python3.11 main.py \
  --requirements reqs.txt \
  --mobile
# Generates mobile_react_native/ — React Native (Expo SDK 51) app
# connecting to BFF via BFF_BASE_URL env var
```

#### Full stack + Flutter mobile

```bash
python3.11 main.py \
  --requirements reqs.txt \
  --mobile-platform Flutter
```

#### iOS **and** Android native — generated in parallel

```bash
python3.11 main.py \
  --requirements reqs.txt \
  --mobile-platform "iOS (Swift)" \
  --mobile-platform "Android (Kotlin)"
# Runs two MobileAgents in parallel via asyncio.gather
# Outputs: mobile_ios_swift/ and mobile_android_kotlin/
```

#### All three mobile targets at once

```bash
python3.11 main.py \
  --requirements reqs.txt \
  --mobile-platform "React Native" \
  --mobile-platform "iOS (Swift)" \
  --mobile-platform "Android (Kotlin)"
```

#### Node.js/NestJS BFF, no mobile

```bash
python3.11 main.py \
  --requirements reqs.txt \
  --bff-lang Node.js \
  --bff-framework NestJS
```

### pipeline.yaml — Full Configuration Reference

All configuration options live in one file. CLI flags always override `pipeline.yaml` values.

```yaml
# pipeline.yaml

# ─── Component Toggles ───────────────────────────────────────────────────────
components:
  backend: true      # Set false to... why would you?
  bff: true          # Set false for API-only or mobile-only projects
  frontend: true     # Set false for API-only or mobile-only projects

  # mobile_platforms: list of platforms to generate in parallel.
  # Empty (or omit) = mobile disabled.
  # Each entry spawns one MobileAgent; all run concurrently via asyncio.gather.
  # Outputs land in: generated/mobile_react_native/, generated/mobile_ios_swift/, etc.
  mobile_platforms: []
  # mobile_platforms: ["React Native"]
  # mobile_platforms: ["iOS (Swift)", "Android (Kotlin)"]
  # mobile_platforms: ["Flutter"]
  # mobile_platforms: ["React Native", "iOS (Swift)", "Android (Kotlin)"]

# ─── Tech-Stack Preferences ──────────────────────────────────────────────────
# Leave null to use each agent's built-in default.
tech:
  # Backend (default: Kotlin / Spring Boot 3.3)
  backend_language: null     # "Python" | "Go" | "Node.js" | "Java" | ...
  backend_framework: null    # "FastAPI" | "Gin" | "Express" | "Spring Boot" | ...

  # BFF (default: Kotlin / Spring WebFlux)
  bff_language: null         # "Node.js" | "Kotlin" | ...
  bff_framework: null        # "NestJS" | "Spring WebFlux" | ...

  # Frontend (default: React 18 / TypeScript / Vite)
  frontend_framework: null   # "Vue" | "Angular" | "Next.js" | "Svelte" | ...
  frontend_language: null    # "TypeScript" | "JavaScript"

  # Note: mobile platform(s) are set via components.mobile_platforms above.

# ─── Spec-Driven Constraints ─────────────────────────────────────────────────
spec:
  tech_constraints: null     # e.g. "PostgreSQL 16, Redis 7, JWT auth"
  arch_constraints: null     # e.g. "12-factor app, stateless, horizontal scaling"
  files: []                  # optional: existing OpenAPI YAML / SQL DDL to honour
```

### Mobile Agent

The Mobile Agent generates a complete mobile client that connects to the BFF (or directly to the backend when BFF is disabled). **Multiple platforms can be generated simultaneously** — each one runs as an independent `MobileAgent` instance via `asyncio.gather`, writing to its own subdirectory.

| Platform | Slug (output dir) | Default stack |
|---|---|---|
| **React Native** _(default)_ | `mobile_react_native/` | Expo SDK 51, React Navigation 6, Zustand, Axios |
| **Flutter** | `mobile_flutter/` | Riverpod 2, Dio, GoRouter, Flutter 3.22 |
| **iOS (Swift)** | `mobile_ios_swift/` | SwiftUI + Combine, URLSession, async/await |
| **Android (Kotlin)** | `mobile_android_kotlin/` | Jetpack Compose + ViewModel, Retrofit 2, Coroutines |

The BFF URL is injected via the `BFF_BASE_URL` environment variable. Each platform's artifact is saved as `03d_<slug>_artifact.json`.

**Example — iOS + Android in one run:**

```bash
python3.11 main.py \
  --requirements reqs.txt \
  --mobile-platform "iOS (Swift)" \
  --mobile-platform "Android (Kotlin)"
# Both agents run concurrently. Outputs:
#   generated/mobile_ios_swift/
#   generated/mobile_android_kotlin/
#   artifacts/03d_mobile_ios_swift_artifact.json
#   artifacts/03d_mobile_android_kotlin_artifact.json
```

---

## Human Intelligence Checkpoints

The pipeline **automatically pauses** at 4 checkpoints by default. At each pause it prints a summary panel and waits for your input before continuing. No `Ctrl+C` needed.

```
⏸  Pipeline paused — human review required

  Requirements extracted : 12
  Goals identified       : 5
  ...

  💡 If requirements were misunderstood, update your file and restart.

  Artifact → artifacts/my_run/01_discovery_artifact.json

  ↵ Enter — proceed    s — skip checkpoint    a — abort pipeline
  ▶ _
```

| # | Checkpoint | After Agent | Why Human Input Matters |
|---|---|---|---|
| 1 | **Requirements Validated** | Discovery Agent | Confirm the agent correctly interpreted ambiguous requirements; add tacit domain knowledge the LLM can't know |
| 2 | **Architecture Approved** | Architecture Agent + Test | Review strategic technology choices and trade-offs against team expertise, org constraints, and existing systems |
| 3 | **API Contract Approved** ⚠️ | Spec Agent | The OpenAPI + DDL is a **public contract** — once downstream services depend on it, changes are expensive |
| 4 | **Security & Quality Review** | Review Agent | LLMs miss context-specific threat models, business-logic exploits, and organisation-specific compliance requirements |

> **CI/CD / unattended mode:** pass `--auto` to skip all checkpoints and run end-to-end without any pauses. Checkpoints are also auto-skipped when stdin is not a TTY (piped input, Docker, GitHub Actions).

### Commands at each checkpoint

| Input | Action |
|---|---|
| `↵ Enter` (or any text) | Proceed to the next pipeline step |
| `s` | Skip this checkpoint and continue (don't pause here) |
| `a` or `abort` | Stop the pipeline immediately — all artifacts written so far are preserved |

### Checkpoint 1 — Requirements Validated

The pipeline pauses after the Discovery Agent and shows you what it understood: requirements, goals, constraints, scope, and top risks.

**If the agent missed something or misunderstood scope:**
```bash
# Type 'a' to abort, then edit your requirements file
vim reqs.txt

# Restart with corrected requirements
python3.11 main.py --requirements reqs.txt --output-dir ./artifacts/my_run_v2
```

**Inspect the full artifact at any time:**
```bash
cat artifacts/my_run/01_discovery_artifact.json | python3 -m json.tool | less
```

### Checkpoint 2 — Architecture Approved

The pipeline pauses after Architecture design and the first testing pass. Shows architecture style, component names, and test results.

**To override technology or design decisions:**
```bash
# Type 'a' to abort, then restart with constraints
python3.11 main.py \
  --requirements reqs.txt \
  --arch-constraints "Event-sourcing with Kafka, no synchronous REST between services" \
  --tech-constraints "Kotlin + Ktor, not Spring Boot" \
  --output-dir ./artifacts/my_run_v2
```

### Checkpoint 3 — API Contract Approved ⚠️ Most critical

The pipeline pauses after the Spec Agent and shows the OpenAPI + DDL it generated, with direct file paths.

**This is the most important gate.** Once Engineering runs, all three services (BE, BFF, FE) implement against this contract. Edit the files freely at the prompt before pressing Enter:

```bash
# While the pipeline is paused at Checkpoint 3:
vim artifacts/my_run/generated/specs/openapi.yaml   # add/remove/rename endpoints
vim artifacts/my_run/generated/specs/schema.sql     # adjust tables and columns

# Then press Enter at the prompt — Engineering implements your edited contract exactly
```

**Alternatively, abort and re-run with the edited contract as the base:**
```bash
# Type 'a' to abort, edit the spec files, then resume
python3.11 main.py \
  --requirements reqs.txt \
  --from-run ./artifacts/my_run \
  --output-dir ./artifacts/my_run_approved
```

The Spec Agent will mark all edited paths as the approved contract with `x-existing: true`.

### Checkpoint 4 — Security & Quality Review

The pipeline pauses after the review loop and shows the security score, critical issue count, and a list of any blocking findings.

**If there are critical issues you need to handle yourself:**
```bash
# Type 'a' to abort, then re-run with security constraints injected
python3.11 main.py \
  --requirements reqs.txt \
  --from-run ./artifacts/my_run \
  --arch-constraints "All endpoints require mutual TLS; secrets via AWS Secrets Manager only" \
  --output-dir ./artifacts/my_run_secure
```

### Running without checkpoints (CI/CD)

```bash
# Skip all human review pauses — runs fully unattended
python3.11 main.py --requirements reqs.txt --auto

# Checkpoints are also automatically skipped when stdin is not a TTY:
# e.g. piped input, Docker containers, GitHub Actions, etc.
```

### Checkpoint 5 — Incremental feature development (chain of runs)

Every `--from-run` continues the contract chain. The recommended workflow for a live system:

```bash
# Sprint 1 — initial build
python3.11 main.py --requirements sprint1.txt --output-dir ./artifacts/sprint1
# └─ Human review at: 01_discovery_artifact.json, 02_architecture_artifact.json,
#    generated/specs/openapi.yaml, 04_review_artifact.json

# Sprint 2 — new feature, must not break sprint 1 API
python3.11 main.py \
  --requirements sprint2.txt \
  --from-run ./artifacts/sprint1 \
  --output-dir ./artifacts/sprint2
# └─ Spec Agent marks all sprint1 paths x-existing: true
#    Human approves only the new paths before Engineering runs

# Sprint 3 — another increment
python3.11 main.py \
  --requirements sprint3.txt \
  --from-run ./artifacts/sprint2 \
  --output-dir ./artifacts/sprint3
```

> **Tip:** Commit each run's `generated/specs/` directory to git. Your API contract history becomes part of your codebase, with full `git diff` between sprints.

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

components:
  bff: false            # API-only: no BFF layer
  mobile_platforms:     # generate two native apps in parallel
    - "iOS (Swift)"
    - "Android (Kotlin)"

tech:
  backend_language: Go
  backend_framework: Gin
  frontend_framework: Vue
  frontend_language: TypeScript

spec:
  tech_constraints: "PostgreSQL 16, Redis 7, JWT auth"
  arch_constraints: "12-factor app, horizontal scaling"
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
git clone https://github.com/vb-nattamai/llm-sdlc-workflow.git
cd llm-sdlc-workflow

# Install the package and all dependencies (editable mode — recommended for development)
pip install -e .

# Or install with dev dependencies (pytest etc.)
pip install -e ".[dev]"
```

> The package is installed from `src/` using [PEP 517 src layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/). `main.py` at the repo root stays as a convenient CLI entry point, or you can use `python -m llm_sdlc_workflow` once installed.

### Authentication

The pipeline calls the **GitHub Models API** — an OpenAI-compatible endpoint hosted by GitHub (backed by Azure). Authentication uses your existing **GitHub Copilot token**. No `.env` file, no OpenAI account, and no separate API credits are required.

#### How the token is resolved (automatic, in order)

The pipeline tries two methods at startup and uses the first that succeeds:

| Priority | Method | How to set it up |
|---|---|---|
| 1 | `GITHUB_TOKEN` environment variable | `export GITHUB_TOKEN=$(gh auth token)` |
| 2 | GitHub CLI — `gh auth token` | Install `gh` and run `gh auth login` once |

If neither is available the pipeline exits immediately with a clear error message.

#### Option A — GitHub CLI (recommended, zero configuration)

```bash
# 1. Install the GitHub CLI (if not already installed)
#    macOS:
brew install gh
#    Linux:
sudo apt install gh   # or: https://cli.github.com/

# 2. Authenticate once — opens a browser flow
gh auth login

# 3. Verify the token is accessible (the pipeline calls this automatically)
gh auth token

# 4. Run the pipeline — no further setup needed
python3.11 main.py --requirements my_requirements.txt
```

> The pipeline calls `gh auth token` programmatically at startup. As long as your CLI session is active, nothing else is needed.

#### Option B — Personal Access Token (PAT) via environment variable

Use this for CI/CD pipelines, Docker containers, or environments where the GitHub CLI is not available.

```bash
# 1. Create a fine-grained PAT at: https://github.com/settings/tokens
#    Required permission: Models → Read-only  (listed as "models:read")
#    No repository or organisation permissions needed.

# 2. Export the token in your shell session
export GITHUB_TOKEN=github_pat_XXXXXXXXXXXXXXXXXXXX

# 3. (Optional) Add to your shell profile to persist across sessions
echo 'export GITHUB_TOKEN=github_pat_XXXXXXXXXXXXXXXXXXXX' >> ~/.zshrc

# 4. Run the pipeline
python3.11 main.py --requirements my_requirements.txt
```

> **Never hardcode the token in source files or commit it to git.** The `.gitignore` in this repo already excludes `.env` and `.env.*` files — store it there if you prefer a file-based approach:
> ```bash
> echo 'GITHUB_TOKEN=github_pat_XXXXXXXXXXXXXXXXXXXX' >> .env
> source .env   # or use direnv / dotenv
> ```

#### Required: GitHub Copilot licence

GitHub Models access is **included with every GitHub Copilot plan** (Free, Pro, Business, Enterprise). The plan determines your daily rate limits:

| Model tier | Model examples | Copilot Free/Pro | Copilot Business | Copilot Enterprise |
|---|---|---|---|---|
| **High** | `gpt-4o` (default) | **50 req/day** | **100 req/day** | **150 req/day** |
| **Low** | `gpt-4o-mini` | **150 req/day** | **300 req/day** | **450 req/day** |
| Concurrent requests | all models | 2 | 2 | 4 |

> `gpt-4o` is a **High** model. A full pipeline run makes many calls (one per agent plus chunked file generation), so it can exhaust the daily quota. See [Choosing a model](#choosing-a-model) below.

#### Choosing a model

Override the default `gpt-4o` with the `--model` flag or the `PIPELINE_MODEL` environment variable:

```bash
# Cheaper, 3× higher daily limit — good for experimentation
python3.11 main.py --requirements reqs.txt --model gpt-4o-mini

# Set a persistent default
export PIPELINE_MODEL=gpt-4o-mini
```

| Use case | Recommended model | Daily limit (Pro) |
|---|---|---|
| Full production pipeline | `gpt-4o` | 50 req/day |
| Rapid iteration / experimentation | `gpt-4o-mini` | 150 req/day |
| Best quality, slow | `o3-mini` | 12 req/day |

#### Rate limit errors

If you hit the daily quota you will see:

```
Error code: 429 - Rate limit of 100 per 86400s exceeded for UserByModelByDay.
Please wait 69116 seconds before retrying.
```

Options:
- **Wait** — the quota resets every 24 hours.
- **Switch models** — `--model gpt-4o-mini` has a 3× higher daily allowance.
- **Use your own API key** — see [Bring Your Own API Key](#bring-your-own-api-key) below.

#### Bring Your Own API Key

Two environment variables let you swap the provider without touching any code:

| Variable | Purpose | Default |
|---|---|---|
| `PIPELINE_BASE_URL` | API endpoint (any OpenAI-compatible URL) | `https://models.inference.ai.azure.com` |
| `PIPELINE_API_KEY` | API key for the provider (overrides GitHub token resolution) | _(uses GitHub token)_ |
| `PIPELINE_MODEL` | Model name | `gpt-4o` |

When `PIPELINE_API_KEY` is set, `GITHUB_TOKEN` and `gh auth token` are ignored entirely.

##### Setting variables in your GitHub repository

API keys must **never** be committed to source code. GitHub provides two secure storage mechanisms depending on whether the value is sensitive:

| Type | Use for | Visible in logs? | CLI to set |
|---|---|---|---|
| **Secret** | `PIPELINE_API_KEY` (any API key) | ❌ Always masked | `gh secret set` |
| **Variable** | `PIPELINE_BASE_URL`, `PIPELINE_MODEL` (non-sensitive config) | ✅ Visible | `gh variable set` |

**Via GitHub CLI (fastest):**

```bash
# Store the API key as an encrypted secret (value is never shown in logs)
gh secret set PIPELINE_API_KEY --body "xai-xxxxxxxxxxxxxxxxxxxx"

# Store the endpoint and model as plain variables (non-sensitive)
gh variable set PIPELINE_BASE_URL --body "https://api.x.ai/v1"
gh variable set PIPELINE_MODEL    --body "grok-3-beta"
```

**Via GitHub web UI:**

1. Go to your repository → **Settings** → **Secrets and variables** → **Actions**
2. For `PIPELINE_API_KEY` → click **New repository secret**
3. For `PIPELINE_BASE_URL` and `PIPELINE_MODEL` → switch to the **Variables** tab → click **New repository variable**

**Using them in a GitHub Actions workflow:**

```yaml
# .github/workflows/pipeline.yml
name: Run LLM SDLC Pipeline

on:
  workflow_dispatch:
    inputs:
      requirements:
        description: "Path to requirements file"
        default: "hello_world_requirements.txt"

jobs:
  run-pipeline:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - run: pip install -e ".[dev]"

      - name: Run pipeline
        env:
          PIPELINE_API_KEY:  ${{ secrets.PIPELINE_API_KEY }}
          PIPELINE_BASE_URL: ${{ vars.PIPELINE_BASE_URL }}
          PIPELINE_MODEL:    ${{ vars.PIPELINE_MODEL }}
        run: |
          python3.11 main.py \
            --requirements ${{ github.event.inputs.requirements }} \
            --auto

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: pipeline-artifacts
          path: artifacts/
```

> `--auto` is required in CI — it skips all human review checkpoints since stdin is not a TTY. Alternatively, the pipeline skips checkpoints automatically when stdin is not a TTY (piped input, Docker, GitHub Actions), so `--auto` is only needed if you want to be explicit.

**For GitHub Models (default) in CI — no secret needed:**

If you are using the default GitHub Models endpoint, you do not need `PIPELINE_API_KEY` at all. GitHub Actions provides `GITHUB_TOKEN` automatically with `models:read` permission:

```yaml
      - name: Run pipeline (GitHub Models — no API key needed)
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}   # automatically provided
        run: python3.11 main.py --requirements reqs.txt --auto
```

---

#### Available models on GitHub Models (no code changes, no extra account)

All of these work with your existing GitHub token and the `--model` flag. GitHub Models hosts models from multiple providers:

```bash
# xAI Grok — available directly on GitHub Models
python3.11 main.py --requirements reqs.txt --model xai-grok-3
python3.11 main.py --requirements reqs.txt --model xai-grok-3-mini   # higher rate limit

# DeepSeek R1 (open-weight reasoning model)
python3.11 main.py --requirements reqs.txt --model DeepSeek-R1

# Meta Llama 3
python3.11 main.py --requirements reqs.txt --model meta-llama-3.1-405b-instruct

# Mistral (hosted on GitHub Models)
python3.11 main.py --requirements reqs.txt --model Mistral-large-2411

# Microsoft Phi
python3.11 main.py --requirements reqs.txt --model Phi-4
```

> Browse the full catalogue at [github.com/marketplace/models](https://github.com/marketplace/models). Use the exact model name shown there as the `--model` value.

---

#### OpenAI (direct, bypasses GitHub Models)

```bash
export PIPELINE_API_KEY=sk-...                    # your OpenAI API key
export PIPELINE_BASE_URL=https://api.openai.com/v1
export PIPELINE_MODEL=gpt-4o                     # or gpt-4o-mini, o3-mini, etc.

python3.11 main.py --requirements reqs.txt
```

---

#### xAI Grok (direct API)

xAI's API is fully OpenAI-compatible — swap the endpoint and key:

```bash
export PIPELINE_API_KEY=xai-...                   # from console.x.ai
export PIPELINE_BASE_URL=https://api.x.ai/v1
export PIPELINE_MODEL=grok-3-beta                # or grok-3-mini-beta

python3.11 main.py --requirements reqs.txt
```

---

#### Google Gemini

Google exposes an OpenAI-compatible endpoint for Gemini models:

```bash
export PIPELINE_API_KEY=AIza...                   # from aistudio.google.com/app/apikey
export PIPELINE_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
export PIPELINE_MODEL=gemini-2.0-flash           # or gemini-2.5-pro-preview-03-25

python3.11 main.py --requirements reqs.txt
```

> Get a free API key at [aistudio.google.com](https://aistudio.google.com/app/apikey) — no billing required for Gemini Flash.

---

#### Mistral (direct API)

```bash
export PIPELINE_API_KEY=...                       # from console.mistral.ai
export PIPELINE_BASE_URL=https://api.mistral.ai/v1
export PIPELINE_MODEL=mistral-large-latest       # or mistral-small-latest

python3.11 main.py --requirements reqs.txt
```

---

#### Anthropic Claude

Anthropic's native API is **not** OpenAI-compatible. The recommended approach is to use a local proxy such as [LiteLLM](https://github.com/BerriAI/litellm) which translates the OpenAI format to Anthropic's Messages API:

```bash
# 1. Install and start LiteLLM proxy
pip install litellm[proxy]
ANTHROPIC_API_KEY=sk-ant-... litellm --model claude-opus-4-5 --port 4000

# 2. Point the pipeline at the local proxy
export PIPELINE_API_KEY=anything           # LiteLLM accepts any non-empty key
export PIPELINE_BASE_URL=http://localhost:4000
export PIPELINE_MODEL=claude-opus-4-5

python3.11 main.py --requirements reqs.txt
```

Alternatively, use Claude through **AWS Bedrock** (OpenAI-compatible via Amazon's converse API) or **Google Vertex AI** (OpenAI-compatible):

```bash
# AWS Bedrock via LiteLLM
AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
  litellm --model bedrock/anthropic.claude-opus-4-5-20251101-v1:0 --port 4000
```

---

#### Local models via Ollama

Run any model locally with [Ollama](https://ollama.com) — no internet, no API costs:

```bash
# 1. Install Ollama and pull a model
brew install ollama
ollama pull llama3.3         # or mistral, phi4, deepseek-r1, etc.
ollama serve                 # starts on http://localhost:11434

# 2. Point the pipeline at Ollama's OpenAI-compatible endpoint
export PIPELINE_API_KEY=ollama            # any non-empty string
export PIPELINE_BASE_URL=http://localhost:11434/v1
export PIPELINE_MODEL=llama3.3

python3.11 main.py --requirements reqs.txt
```

> ⚠️ Local models are generally less capable at structured JSON generation than frontier models. The pipeline uses `response_format: json_object` — ensure your chosen Ollama model supports it (Llama 3.3, Mistral, Phi-4 do).

---

#### Provider quick-reference

| Provider | `PIPELINE_BASE_URL` | `PIPELINE_API_KEY` source | Recommended model |
|---|---|---|---|
| GitHub Models _(default)_ | `https://models.inference.ai.azure.com` | `gh auth token` / `GITHUB_TOKEN` | `gpt-4o` |
| OpenAI | `https://api.openai.com/v1` | [platform.openai.com](https://platform.openai.com/api-keys) | `gpt-4o` |
| xAI Grok | `https://api.x.ai/v1` | [console.x.ai](https://console.x.ai) | `grok-3-beta` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | [aistudio.google.com](https://aistudio.google.com/app/apikey) | `gemini-2.0-flash` |
| Mistral | `https://api.mistral.ai/v1` | [console.mistral.ai](https://console.mistral.ai) | `mistral-large-latest` |
| Anthropic Claude | via LiteLLM proxy | [console.anthropic.com](https://console.anthropic.com) | `claude-opus-4-5` |
| Ollama (local) | `http://localhost:11434/v1` | any string | `llama3.3` |

> With your own key, rate limits and billing are managed entirely by your chosen provider — not GitHub.

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
# ─── Input / output ──────────────────────────────────────────────────────────
--requirements FILE       Path to a requirements text file
--interactive             Type requirements at the terminal (stdin)
--config FILE             Load configuration from a pipeline.yaml (CLI flags override)
--spec FILE               Spec file (OpenAPI YAML, SQL DDL, etc.) — repeatable
--output-dir DIR          Artifacts output directory (default: artifacts/run_YYYYMMDD_HHMMSS)
--project-name NAME       Generated code directory name (prompts if omitted)
--from-run DIR            Extend the existing contract from a previous run

# ─── Constraints ─────────────────────────────────────────────────────────────
--tech-constraints STR    e.g. "Python FastAPI, PostgreSQL, Redis"
--arch-constraints STR    e.g. "Microservices on Kubernetes"

# ─── Execution ───────────────────────────────────────────────────────────────
--auto                    Skip all human review checkpoints (CI/CD mode)
--model MODEL             LLM model (default: gpt-4o, or PIPELINE_MODEL env var)

# ─── Component toggles ───────────────────────────────────────────────────────
--no-bff                  Disable BFF sub-agent (API-only or mobile-first projects)
--no-frontend             Disable Frontend sub-agent
--mobile                  Enable Mobile sub-agent (React Native by default)

# ─── Tech-stack preferences ──────────────────────────────────────────────────
--backend-lang LANG       Backend language, e.g. "Python", "Go", "Node.js" (default: Kotlin)
--backend-framework FW    Backend framework, e.g. "FastAPI", "Gin"  (default: Spring Boot)
--bff-lang LANG           BFF language (default: Kotlin)
--bff-framework FW        BFF framework, e.g. "NestJS"  (default: Spring WebFlux)
--frontend-framework FW   Frontend framework, e.g. "Vue", "Next.js"  (default: React 18)
--frontend-lang LANG      Frontend language  (default: TypeScript)
--mobile-platform PLAT    Mobile platform — can be given MULTIPLE TIMES to generate
                          several platforms in parallel:
                            --mobile-platform "iOS (Swift)"
                            --mobile-platform "iOS (Swift)" --mobile-platform "Android (Kotlin)"
                          Valid values: "React Native", "Flutter",
                                        "iOS (Swift)", "Android (Kotlin)"
                          Default (when --mobile is set): React Native
```

---

## Output Structure

Each run creates a timestamped directory under `artifacts/`:

```
artifacts/run_20260318_120000/
├── 00_pipeline_report.json              # overall pass/fail + summary metrics
├── 01_discovery_artifact.json           # Discovery Agent output
├── 02_architecture_artifact.json        # Architecture Agent output
├── 03_engineering_artifact.json         # Engineering Agent (merged) output
├── 03a_backend_artifact.json            # Backend sub-agent output
├── 03b_bff_artifact.json                # BFF sub-agent output  (omitted when --no-bff)
├── 03c_frontend_artifact.json           # Frontend sub-agent output  (omitted when --no-frontend)
├── 03d_mobile_react_native_artifact.json  # Mobile agent — React Native  (one file per platform)
├── 03d_mobile_ios_swift_artifact.json     # Mobile agent — iOS (Swift)
├── 03d_mobile_android_kotlin_artifact.json# Mobile agent — Android (Kotlin)
├── 04_generated_spec_artifact.json      # Spec Agent — forward contract
├── 04_review_artifact.json              # Review Agent output
├── 05a_testing_architecture.json        # Testing: architecture stage
├── 05b_testing_infrastructure.json      # Testing: live HTTP + Cypress stage
├── 05c_testing_review.json              # Testing: final sign-off
├── 06a_infrastructure_plan_artifact.json  # Infrastructure Agent — IaC plan
├── 06b_infrastructure_apply_artifact.json # Infrastructure Agent — containers started
├── 07_deployment_artifact.json           # Deployment Agent — CI/CD + K8s + Helm
├── *_agent_history.json                 # full LLM conversation history per agent
└── generated/                           # ← all generated source code + IaC
    ├── backend/                         # Language/framework — configurable (default: Kotlin/Spring Boot)
    │   ├── build.gradle.kts             #   (or pyproject.toml, go.mod, package.json …)
    │   ├── src/main/kotlin/...
    │   └── Dockerfile
    ├── bff/                             # Configurable (default: Kotlin/Spring WebFlux) — optional
    │   ├── build.gradle.kts
    │   ├── src/main/kotlin/...
    │   └── Dockerfile
    ├── frontend/                        # Configurable (default: React 18 + TypeScript/Vite) — optional
    │   ├── package.json
    │   ├── src/
    │   ├── nginx.conf
    │   └── Dockerfile
    ├── mobile_react_native/             # React Native (Expo) — one dir per platform
    ├── mobile_ios_swift/                # iOS (Swift) — when --mobile-platform "iOS (Swift)"
    ├── mobile_android_kotlin/           # Android — when --mobile-platform "Android (Kotlin)"
    ├── mobile_flutter/                  # Flutter — when --mobile-platform Flutter
    ├── specs/                           # Forward contract (use with --from-run)
    │   ├── openapi.yaml                 # OpenAPI 3.0 — all endpoints
    │   └── schema.sql                   # SQL DDL — all tables
    ├── cypress/                         # Cypress e2e specs
    │   ├── cypress.config.ts
    │   └── e2e/*.cy.ts
    ├── deployment/                      # CI/CD + Kubernetes + Helm
    │   ├── .github/workflows/           # ci.yml, cd-staging.yml, cd-production-canary.yml
    │   │   ├── ci.yml                   #   cd-production-blue-green.yml, security-scan.yml
    │   │   └── ...                      #   rollback.yml
    │   ├── k8s/                         # Base K8s manifests (Deployment, Service, Ingress, HPA, PDB)
    │   │   ├── blue-green/              # Blue-green Deployment pairs + switch.sh
    │   │   └── canary/                  # Argo Rollout CRD + AnalysisTemplate
    │   ├── helm/                        # Helm chart (Chart.yaml, values per env, templates/)
    │   ├── scripts/                     # deploy.sh, rollback.sh, canary-promote.sh
    │   └── Makefile                     # make deploy-staging / deploy-production / rollback
    └── docker-compose.yml               # starts the full monorepo stack
```

The `generated/specs/` directory is what `--from-run` reads on the next run.

---

## Project Structure

```
llm-sdlc-workflow/                        ← repo root
├── main.py                               # CLI entry point (python main.py ...)
├── pyproject.toml                        # package metadata + dependencies (PEP 517)
├── pipeline.yaml                         # pipeline config template — copy per project
├── README.md
├── .gitignore
│
├── src/
│   └── llm_sdlc_workflow/               # installable Python package
│       ├── __init__.py                  # package version
│       ├── __main__.py                  # python -m llm_sdlc_workflow entry point
│       ├── pipeline.py                  # orchestrator — accepts PipelineConfig
│       ├── config.py                    # PipelineConfig, ComponentConfig, TechConfig
│       │
│       ├── agents/                      # one file per AI agent
│       │   ├── base_agent.py            # shared: LLM client, retry, chunked gen, I/O
│       │   ├── discovery_agent.py       # DiscoveryAgent   → DiscoveryArtifact
│       │   ├── architecture_agent.py    # ArchitectureAgent → ArchitectureArtifact
│       │   ├── spec_agent.py            # SpecAgent        → GeneratedSpecArtifact
│       │   ├── engineering_agent.py     # EngineeringAgent → runs only enabled sub-agents
│       │   ├── backend_agent.py         # accepts language= / framework= overrides
│       │   ├── bff_agent.py             # accepts language= / framework= overrides
│       │   ├── frontend_agent.py        # accepts framework= / language= overrides
│       │   ├── mobile_agent.py          # MobileAgent — React Native / Flutter / Swift / Kotlin
│       │   ├── infrastructure_agent.py  # Dockerfiles + docker-compose
│       │   ├── deployment_agent.py      # DeploymentAgent — GitHub Actions + K8s + Helm + canary/blue-green
│       │   ├── review_agent.py          # OWASP security + code quality loop
│       │   └── testing_agent.py         # 3-stage: arch → live HTTP → final
│       │
│       ├── models/
│       │   └── artifacts.py             # all Pydantic models (typed inter-agent data)
│       │
│       └── prompts/                     # agent system prompts — edit without touching Python
│           ├── discovery_agent.md
│           ├── architecture_agent.md
│           ├── spec_agent.md
│           ├── backend_agent.md         # default: Kotlin Spring Boot 3.3 persona
│           ├── bff_agent.md             # default: Kotlin Spring WebFlux persona
│           ├── frontend_agent.md        # default: React 18 + TypeScript 5 persona
│           ├── mobile_agent.md          # React Native (Expo), Flutter, Swift, Kotlin variants
│           ├── infrastructure_agent.md
│           ├── deployment_agent.md      # GitHub Actions CI/CD, K8s, Helm, canary, blue-green
│           ├── review_agent.md
│           └── testing_agent.md
│
├── tests/                               # pytest test suite
│   ├── test_artifacts.py
│   └── test_pipeline.py
│
├── examples/
│   └── hello_world_requirements.txt     # minimal 3-tier app example
│
└── .github/
    └── workflows/
        └── pipeline.yml                 # GitHub Actions — run pipeline via workflow_dispatch
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
| **MigrationAgent** | Database | Flyway / Liquibase migration scripts with rollback procedures |
| **PerformanceAgent** | Testing | k6 / Gatling load test scripts, SLA budgets, bottleneck analysis |
| **ComplianceAgent** | Governance | GDPR data map, SOC2 controls checklist, HIPAA PHI handling guide |
| **SecurityScanAgent** | Security | SAST output triage, dependency CVE report, secrets detection |
| **MaintenanceAgent** | Maintenance | Dependency update PRs, technical debt scoring, refactoring recommendations |

---

## How It Works

1. **Chunked LLM generation** — each agent generates files in two LLM calls: first a plan with all content `__PENDING__`, then one call per file to fill it. Prevents token-limit failures on large codebases.

2. **Contract-first spec** — the Spec Agent generates an OpenAPI + DDL contract *before* any code is written. All three engineering sub-agents implement against this single source of truth, ensuring consistency from day one.

3. **Parallel sub-agents** — Only the *enabled* sub-agents run, via `asyncio.gather`. Disable BFF or Frontend with a flag; add Mobile with `--mobile`. Infrastructure planning also runs in parallel with Engineering. After the review loop, the **Infrastructure Agent** (start containers) and **Deployment Agent** (CI/CD + K8s + Helm) both run in parallel.

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
- Python packages: managed via `pyproject.toml` — install with `pip install -e .`
