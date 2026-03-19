"""
Entry point for the LLM SDLC Workflow.

Usage:
    python3.11 main.py                                  # built-in example
    python3.11 main.py --requirements reqs.txt          # custom requirements
    python3.11 main.py --interactive                    # type requirements
    python3.11 main.py --config pipeline.yaml           # load from config file
    python3.11 main.py --spec openapi.yaml              # provide a single spec file
    python3.11 main.py --spec api.yaml --spec schema.sql  # multiple spec files
    python3.11 main.py --tech-constraints "Python FastAPI, PostgreSQL, Redis"
    python3.11 main.py --arch-constraints "Must be deployable on AWS Lambda"
    python3.11 main.py --from-run artifacts/run_20260318_120000  # extend existing spec
    python3.11 main.py --model gpt-4o-mini                       # use a cheaper/faster model

Spec-driven development (via config file):
  Copy pipeline.yaml, fill in the spec section, then:
    python3.11 main.py --config pipeline.yaml

  CLI flags always override values from the config file.
  The Testing Agent derives test cases solely from requirements (DiscoveryArtifact).

Incremental development (--from-run):
  Loads the existing OpenAPI + DDL from a previous pipeline run and extends it
  with new endpoints/tables only.  Existing paths get x-existing markers so
  sub-agents cannot break a running API.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from datetime import datetime
from typing import Dict, List

import yaml

import anyio
from rich.console import Console
from rich.panel import Panel

from llm_sdlc_workflow.models.artifacts import SpecArtifact
from llm_sdlc_workflow.pipeline import Pipeline, _auto_detect_resume_stage
from llm_sdlc_workflow.config import PipelineConfig, ComponentConfig, TechConfig

console = Console()

EXAMPLE_REQUIREMENTS = """
Build a task management REST API with the following features:

1. User authentication (register, login, logout) using JWT tokens
2. Users can create, read, update, and delete their own tasks
3. Tasks have: title, description, status (todo/in_progress/done), priority (low/medium/high),
   due date, and tags
4. Tasks can be filtered by status, priority, and tags
5. Pagination support for task listings (max 50 per page)
6. Users can share tasks with other users (read-only or edit access)
7. Email notifications when a shared task is updated (async, non-blocking)
8. Rate limiting: 100 requests/minute per user
9. Full audit log of all task changes (who changed what and when)
10. API must be production-ready: proper error handling, input validation, logging

Non-functional requirements:
- The API should handle 1000 concurrent users
- Response time < 200ms for 95th percentile
- 99.9% uptime target
- All sensitive data encrypted at rest and in transit
- GDPR compliant (data export and deletion endpoints)

Technology preferences: Python backend preferred, PostgreSQL for storage.
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LLM SDLC Workflow — spec-driven full-stack code generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3.11 main.py
  python3.11 main.py --requirements reqs.txt
  python3.11 main.py --config pipeline.yaml
  python3.11 main.py --spec openapi.yaml --spec db_schema.sql
  python3.11 main.py --tech-constraints "FastAPI, PostgreSQL, Redis, Celery"
  python3.11 main.py --arch-constraints "Microservices on Kubernetes"
  python3.11 main.py --requirements reqs.txt --spec api.yaml --tech-constraints "Python only"
        """,
    )
    parser.add_argument("--requirements", help="Path to requirements text file")
    parser.add_argument("--interactive", action="store_true", help="Enter requirements interactively")
    parser.add_argument("--output-dir", help="Artifacts output directory")
    parser.add_argument(
        "--config", metavar="FILE",
        help="Path to a pipeline.yaml config file (CLI flags override config values)"
    )
    parser.add_argument(
        "--spec", action="append", dest="spec_files", metavar="FILE",
        help="Path to a spec file (OpenAPI YAML, SQL schema, etc.) — can be repeated"
    )
    parser.add_argument(
        "--tech-constraints", metavar="STRING",
        help='Technology constraints, e.g. "Python FastAPI, PostgreSQL, Redis"'
    )
    parser.add_argument(
        "--arch-constraints", metavar="STRING",
        help='Architecture constraints, e.g. "Must run on AWS Lambda, serverless"'
    )
    parser.add_argument(
        "--from-run", metavar="DIR",
        help=(
            "Path to a previous pipeline run directory. Loads existing OpenAPI + DDL "
            "from generated/specs/ and passes them to the Spec Agent so the new run "
            "EXTENDS the existing contract instead of starting from scratch."
        )
    )
    parser.add_argument(
        "--resume-from", metavar="DIR",
        help=(
            "Resume a previous pipeline run. Provide the run's artifacts directory "
            "(e.g. artifacts/run_20260319_150134). The pipeline reloads completed "
            "artifacts and re-runs from --resume-stage onwards. If --resume-stage is "
            "omitted the stage is auto-detected from which artifacts are present."
        ),
    )
    parser.add_argument(
        "--resume-stage", metavar="STAGE",
        choices=["discovery", "architecture", "spec", "engineering",
                 "review", "infrastructure", "testing"],
        help=(
            "Stage to start from when using --resume-from. "
            "Choices: discovery, architecture, spec, engineering, "
            "review, infrastructure, testing. Auto-detected if omitted."
        ),
    )
    parser.add_argument(
        "--auto", action="store_true",
        help=(
            "Skip all human review checkpoints and run the pipeline end-to-end without "
            "pausing. Useful for CI/CD or when you trust the output and want a fully "
            "unattended run. Human checkpoints are ENABLED by default."
        )
    )
    parser.add_argument(
        "--project-name", metavar="NAME",
        help=(
            "Name for the generated project directory (e.g. 'my_ecommerce_app'). "
            "Generated code will be written to <output-dir>/<project-name>/. "
            "If not provided, you will be prompted for a name at startup."
        )
    )
    parser.add_argument(
        "--model", metavar="MODEL",
        default=os.getenv("PIPELINE_MODEL", "gpt-4o"),
        help=(
            "LLM model name to use for all agents "
            "(default: gpt-4o, or PIPELINE_MODEL env var). "
            "Examples: gpt-4o, gpt-4o-mini, o3-mini"
        )
    )

    # ── Component toggles ──────────────────────────────────────────────────
    comp = parser.add_argument_group("component toggles")
    comp.add_argument(
        "--no-bff", action="store_true",
        help="Disable the BFF sub-agent (useful for pure API or mobile-only projects)."
    )
    comp.add_argument(
        "--no-frontend", action="store_true",
        help="Disable the Frontend sub-agent (API-only or mobile project)."
    )
    comp.add_argument(
        "--mobile", action="store_true",
        help="Enable the Mobile sub-agent (React Native by default)."
    )

    # ── Tech-stack preferences ────────────────────────────────────────────
    tech = parser.add_argument_group("tech-stack preferences")
    tech.add_argument(
        "--backend-lang", metavar="LANG",
        help='Backend programming language, e.g. "Python", "Go", "Node.js". Default: Kotlin.'
    )
    tech.add_argument(
        "--backend-framework", metavar="FRAMEWORK",
        help='Backend framework, e.g. "FastAPI", "Gin", "Express". Default: Spring Boot.'
    )
    tech.add_argument(
        "--bff-lang", metavar="LANG",
        help='BFF programming language. Default: Kotlin.'
    )
    tech.add_argument(
        "--bff-framework", metavar="FRAMEWORK",
        help='BFF framework, e.g. "NestJS", "Spring WebFlux". Default: Spring WebFlux.'
    )
    tech.add_argument(
        "--frontend-framework", metavar="FRAMEWORK",
        help='Frontend framework, e.g. "Vue", "Angular", "Next.js". Default: React 18.'
    )
    tech.add_argument(
        "--frontend-lang", metavar="LANG",
        help='Frontend language, e.g. "TypeScript", "JavaScript". Default: TypeScript.'
    )
    tech.add_argument(
        "--mobile-platform", metavar="PLATFORM", action="append", dest="mobile_platforms",
        help=(
            'Mobile platform to generate. Can be specified multiple times to generate '
            'several platforms in parallel, e.g. '
            '--mobile-platform "iOS (Swift)" --mobile-platform "Android (Kotlin)". '
            'Implies --mobile. Valid values: "React Native", "Flutter", '
            '"iOS (Swift)", "Android (Kotlin)". Default (when --mobile is set): React Native.'
        )
    )
    return parser.parse_args()


def _apply_config(args: argparse.Namespace) -> None:
    """Merge a pipeline.yaml config file into args. CLI flags take precedence."""
    if not args.config:
        return

    config_path = args.config
    if not os.path.exists(config_path):
        console.print(f"[red]Config file not found: {config_path}[/red]")
        sys.exit(1)

    config_dir = os.path.dirname(os.path.abspath(config_path))
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}

    # requirements — only apply if not set by CLI
    if not args.requirements and cfg.get("requirements"):
        req_path = cfg["requirements"]
        if not os.path.isabs(req_path):
            req_path = os.path.join(config_dir, req_path)
        args.requirements = req_path

    # output_dir
    if not args.output_dir and cfg.get("output_dir"):
        args.output_dir = cfg["output_dir"]

    # model — only apply if user didn't pass --model explicitly and env var not set
    if args.model == os.getenv("PIPELINE_MODEL", "gpt-4o") and cfg.get("model"):
        args.model = cfg["model"]

    # spec block
    spec_cfg = cfg.get("spec") or {}

    if not args.tech_constraints and spec_cfg.get("tech_constraints"):
        args.tech_constraints = spec_cfg["tech_constraints"]

    if not args.arch_constraints and spec_cfg.get("arch_constraints"):
        args.arch_constraints = spec_cfg["arch_constraints"]

    # spec files — only apply if not already provided via --spec
    if not args.spec_files:
        cfg_files = spec_cfg.get("files") or []
        if cfg_files:
            resolved = []
            for p in cfg_files:
                if not os.path.isabs(p):
                    p = os.path.join(config_dir, p)
                resolved.append(p)
            args.spec_files = resolved

    # components block — only apply if flag not already set by CLI
    comp_cfg = cfg.get("components") or {}
    tech_cfg = cfg.get("tech") or {}

    if not args.no_bff and comp_cfg.get("bff") is False:
        args.no_bff = True
    if not args.no_frontend and comp_cfg.get("frontend") is False:
        args.no_frontend = True
    # New form: components.mobile_platforms list
    yaml_platforms = comp_cfg.get("mobile_platforms") or []
    # Old form: components.mobile: true + tech.mobile_platform scalar
    if not yaml_platforms and comp_cfg.get("mobile"):
        scalar = tech_cfg.get("mobile_platform")
        yaml_platforms = [scalar] if scalar else ["React Native"]
    if yaml_platforms and not args.mobile_platforms:
        args.mobile_platforms = yaml_platforms
        args.mobile = True  # keep the flag consistent

    # tech block
    if not args.backend_lang and tech_cfg.get("backend_language"):
        args.backend_lang = tech_cfg["backend_language"]
    if not args.backend_framework and tech_cfg.get("backend_framework"):
        args.backend_framework = tech_cfg["backend_framework"]
    if not args.bff_lang and tech_cfg.get("bff_language"):
        args.bff_lang = tech_cfg["bff_language"]
    if not args.bff_framework and tech_cfg.get("bff_framework"):
        args.bff_framework = tech_cfg["bff_framework"]
    if not args.frontend_framework and tech_cfg.get("frontend_framework"):
        args.frontend_framework = tech_cfg["frontend_framework"]
    if not args.frontend_lang and tech_cfg.get("frontend_language"):
        args.frontend_lang = tech_cfg["frontend_language"]

    console.print(f"[dim]Config loaded from {config_path}[/dim]")


def load_spec(args: argparse.Namespace) -> SpecArtifact | None:
    """Build a SpecArtifact from CLI arguments."""
    has_spec = any([args.spec_files, args.tech_constraints, args.arch_constraints])
    if not has_spec:
        return None

    additional_specs: Dict[str, str] = {}
    source_files: List[str] = []

    if args.spec_files:
        for path in args.spec_files:
            if not os.path.exists(path):
                console.print(f"[red]Spec file not found: {path}[/red]")
                sys.exit(1)
            with open(path) as f:
                content = f.read()
            ext = os.path.splitext(path)[1].lower()
            name = os.path.basename(path)
            source_files.append(path)

            # Route to the right field based on extension / content
            if ext in (".yaml", ".yml", ".json") and any(
                k in content for k in ("openapi", "swagger", "paths:")
            ):
                additional_specs["api_spec"] = content
            elif ext in (".sql", ".ddl") or "CREATE TABLE" in content.upper():
                additional_specs["database_schema"] = content
            else:
                additional_specs[name] = content

    spec = SpecArtifact(
        api_spec=additional_specs.pop("api_spec", None),
        database_schema=additional_specs.pop("database_schema", None),
        tech_stack_constraints=args.tech_constraints,
        architecture_constraints=args.arch_constraints,
        additional_specs=additional_specs,
        source_files=source_files,
    )

    parts = []
    if spec.api_spec:
        parts.append("API spec")
    if spec.database_schema:
        parts.append("DB schema")
    if spec.tech_stack_constraints:
        parts.append(f"tech: {spec.tech_stack_constraints}")
    if spec.architecture_constraints:
        parts.append(f"arch: {spec.architecture_constraints}")
    parts += list(spec.additional_specs.keys())

    console.print(Panel(
        "Spec-driven mode enabled.\n"
        "Architecture + Engineering will honour these specs.\n"
        "Testing Agent will still verify against requirements only.\n\n"
        "Specs loaded: " + ", ".join(parts),
        title="[bold yellow]Spec-Driven Development[/bold yellow]",
    ))
    return spec


def load_existing_spec(from_run_dir: str) -> SpecArtifact | None:
    """Load <project>/specs/ from a previous run to enable incremental spec extension.

    Searches for */specs/openapi.yaml (or .json) under from_run_dir so the project
    name of the previous run does not need to be known in advance.
    """
    # Find the specs directory regardless of what the previous project name was
    candidates = (
        glob.glob(os.path.join(from_run_dir, "*", "specs", "openapi.yaml"))
        + glob.glob(os.path.join(from_run_dir, "*", "specs", "openapi.json"))
    )
    if not candidates:
        console.print(
            f"[red]--from-run: no <project>/specs/openapi.yaml found under {from_run_dir}[/red]"
        )
        sys.exit(1)

    specs_dir = os.path.dirname(candidates[0])

    def _read(name: str) -> str | None:
        path = os.path.join(specs_dir, name)
        if os.path.exists(path):
            with open(path) as fh:
                return fh.read()
        return None

    openapi = _read("openapi.yaml") or _read("openapi.json")
    schema = _read("schema.sql")
    tech = _read("tech_constraints.txt")
    arch = _read("arch_constraints.txt")

    if not openapi and not schema:
        console.print(
            f"[red]--from-run: neither openapi.yaml nor schema.sql found in {specs_dir}[/red]"
        )
        sys.exit(1)

    parts = []
    if openapi:
        parts.append(f"openapi ({len(openapi.splitlines())} lines)")
    if schema:
        parts.append(f"schema.sql ({len(schema.splitlines())} lines)")
    if tech:
        parts.append("tech_constraints.txt")
    if arch:
        parts.append("arch_constraints.txt")

    console.print(Panel(
        f"Incremental spec-driven mode.\n"
        f"Loaded from: {specs_dir}\n"
        f"Existing specs: {', '.join(parts)}\n\n"
        "Spec Agent will EXTEND the existing contract.\n"
        "Existing API paths get x-existing markers — sub-agents must not alter them.",
        title="[bold yellow]--from-run: Extending Existing Spec[/bold yellow]",
    ))

    return SpecArtifact(
        api_spec=openapi,
        database_schema=schema,
        tech_stack_constraints=tech,
        architecture_constraints=arch,
        source_files=[specs_dir],
    )


def _sanitize_project_name(name: str) -> str:
    """Lowercase, spaces/dashes → underscores, keep alphanumeric + underscore only."""
    name = name.strip().lower()
    name = re.sub(r'[\s\-]+', '_', name)
    name = re.sub(r'[^\w]', '', name)
    return name or "generated"


def _resolve_project_name(args: argparse.Namespace) -> str:
    """Return the project name: from --project-name flag, TTY prompt, or default 'generated'."""
    if getattr(args, 'project_name', None):
        return _sanitize_project_name(args.project_name)
    if sys.stdin.isatty() and not getattr(args, 'auto', False):
        console.print(
            "\n[bold yellow]What should the generated project be called?[/bold yellow]\n"
            "[dim]This becomes the folder name inside your output directory.\n"
            "Examples: hello_world, my_ecommerce_app, task_manager[/dim]"
        )
        raw = input("  Project name: ").strip()
        if raw:
            name = _sanitize_project_name(raw)
            console.print(f"[green]  ✓ Using project name: [bold]{name}[/bold][/green]\n")
            return name
    return "generated"


def get_requirements(args: argparse.Namespace) -> str:
    if args.requirements:
        with open(args.requirements) as f:
            return f.read().strip()
    if args.interactive:
        console.print(Panel(
            "Enter requirements. Press Ctrl+D (Unix) or Ctrl+Z (Windows) when done.",
            title="Interactive Mode",
        ))
        return sys.stdin.read().strip()
    console.print(Panel(
        "No requirements provided — using built-in Task Management API example.\n\n"
        "Run with [bold]--requirements path.txt[/bold] to use your own.",
        title="[yellow]Using Example Requirements[/yellow]",
    ))
    return EXAMPLE_REQUIREMENTS


async def async_main(args: argparse.Namespace, requirements: str, spec, existing_spec) -> int:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    resume_from = getattr(args, "resume_from", None)
    resume_stage = getattr(args, "resume_stage", None)
    checkpoint = None

    if resume_from:
        if not os.path.isdir(resume_from):
            console.print(f"[red]--resume-from: directory not found: {resume_from}[/red]")
            return 1
        if resume_stage is None:
            resume_stage = _auto_detect_resume_stage(resume_from)
            console.print(f"[dim]Auto-detected resume stage: [cyan]{resume_stage}[/cyan][/dim]")
        checkpoint, _chk_project = Pipeline.load_checkpoint(resume_from, resume_stage)
        artifacts_dir = args.output_dir or resume_from   # reuse same run dir
        if not getattr(args, "project_name", None):
            args.project_name = _chk_project
        if not requirements and checkpoint.requirements:
            requirements = checkpoint.requirements
    else:
        project_name_early = _resolve_project_name(args)
        # Use <project-name>_run_<timestamp> so the artifact folder is traceable
        run_folder = f"{project_name_early}_run_{timestamp}"
        artifacts_dir = args.output_dir or os.path.join("artifacts", run_folder)

    human_checkpoints = not getattr(args, "auto", False)
    project_name = _resolve_project_name(args)

    # Resolve mobile_platforms list
    # --mobile-platform can be given multiple times (action=append) → list
    # --mobile alone → ["React Native"]
    raw_platforms = getattr(args, "mobile_platforms", None) or []
    if not raw_platforms and getattr(args, "mobile", False):
        raw_platforms = ["React Native"]

    # Build pipeline configuration from CLI args
    pipeline_config = PipelineConfig(
        components=ComponentConfig(
            backend=True,  # always enabled
            bff=not getattr(args, "no_bff", False),
            frontend=not getattr(args, "no_frontend", False),
            mobile_platforms=raw_platforms,
        ),
        tech=TechConfig(
            backend_language=getattr(args, "backend_lang", None),
            backend_framework=getattr(args, "backend_framework", None),
            bff_language=getattr(args, "bff_lang", None),
            bff_framework=getattr(args, "bff_framework", None),
            frontend_framework=getattr(args, "frontend_framework", None),
            frontend_language=getattr(args, "frontend_lang", None),
        ),
    )

    # Thread model selection through the env var that base_agent.py reads
    os.environ["PIPELINE_MODEL"] = args.model

    console.print(Panel(
        f"[bold]Requirements preview:[/bold]\n{requirements[:300]}"
        f"{'...' if len(requirements) > 300 else ''}\n\n"
        f"[dim]Project name      : {project_name}[/dim]\n"
        f"[dim]Generated code    : {artifacts_dir}/{project_name}/[/dim]\n"
        f"[dim]Artifacts         : {artifacts_dir}/[/dim]\n"
        f"[dim]Model             : {args.model}[/dim]\n"
        f"[dim]{pipeline_config.summary()}[/dim]\n"
        f"[dim]Human checkpoints : {'enabled (4 review pauses)' if human_checkpoints else 'disabled (--auto)'}[/dim]",
        title="Starting Pipeline",
    ))

    pipeline = Pipeline(
        artifacts_dir=artifacts_dir,
        human_checkpoints=human_checkpoints,
        project_name=project_name,
        config=pipeline_config,
    )
    result = await pipeline.run(
        requirements,
        spec=spec,
        existing_spec=existing_spec,
        resume_from_stage=resume_stage if resume_from else None,
        checkpoint=checkpoint,
    )
    pipeline.print_summary(result)
    return 0 if result.passed else 1


def main() -> int:
    args = parse_args()
    _apply_config(args)
    # When resuming, requirements can come from the checkpoint's discovery artifact
    _resume_from = getattr(args, "resume_from", None)
    if _resume_from and not getattr(args, "requirements", None) and not getattr(args, "interactive", False):
        requirements = ""  # will be loaded from checkpoint in async_main
    else:
        requirements = get_requirements(args)
    if not requirements and not _resume_from:
        console.print("[red]Error: No requirements provided.[/red]")
        return 1

    spec = load_spec(args)
    existing_spec = load_existing_spec(args.from_run) if args.from_run else None

    try:
        return anyio.run(async_main, args, requirements, spec, existing_spec)
    except KeyboardInterrupt:
        console.print("\n[yellow]Pipeline interrupted.[/yellow]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
