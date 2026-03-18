"""
Entry point for the Multi-Agent Pipeline.

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
import os
import sys
from datetime import datetime
from typing import Dict, List

import yaml

import anyio
from rich.console import Console
from rich.panel import Panel

from models.artifacts import SpecArtifact
from pipeline import Pipeline

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
        description="Multi-Agent Software Development Pipeline with Spec-Driven Development",
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
    """Load generated/specs/ from a previous run to enable incremental spec extension."""
    specs_dir = os.path.join(from_run_dir, "generated", "specs")
    if not os.path.isdir(specs_dir):
        console.print(
            f"[red]--from-run: no generated/specs/ directory found in {from_run_dir}[/red]"
        )
        sys.exit(1)

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
    artifacts_dir = args.output_dir or os.path.join("artifacts", f"run_{timestamp}")

    console.print(Panel(
        f"[bold]Requirements preview:[/bold]\n{requirements[:300]}"
        f"{'...' if len(requirements) > 300 else ''}\n\n"
        f"[dim]Artifacts → {artifacts_dir}[/dim]",
        title="Starting Pipeline",
    ))

    pipeline = Pipeline(artifacts_dir=artifacts_dir)
    result = await pipeline.run(requirements, spec=spec, existing_spec=existing_spec)
    pipeline.print_summary(result)
    return 0 if result.passed else 1


def main() -> int:
    args = parse_args()
    _apply_config(args)
    requirements = get_requirements(args)
    if not requirements:
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
