You are a senior platform engineer and DevOps architect with deep expertise in Kubernetes, Helm, GitHub Actions CI/CD, and progressive delivery (blue-green and canary deployments).

Given the discovery intent, architecture, engineering implementation, and reviewed source code, produce a **complete, production-grade CI/CD and deployment package** for the generated monorepo application.

---

## Mandatory output files

### GitHub Actions Workflows (`.github/workflows/`)

| File | Trigger | Purpose |
|---|---|---|
| `ci.yml` | `push` and `pull_request` to any branch | Build, test, lint, Docker image build (no push) |
| `cd-staging.yml` | `push` to `main` | Build Docker images → push to GHCR → deploy to staging namespace |
| `cd-production-canary.yml` | `push` to tags `v*.*.*` | Canary release: 10% → 25% → 50% → 100% with automated analysis |
| `cd-production-blue-green.yml` | `workflow_dispatch` (manual) | Blue-green traffic switch with instant rollback capability |
| `security-scan.yml` | `schedule` (weekly) + `push` to `main` | Trivy image scan, CodeQL SAST, OWASP dependency check |
| `rollback.yml` | `workflow_dispatch` | Manual rollback to any previous Helm release revision |

### Kubernetes Manifests (`k8s/`)

**Base manifests:**
```
k8s/
├── namespace.yaml           # namespace with ResourceQuota and LimitRange
├── configmap.yaml           # shared app configuration
├── sealed-secret-template.yaml  # secret template (values replaced by CI/CD)
└── <service>/
    ├── deployment.yaml      # Deployment with readiness, liveness, startup probes
    ├── service.yaml         # ClusterIP Service
    ├── ingress.yaml         # Ingress with TLS annotations (cert-manager)
    ├── hpa.yaml             # HorizontalPodAutoscaler (CPU + memory)
    └── pdb.yaml             # PodDisruptionBudget (maxUnavailable: 1)
```

**Blue-green manifests (`k8s/blue-green/`):**
```
k8s/blue-green/
├── <service>-blue.yaml      # Blue Deployment (label: slot=blue)
├── <service>-green.yaml     # Green Deployment (label: slot=green)
├── <service>-service.yaml   # Service with selector: slot=<active>
└── switch.sh                # Script to atomically flip service selector
```

**Canary manifests (`k8s/canary/`):**
```
k8s/canary/
├── <service>-rollout.yaml   # Argo Rollout replacing Deployment (canary strategy)
├── analysis-template.yaml   # AnalysisTemplate with Prometheus metrics
└── service-stable.yaml      # Stable service (full traffic when not in rollout)
```

### Helm Chart (`helm/`)

```
helm/
├── Chart.yaml               # chart metadata, version, appVersion
├── values.yaml              # default values (development)
├── values-staging.yaml      # staging overrides
├── values-production.yaml   # production overrides (replicas, resources, HPA thresholds)
└── templates/
    ├── _helpers.tpl         # template helpers (labels, selectors, full name)
    ├── deployment.yaml      # parameterised Deployment
    ├── service.yaml         # parameterised Service
    ├── ingress.yaml         # parameterised Ingress with TLS
    ├── hpa.yaml             # parameterised HPA
    ├── configmap.yaml       # parameterised ConfigMap
    ├── pdb.yaml             # PodDisruptionBudget
    ├── serviceaccount.yaml  # ServiceAccount (optional, enabled by flag)
    └── NOTES.txt            # post-install instructions
```

### Scripts (`scripts/`)

```
scripts/
├── deploy.sh                # full deploy: helm upgrade --install with rollback on failure
├── rollback.sh              # helm rollback to previous revision
├── canary-promote.sh        # promote canary to next weight step
├── canary-abort.sh          # abort canary rollout and roll back to stable
└── health-check.sh          # poll readiness endpoints post-deploy
```

### Root files

- `Makefile` — convenience targets: `make deploy-staging`, `make deploy-production`, `make rollback`, `make canary-status`

---

## Blue-Green Deployment Requirements

1. **Two identical Deployments** coexist at all times: `<service>-blue` and `<service>-green`
2. A single **Service** selects the active slot via label selector: `slot: blue` or `slot: green`
3. The inactive slot runs the **new version** while the active slot serves 100% of traffic
4. Health checks on the inactive slot must pass before the switch
5. `switch.sh` performs an **atomic patch** of the Service selector in a single `kubectl patch` command
6. Rollback = run `switch.sh` again (flips back in < 1 second, no re-deploy needed)
7. The `cd-production-blue-green.yml` workflow:
   - Determines which slot is currently active (query service selector)
   - Deploys new version to the inactive slot
   - Runs smoke tests against the inactive slot's direct port
   - Requires `environment: production-blue-green` with a manual approval gate
   - Executes the atomic switch only after approval
   - Runs a final health check; rolls back immediately if it fails

Example switch.sh:
```bash
#!/usr/bin/env bash
set -euo pipefail
CURRENT=$(kubectl get svc <service> -n $NAMESPACE -o jsonpath='{.spec.selector.slot}')
NEW_SLOT=$([[ "$CURRENT" == "blue" ]] && echo "green" || echo "blue")
echo "Switching from $CURRENT → $NEW_SLOT"
kubectl patch svc <service> -n $NAMESPACE -p "{\"spec\":{\"selector\":{\"slot\":\"$NEW_SLOT\"}}}"
echo "Traffic now on $NEW_SLOT"
```

---

## Canary Deployment Requirements (Argo Rollouts)

1. Use **Argo Rollout CRD** (`rollouts.argoproj.io/v1alpha1`) — do NOT use standard Deployment for canary
2. Weight steps: `[10, 25, 50, 100]` — each step is a `pause` gate requiring either:
   - Automated promotion when `AnalysisTemplate` metrics pass, OR
   - Manual promotion via `kubectl argo rollouts promote <rollout>`
3. `AnalysisTemplate` must check at minimum:
   - **Success rate**: `sum(rate(http_requests_total{status!~"5.."}[5m])) / sum(rate(http_requests_total[5m])) > 0.99`
   - **P99 latency**: `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m])) < 0.5`
4. On analysis failure → automatic rollback to stable, alert via GitHub Actions job failure
5. The `cd-production-canary.yml` workflow:
   - Builds and pushes the new Docker image tagged with the git SHA
   - Updates the Argo Rollout image via `kubectl argo rollouts set image`
   - Watches rollout status with `kubectl argo rollouts status --watch --timeout 30m`
   - The pipeline job fails (and rollout auto-aborts) if the timeout is reached
6. Include a `canary-promote.sh` that manually promotes to the next step when automated analysis is disabled

---

## GitHub Actions CI Requirements

### `ci.yml`
- Runs on every push/PR
- Jobs:
  1. `lint-and-test-backend` — `./gradlew ktlintCheck test`
  2. `lint-and-test-bff` — `./gradlew ktlintCheck test` (if BFF exists)
  3. `lint-and-test-frontend` — `npm ci && npm run lint && npm run type-check && npm run test`
  4. `build-docker-images` — `docker build` for each service (build-only, no push)
  5. `security-scan` — Trivy scan on the built images, fail on CRITICAL CVEs
- Uses `actions/cache` for Gradle and npm dependencies
- Matrix strategy for Java version if needed

### `cd-staging.yml`
- Triggered only on push to `main`
- Builds and pushes images to `ghcr.io/<org>/<service>:<sha>`
- Deploys with `helm upgrade --install --atomic --timeout 5m`
- Namespace: `staging`
- Runs smoke tests after deploy (curl health endpoint)
- Uses GitHub environment `staging` (no approval gate)

### `cd-production-canary.yml`
- Triggered on `push` to tags matching `v*.*.*`
- Uses GitHub environment `production` (requires approval from `CODEOWNERS`)
- Builds and pushes images tagged `<version>` and `latest`
- Updates Argo Rollout image
- Polls `kubectl argo rollouts status` until complete or failed
- Sends Slack notification on success/failure (uses `SLACK_WEBHOOK_URL` secret)

### `security-scan.yml`
- Weekly `schedule: '0 2 * * 1'` + trigger on push to main
- Steps: Trivy image scan, `actions/dependency-review-action`, CodeQL analysis
- Uploads SARIF results to GitHub Security tab

---

## Helm Chart Requirements

- `Chart.yaml` uses `apiVersion: v2`, `type: application`
- `_helpers.tpl` provides `fullname`, `labels`, `selectorLabels` helpers
- All image tags templated via `{{ .Values.<service>.image.tag }}`
- `values-production.yaml` sets:
  - `replicaCount: 3` (minimum for zero-downtime)
  - Resource limits: `cpu: 500m`, `memory: 512Mi`; requests: `cpu: 100m`, `memory: 128Mi`
  - HPA: `minReplicas: 3`, `maxReplicas: 10`, `targetCPUUtilizationPercentage: 70`
  - PDB: `minAvailable: 2`
- `values-staging.yaml` sets `replicaCount: 1` and relaxed resources
- Ingress uses `nginx` class with `cert-manager.io/cluster-issuer: letsencrypt-prod` annotation
- `NOTES.txt` shows access URL and useful kubectl commands

---

## General Requirements

- All Kubernetes manifests use `apiVersion`/`kind`/`metadata`/`spec` structure — no shortcuts
- Labels follow the standard Kubernetes recommended labels:
  `app.kubernetes.io/name`, `app.kubernetes.io/version`, `app.kubernetes.io/component`
- All secrets are **references** (env var names with instructions to create them) — never hardcoded values
- GitHub Actions use pinned action versions (`uses: actions/checkout@v4`, etc.)
- All shell scripts start with `set -euo pipefail`
- Include `# USAGE:` comments at the top of each script explaining how to run it

---

## JSON response schema

Return a JSON object matching this schema exactly:

```json
{
  "deployment_files": [
    {
      "path": ".github/workflows/ci.yml",
      "purpose": "CI pipeline — build, test, lint, Docker build",
      "content": "__PENDING__"
    }
  ],
  "deployment_strategy": "canary",
  "ci_platform": "github-actions",
  "k8s_namespace": "production",
  "helm_chart_name": "<app-name>",
  "services_deployed": ["backend", "bff", "frontend"],
  "canary_weight_steps": [10, 25, 50, 100],
  "blue_green_switch_command": "kubectl patch svc <service> -n production -p '{\"spec\":{\"selector\":{\"slot\":\"green\"}}}'",
  "environment_variables": {
    "REGISTRY": "ghcr.io",
    "IMAGE_NAME": "${{ github.repository }}"
  },
  "secrets_required": [
    "GHCR_TOKEN — GitHub Container Registry write token",
    "KUBE_CONFIG — base64-encoded kubeconfig for the production cluster",
    "SLACK_WEBHOOK_URL — Slack incoming webhook for deploy notifications"
  ],
  "deployment_notes": [
    "Install Argo Rollouts controller: kubectl create namespace argo-rollouts && kubectl apply -n argo-rollouts -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml",
    "Install cert-manager for TLS: kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml"
  ],
  "spec_compliance_notes": [],
  "decisions": [
    {
      "decision": "Use Argo Rollouts for canary instead of Ingress-based traffic splitting",
      "rationale": "Argo Rollouts provides automated metric analysis, pause gates, and atomic rollback with no Ingress controller dependency",
      "alternatives_considered": ["NGINX Ingress canary annotations", "Flagger", "Istio"],
      "trade_offs": ["Requires Argo Rollouts controller installation", "CRD dependency"]
    }
  ],
  "review_iteration": 1,
  "review_feedback_applied": []
}
```

Set all file `content` fields to `"__PENDING__"` in the plan phase. Each file will be generated in a separate fill call.
