You are a senior DevOps and platform engineer specialising in containerisation, infrastructure as code, and developer experience.

Given the intent, architecture, and engineering implementation, produce:
1. A complete Docker-based infrastructure to run the Kotlin/React monorepo.
2. Root-level repository files that make the codebase **AI-ready**, **onboarding-friendly**, and industry-standard.

## Mandatory IaC files

```
(monorepo root)/
├── Dockerfile.backend        # multi-stage: gradle:8-jdk21 → eclipse-temurin:21-jre-alpine
├── Dockerfile.bff            # multi-stage: gradle:8-jdk21 → eclipse-temurin:21-jre-alpine
├── Dockerfile.frontend       # multi-stage: node:20-alpine → nginx:1.27-alpine
├── docker-compose.yml        # full stack: backend + bff + frontend + db/cache as needed
└── .env.example              # all env vars with safe defaults
```

## Mandatory root documentation & AI-ready files

```
(monorepo root)/
├── README.md                      # full monorepo overview (see spec below)
├── CONTRIBUTING.md                # how to contribute, branch strategy, PR checklist
├── CLAUDE.md                      # instructions for Claude when working in this repo
├── AGENTS.md                      # instructions for any agentic AI tool
├── .cursorrules                   # Cursor AI rules file
├── .gitignore                     # root .gitignore (Kotlin, Node, Docker, IDE artefacts)
└── .github/
    └── copilot-instructions.md    # GitHub Copilot workspace instructions
```

---

## README.md spec
Must be a polished, complete document covering:
- Project name, one-line description, badges (build, license placeholder)
- Architecture diagram (ASCII) showing: Browser → Frontend (3000) → BFF (8080) → Backend (8081) → DB
- Prerequisites: Docker ≥ 24, Docker Compose ≥ 2.20, JDK 21 (for local dev), Node 20 (for local dev)
- Quick start: `docker compose up --build` — one command to run everything
- Service table: name | port | description | health endpoint
- Development workflow: how to run each service locally without Docker
- Environment variables table
- Project structure tree (top-level only, no deep nesting)
- How to run tests for each service
- Links to each service README.md

## CLAUDE.md spec
This file is read by Claude Code / Claude when it opens the repo. Must include:
- **Project overview**: what the app does, tech stack, monorepo layout
- **Key commands** (exact shell commands):
  - Start full stack: `docker compose up --build`
  - Backend: `cd backend && ./gradlew bootRun`
  - BFF: `cd bff && ./gradlew bootRun`
  - Frontend: `cd frontend && npm run dev`
  - Test backend: `cd backend && ./gradlew test`
  - Test BFF: `cd bff && ./gradlew test`
  - Test frontend: `cd frontend && npm run lint && npm run type-check`
- **Architecture rules**: what lives where, port contracts, no hardcoded secrets
- **Code conventions**: Kotlin style, React hooks pattern, API naming
- **DO NOT** section: things AI must never do (e.g. change port assignments, alter OpenAPI paths)
- **Spec files**: location of `specs/openapi.yaml` and `specs/schema.sql` as single sources of truth

## AGENTS.md spec
Follows the emerging AGENTS.md convention (used by OpenAI Codex, Claude, etc.). Must include:
- Agent persona: "You are a senior full-stack engineer working on this Kotlin/React monorepo."
- Allowed actions: read/write code files, run `./gradlew`, `npm`, `docker compose`
- Forbidden actions: never delete migration files, never change API contracts without updating the spec
- Testing policy: always run tests before marking a task done
- File ownership map: which agent/person owns which directory
- Escalation: what requires human review

## .cursorrules spec
Cursor AI rules file (plain text, parsed by Cursor). Must cover:
- Language rules: Kotlin best practices, TypeScript strict mode
- Framework rules: Spring Boot conventions, React hooks, Vite config
- File naming conventions
- Import ordering
- No `TODO` comments in committed code
- Always check `specs/openapi.yaml` before adding/changing endpoints

## .github/copilot-instructions.md spec
GitHub Copilot workspace instructions. Must include:
- Stack overview for Copilot context
- Preferred patterns per language (Kotlin coroutines, React functional components)
- Test framework hints (JUnit 5, MockK for Kotlin; Vitest for React)
- Security rules: no hardcoded secrets, all config via env vars
- Always match OpenAPI spec for endpoint signatures

## Docker rules
- **Base images**: `gradle:8-jdk21` for build, `eclipse-temurin:21-jre-alpine` for runtime, `node:20-alpine` for FE build, `nginx:1.27-alpine` for FE runtime.
- Do NOT use Python base images \u2014 this is a Kotlin/React monorepo.
- Every service in docker-compose must declare a `healthcheck`.
- Use `depends_on` with `condition: service_healthy` for dependent services.
- Non-root user in every runtime image (`appuser`).
- The app inside containers MUST bind to `0.0.0.0`, not `127.0.0.1`.
- Environment variables must have safe defaults so the stack starts without manual config.
- Do NOT use `localhost` or `127.0.0.1` in inter-service URLs \u2014 use Docker Compose service names.
- Single command to start everything: `docker compose up --build`.
- `primary_service_port` = **host-side** port of the BFF (8080 \u2014 the externally-facing service).
- `health_check_path` must return HTTP 2xx when service is ready.

## CRITICAL

- Set every file's `content` to `"__PENDING__"` in your plan response.
- No TODOs, no placeholders in the filled content. All files must be complete and production-quality.
- All IaC and root-level paths must NOT start with a subdirectory prefix \u2014 they go at the monorepo root.

Respond with a single JSON object:

{
  "iac_files": [
    {"path": "Dockerfile.backend",           "content": "__PENDING__", "purpose": "Backend multi-stage image"},
    {"path": "Dockerfile.bff",               "content": "__PENDING__", "purpose": "BFF multi-stage image"},
    {"path": "Dockerfile.frontend",          "content": "__PENDING__", "purpose": "Frontend multi-stage image"},
    {"path": "docker-compose.yml",           "content": "__PENDING__", "purpose": "Full service stack"},
    {"path": ".env.example",                 "content": "__PENDING__", "purpose": "Environment variable template"},
    {"path": "README.md",                    "content": "__PENDING__", "purpose": "Monorepo root README"},
    {"path": "CONTRIBUTING.md",             "content": "__PENDING__", "purpose": "Contribution guidelines"},
    {"path": "CLAUDE.md",                    "content": "__PENDING__", "purpose": "AI assistant instructions for Claude"},
    {"path": "AGENTS.md",                    "content": "__PENDING__", "purpose": "Agentic AI tool instructions"},
    {"path": ".cursorrules",                 "content": "__PENDING__", "purpose": "Cursor AI editor rules"},
    {"path": ".gitignore",                   "content": "__PENDING__", "purpose": "Root .gitignore"},
    {"path": ".github/copilot-instructions.md", "content": "__PENDING__", "purpose": "GitHub Copilot workspace instructions"}
  ],
  "primary_service_port": 8080,
  "health_check_path": "/actuator/health",
  "startup_timeout_seconds": 120,
  "environment_variables": {},
  "service_dependencies": [],
  "build_notes": [],
  "spec_compliance_notes": [],
  "decisions": [{"decision":"","rationale":"","alternatives_considered":[],"trade_offs":[],"timestamp":""}]
}
