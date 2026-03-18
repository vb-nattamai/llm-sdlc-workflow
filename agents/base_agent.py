"""
Base agent — supports GitHub Models and any OpenAI-compatible provider:
  - Compact context formatting (passes summaries, not raw JSON blobs)
  - Retry logic (3 attempts with backoff)
  - GitHub token auto-resolved via GITHUB_TOKEN env var or 'gh auth token'
  - Chunked file generation: large file lists are generated one file at a time
    so no single LLM call exceeds the safe token budget
  - Prompt loading from prompts/ directory

Environment variables:
  GITHUB_TOKEN      — GitHub token for GitHub Models (falls back to 'gh auth token')
  PIPELINE_API_KEY  — API key override for non-GitHub providers (OpenAI, xAI, Google, Mistral…)
                      When set, GITHUB_TOKEN / gh auth token are NOT used.
  PIPELINE_BASE_URL — API base URL (default: https://models.inference.ai.azure.com)
                      Override to point at any OpenAI-compatible endpoint:
                        OpenAI   → https://api.openai.com/v1
                        xAI      → https://api.x.ai/v1
                        Google   → https://generativelanguage.googleapis.com/v1beta/openai/
                        Mistral  → https://api.mistral.ai/v1
                        Ollama   → http://localhost:11434/v1
  PIPELINE_MODEL    — model name to use (default: gpt-4o)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel
from rich.console import Console
from rich.rule import Rule

# Prompts directory: <repo_root>/prompts/
_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")

# Semaphore capping concurrent GitHub Models API calls.
# GitHub Models free tier: UserConcurrentRequests = 2 per 0 s.
# Lazily initialised so it's always created inside the running event loop.
_LLM_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    """Return the module-level semaphore, creating it on first call."""
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        _LLM_SEMAPHORE = asyncio.Semaphore(2)
    return _LLM_SEMAPHORE


def load_prompt(filename: str) -> str:
    """Load a system prompt from the prompts/ directory."""
    path = os.path.normpath(os.path.join(_PROMPTS_DIR, filename))
    with open(path) as f:
        return f.read().strip()


T = TypeVar("T", bound=BaseModel)
console = Console()

MAX_RETRIES = 3
RETRY_DELAY = 5        # seconds between retries

# Default endpoint — GitHub Models (OpenAI-compatible, Azure-hosted)
_GITHUB_MODELS_URL = "https://models.inference.ai.azure.com"

# Override the endpoint via PIPELINE_BASE_URL to use any OpenAI-compatible provider
_BASE_URL = os.getenv("PIPELINE_BASE_URL", _GITHUB_MODELS_URL)

# Override the model via PIPELINE_MODEL or --model CLI flag
_DEFAULT_MODEL = os.getenv("PIPELINE_MODEL", "gpt-4o")


def _get_github_token() -> str:
    """Return a GitHub token for the GitHub Models API."""
    token = os.getenv("GITHUB_TOKEN")
    if token:
        return token
    try:
        token = subprocess.check_output(
            ["gh", "auth", "token"], stderr=subprocess.DEVNULL
        ).decode().strip()
        if token:
            return token
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    raise EnvironmentError(
        "No GitHub token found. Set GITHUB_TOKEN or run 'gh auth login'.\n"
        "For non-GitHub providers set PIPELINE_API_KEY instead."
    )


def _get_api_key() -> str:
    """Return the API key for the configured provider.

    PIPELINE_API_KEY takes priority — use this for OpenAI, xAI, Google,
    Mistral, or any other non-GitHub provider.
    Falls back to GitHub token resolution for GitHub Models.
    """
    key = os.getenv("PIPELINE_API_KEY")
    if key:
        return key
    return _get_github_token()


def _make_client() -> AsyncOpenAI:
    """Create an AsyncOpenAI client pointed at the configured provider endpoint."""
    return AsyncOpenAI(base_url=_BASE_URL, api_key=_get_api_key())


class BaseAgent:
    def __init__(self, name: str, artifacts_dir: str = "./artifacts", generated_dir_name: str = "generated"):
        self.name = name
        self.artifacts_dir = artifacts_dir
        self.generated_dir_name = generated_dir_name
        os.makedirs(artifacts_dir, exist_ok=True)
        self.history: List[Dict[str, Any]] = []

    # ─── LLM ────────────────────────────────────────────────────────────────

    async def _query_and_parse(
        self,
        system: str,
        user_message: str,
        model_class: Type[T],
    ) -> T:
        """Single-shot structured query → parsed Pydantic model."""
        console.print(Rule(f"[bold cyan]{self.name}[/bold cyan]"))
        self._add_to_history("user", f"{system}\n\n---\n\n{user_message}")
        raw = await self._run_with_retry(system, user_message)
        self._add_to_history("assistant", raw or "")
        console.print(Rule())
        if not raw:
            raise ValueError(f"{self.name} returned an empty response — try again.")
        try:
            data = self._extract_json(raw)
            return model_class(**data)
        except Exception as e:
            console.print(f"[red]JSON parse error in {self.name}:[/red] {e}")
            console.print(f"[dim]Raw (first 1000 chars):\n{raw[:1000]}[/dim]")
            raise

    async def _query_and_parse_chunked(
        self,
        system: str,
        plan_message: str,
        file_keys: List[str],
        model_class: Type[T],
        *,
        file_system_prompt: Optional[str] = None,
        fill_message_tmpl: Optional[str] = None,
        fill_context: Optional[Dict[str, str]] = None,
    ) -> T:
        """
        Two-phase generation for artifacts that contain large embedded files.

        Phase 1 — Plan: generate the full artifact JSON with every file's
          ``content`` field set to ``"__PENDING__"``.

        Phase 2 — Fill: for each pending file make a focused single-file call
          returning only {\"content\": \"<full text>\"}.

        This keeps every individual LLM call small and well-formed.
        """
        console.print(Rule(f"[bold cyan]{self.name} (plan)[/bold cyan]"))

        plan_instruction = (
            "\n\nIMPORTANT: For every file entry in generated_files / iac_files "
            "set its \"content\" field to the exact string \"__PENDING__\". "
            "Do NOT include actual file content in this response — that comes next. "
            "Every other field must be complete and accurate."
        )
        plan_raw = await self._run_with_retry(system, plan_message + plan_instruction)
        self._add_to_history("user", plan_message)
        self._add_to_history("assistant", plan_raw or "")
        console.print(Rule())

        if not plan_raw:
            raise ValueError(f"{self.name} (plan) returned an empty response.")

        data = self._extract_json(plan_raw)
        fill_system = file_system_prompt or system

        for key in file_keys:
            file_list: List[Dict] = data.get(key, [])
            for i, file_entry in enumerate(file_list):
                if str(file_entry.get("content", "")).strip() != "__PENDING__":
                    continue
                path = file_entry.get("path", f"file_{i}")
                purpose = file_entry.get("purpose", "")
                console.print(f"[dim]  ✍  Generating: {path}[/dim]")

                if fill_message_tmpl:
                    fmt_vars = {"path": path, "purpose": purpose}
                    if fill_context:
                        fmt_vars.update(fill_context)
                    fill_msg = fill_message_tmpl.format(**fmt_vars)
                else:
                    context_snapshot = {
                        k: v for k, v in data.items() if k != key
                    }
                    fill_msg = (
                        f"Generate the COMPLETE, RUNNABLE content for this file.\n\n"
                        f"File path: {path}\nPurpose: {purpose}\n\n"
                        f"Project context:\n{json.dumps(context_snapshot, indent=2)[:3000]}\n\n"
                        "Return a JSON object with a single key \"content\" containing "
                        "the full file text. No other keys."
                    )
                for attempt in range(1, MAX_RETRIES + 1):
                    try:
                        fill_raw = await self._raw_query(fill_system, fill_msg)
                        fill_data = self._extract_json(fill_raw)
                        content = fill_data.get("content", "")
                        if content:
                            file_list[i]["content"] = content
                            break
                    except Exception as e:
                        if attempt == MAX_RETRIES:
                            console.print(f"[yellow]  ⚠ Could not generate {path}: {e}[/yellow]")
                            file_list[i]["content"] = f"# TODO: generate {path}\n"
                        else:
                            await asyncio.sleep(RETRY_DELAY)
                # Small pause between fill calls to spread burst traffic.
                await asyncio.sleep(0.5)

            data[key] = file_list

        try:
            return model_class(**data)
        except Exception as e:
            console.print(f"[red]Chunked parse error in {self.name}:[/red] {e}")
            raise

    async def _run_with_retry(self, system: str, user_message: str) -> str:
        """Run a single LLM call with up to MAX_RETRIES attempts."""
        last_err: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return await self._raw_query(system, user_message)
            except Exception as e:
                last_err = e
                if attempt < MAX_RETRIES:
                    console.print(
                        f"[yellow][{self.name}] Attempt {attempt} failed: {e}. "
                        f"Retrying in {RETRY_DELAY}s…[/yellow]"
                    )
                    await asyncio.sleep(RETRY_DELAY)
        raise last_err  # type: ignore

    async def _raw_query(self, system: str, user_message: str) -> str:
        """Single call to the GitHub Models API with json_object output.

        Protected by a module-level asyncio.Semaphore(2) so that at most two
        concurrent LLM calls are ever in flight across all agents, keeping the
        pipeline within the GitHub Models free-tier concurrency limit.
        """
        client = _make_client()
        async with _get_semaphore():
            response = await client.chat.completions.create(
                model=_DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user_message},
                ],
                max_tokens=16384,
                response_format={"type": "json_object"},
            )
        return response.choices[0].message.content or ""

    # ─── Context formatting ──────────────────────────────────────────────────

    def _compact(self, artifact: BaseModel, max_list: int = 8) -> str:
        """
        Compact markdown summary of an artifact for downstream prompts.
        File contents are always stripped — only path/purpose shown.
        """
        lines: List[str] = [f"### {type(artifact).__name__}"]
        data = artifact.model_dump()

        def _fmt_item(v: Any) -> str:
            if isinstance(v, dict):
                parts = [
                    f"{k}: {str(val)[:80]}"
                    for k, val in list(v.items())[:4]
                    if k not in ("timestamp", "content")
                ]
                return "{" + ", ".join(parts) + "}"
            s = str(v)
            return s if len(s) <= 120 else s[:117] + "…"

        def _fmt_val(v: Any, depth: int = 0) -> str:
            indent = "  " * depth
            if isinstance(v, list):
                if not v:
                    return "(none)"
                items = v[:max_list]
                rest = len(v) - max_list
                out = "\n".join(f"{indent}  - {_fmt_item(i)}" for i in items)
                if rest > 0:
                    out += f"\n{indent}  - … and {rest} more"
                return "\n" + out
            if isinstance(v, dict):
                if not v:
                    return "(empty)"
                items = list(v.items())[:max_list]
                return "\n" + "\n".join(f"{indent}  {k}: {_fmt_item(val)}" for k, val in items)
            return _fmt_item(v)

        for key, val in data.items():
            if key in ("raw_requirements", "decisions", "history", "design_decisions"):
                continue
            if key in ("generated_files", "iac_files") and isinstance(val, list):
                label = key.replace("_", " ").title()
                lines.append(f"\n**{label}:**")
                for f in val[:max_list]:
                    if isinstance(f, dict):
                        lines.append(f"  - {f.get('path','?')} — {f.get('purpose','')[:80]}")
                if len(val) > max_list:
                    lines.append(f"  - … and {len(val) - max_list} more")
                continue
            label = key.replace("_", " ").title()
            lines.append(f"\n**{label}:** {_fmt_val(val)}")

        decisions = data.get("decisions", []) or data.get("design_decisions", [])
        if decisions:
            lines.append("\n**Key Decisions:**")
            for d in decisions[:3]:
                lines.append(
                    f"  - {d.get('decision','')[:100]} "
                    f"(reason: {d.get('rationale','')[:80]})"
                )
        return "\n".join(lines)

    # ─── Artifact I/O ────────────────────────────────────────────────────────

    def save_artifact(self, artifact: Any, filename: str) -> str:
        path = os.path.join(self.artifacts_dir, filename)
        with open(path, "w") as f:
            if isinstance(artifact, BaseModel):
                f.write(artifact.model_dump_json(indent=2))
            else:
                json.dump(artifact, f, indent=2)
        console.print(f"[dim]✅ Artifact saved → {path}[/dim]")
        return path

    def load_artifact(self, filename: str) -> Optional[Dict]:
        path = os.path.join(self.artifacts_dir, filename)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        return None

    def save_history(self) -> str:
        filename = f"{self.name.lower().replace(' ', '_')}_history.json"
        path = os.path.join(self.artifacts_dir, filename)
        with open(path, "w") as f:
            json.dump(self.history, f, indent=2)
        return path

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _extract_json(self, text: str) -> Dict:
        m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        m = re.search(r"```\s*([\[{].*?)\s*```", text, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}") + 1
        if 0 <= start < end:
            return json.loads(text[start:end])
        raise ValueError("No JSON object found in agent response.")

    def _add_to_history(self, role: str, content: str) -> None:
        self.history.append({
            "role": role,
            "content": content,
            "agent": self.name,
            "timestamp": datetime.now().isoformat(),
        })
