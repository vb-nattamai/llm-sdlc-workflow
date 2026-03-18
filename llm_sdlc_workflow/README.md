# LLM SDLC Workflow

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
└────────┬─────────┘        → 01_discovery_artifact.json
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
| **Discovery Agent** | Extracts requirements, goals, constraints, scope, risks, and success criteria from raw text | `DiscoveryArtifact` |
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
git clone https://github.com/vb-diconium/llm-sdlc-workflow.git
cd llm-sdlc-workflow
pip install -r requirements.txt
```

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

      - run: pip install -r requirements.txt

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
├── 01_discovery_artifact.json           # Discovery Agent output
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
llm_sdlc_workflow/
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
│   ├── discovery_agent.py      # DiscoveryAgent → DiscoveryArtifact
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
    ├── artifacts.py            # all Pydantic models: DiscoveryArtifact, GeneratedSpecArtifact, etc.
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
