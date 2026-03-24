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
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel
from rich.console import Console
from rich.rule import Rule

# Prompts directory: src/llm_sdlc_workflow/prompts/
_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")

# Semaphore capping concurrent GitHub Models API calls.
# GitHub Models free tier: UserConcurrentRequests = 2 per 0 s.
# Lazily initialised so it's always created inside the running event loop.
_LLM_SEMAPHORE: Optional[asyncio.Semaphore] = None

# Guard to prevent nested spinners when _raw_query is called from inside
# a chunked loop that is already displaying a status line.
_SPINNER_ACTIVE: bool = False

# ─── Friendly model name display ─────────────────────────────────────────────
_MODEL_DISPLAY_NAMES: Dict[str, str] = {
    # Anthropic Claude
    "claude-haiku-4-5-20251001":   "Claude Haiku 4.5",
    "claude-haiku-3-5-20241022":   "Claude Haiku 3.5",
    "claude-sonnet-4-5-20251001":  "Claude Sonnet 4.5",
    "claude-sonnet-3-7-20250219":  "Claude Sonnet 3.7",
    "claude-opus-4-5-20251001":    "Claude Opus 4.5",
    # OpenAI
    "gpt-4o":                      "GPT-4o",
    "gpt-4o-mini":                 "GPT-4o mini",
    "gpt-4.1":                     "GPT-4.1",
    "gpt-4.1-mini":                "GPT-4.1 mini",
    "o1":                          "o1",
    "o3-mini":                     "o3 mini",
    # Google
    "gemini-2.0-flash":            "Gemini 2.0 Flash",
    "gemini-2.0-flash-lite":       "Gemini 2.0 Flash Lite",
    "gemini-1.5-pro":              "Gemini 1.5 Pro",
    # xAI
    "grok-2":                      "Grok 2",
    "grok-2-mini":                 "Grok 2 mini",
    # Mistral
    "mistral-large-latest":        "Mistral Large",
    "mistral-small-latest":        "Mistral Small",
    "codestral-latest":            "Codestral",
}


def _friendly_model_name(model: str) -> str:
    """Return a human-readable display name for a model ID.

    Falls back to a best-effort transformation for unknown IDs:
      claude-haiku-4-5-20251001 → Claude Haiku 4.5
      gpt-4o-mini              → GPT-4o mini  (passthrough, already readable)
    """
    if model in _MODEL_DISPLAY_NAMES:
        return _MODEL_DISPLAY_NAMES[model]
    # Auto-format Claude model IDs that aren't in the table
    m = model.lower()
    if m.startswith("claude-"):
        parts = m.split("-")  # e.g. ["claude","haiku","4","5","20251001"]
        if len(parts) >= 3:
            family = parts[1].capitalize()
            version_parts = [p for p in parts[2:] if not (p.isdigit() and len(p) == 8)]
            version = ".".join(version_parts)
            return f"Claude {family} {version}".strip()
    return model  # passthrough for already-readable names like gpt-4o-mini


def _get_semaphore() -> asyncio.Semaphore:
    """Return the module-level semaphore, creating it on first call.

    Anthropic org limit is 10,000 output tokens/min — use concurrency=1
    to serialise calls and avoid 429s.  GitHub Models allows 2 concurrent.
    """
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        _is_anthropic = "anthropic.com" in _BASE_URL
        _LLM_SEMAPHORE = asyncio.Semaphore(1 if _is_anthropic else 2)
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


def _issues_for_file(issues: List[str], file_path: str) -> List[str]:
    """Return only the issues from *issues* that are relevant to *file_path*.

    Relevance is determined by whether the issue text contains:
    - The file's basename (e.g. "application.yml", "TodoController.kt")
    - The file's parent directory component (e.g. "controller", "service")
    - A keyword from the path that is long enough to be meaningful (>=6 chars)

    If NO issues match the file, return ALL issues so the file still gets
    reviewed for general improvements (e.g. .gitignore, gradle files).
    """
    import os as _os
    basename = _os.path.basename(file_path).lower()
    # e.g. "TodoController.kt" → ["todocontroller", "kt", "todo", "controller"]
    path_parts = set(re.split(r"[./\\-]", file_path.lower()))
    # Only use parts long enough to be meaningful
    meaningful_parts = {p for p in path_parts if len(p) >= 5}
    meaningful_parts.add(basename)

    matched = [
        issue for issue in issues
        if any(part in issue.lower() for part in meaningful_parts)
    ]
    # Fall back to all issues if nothing matched (avoids silently skipping a file)
    return matched if matched else issues


class BaseAgent:
    def __init__(self, name: str, artifacts_dir: str = "./artifacts", generated_dir_name: str = "generated"):
        self.name = name
        self.artifacts_dir = artifacts_dir
        self.generated_dir_name = generated_dir_name
        os.makedirs(artifacts_dir, exist_ok=True)
        self.history: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []   # pipeline-level event log

    def _emit_event(self, event_type: str, message: str, detail: str = "") -> None:
        """Record an observable event (retry, self-heal, parse-error, coerce) for the decision log."""
        import time as _time
        from datetime import datetime as _dt
        entry = {
            "timestamp": _dt.now().isoformat(),
            "event_type": event_type,
            "agent": self.name,
            "message": message,
            "detail": detail,
        }
        self.events.append(entry)

    # ─── LLM ────────────────────────────────────────────────────────────────

    async def _query_and_parse(
        self,
        system: str,
        user_message: str,
        model_class: Type[T],
    ) -> T:
        """Single-shot structured query → parsed Pydantic model.

        On JSON/validation failure, makes one self-heal attempt: sends the raw
        response + error back to the LLM and asks it to return corrected JSON.
        """
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
            self._emit_event(
                "parse_error",
                f"JSON/validation error — attempting self-heal",
                detail=str(e)[:300],
            )
            console.print(f"[red]JSON parse error in {self.name}:[/red] {e}")
            console.print(f"[dim]Raw (first 800 chars):\n{raw[:800]}[/dim]")
            return await self._self_heal(system, raw, e, model_class)

    async def _self_heal(
        self,
        system: str,
        raw: str,
        original_error: Exception,
        model_class: Type[T],
    ) -> T:
        """Ask the LLM to fix its own malformed JSON response (one attempt).

        Sends the original response + the validation error back, requesting a
        corrected JSON object.  Emits a ``self_heal`` event whether it succeeds
        or not so the decision log always has a full trace.
        """
        heal_prompt = (
            f"Your previous response caused a validation error:\n"
            f"```\n{original_error}\n```\n\n"
            f"Here is the original response (first 3000 chars):\n"
            f"```\n{raw[:3000]}\n```\n\n"
            "Please return ONLY a corrected, valid JSON object.\n"
            "Rules:\n"
            "  1. Every list field must contain plain strings, not objects or dicts.\n"
            "  2. Every required field must be present.\n"
            "  3. No extra keys; no markdown fences; raw JSON only."
        )
        console.print(f"[yellow]🔧 {self.name} — self-healing malformed response…[/yellow]")
        try:
            healed_raw = await self._run_with_retry(system, heal_prompt)
            self._add_to_history("user", heal_prompt)
            self._add_to_history("assistant", healed_raw or "")
            if not healed_raw:
                raise ValueError("Self-heal returned empty response.")
            data = self._extract_json(healed_raw)
            result = model_class(**data)
            self._emit_event(
                "self_heal",
                "Self-heal succeeded — corrected JSON accepted",
                detail=f"original error: {str(original_error)[:200]}",
            )
            console.print(f"[green]✅ {self.name} — self-heal succeeded.[/green]")
            return result
        except Exception as heal_err:
            self._emit_event(
                "self_heal",
                "Self-heal FAILED — raising original error",
                detail=f"heal error: {str(heal_err)[:200]} | original: {str(original_error)[:200]}",
            )
            console.print(f"[red]{self.name} — self-heal also failed: {heal_err}[/red]")
            raise original_error  # raise the first error so the caller sees the root cause

    async def _two_phase_parse(
        self,
        system: str,
        phase1_message: str,
        phase2_message: str,
        model_class: Type[T],
        *,
        merge_key: str = "decisions",
        phase1_label: str = "phase 1",
        phase2_label: str = "phase 2",
    ) -> T:
        """Two-phase structured query.

        Phase 1 produces the main artifact body with ``merge_key`` set to [].
        Phase 2 asks only for the ``merge_key`` field (e.g. decisions / issues).
        The two responses are merged before Pydantic validation.

        Benefits:
        - Each LLM call is ~30-50 % smaller → faster token generation.
        - Progress is visible between phases instead of one long silence.
        - Phase 2 failure is non-fatal (merge_key falls back to []).
        """
        # ── Phase 1 ──────────────────────────────────────────────────────────
        console.print(Rule(f"[bold cyan]{self.name} — {phase1_label}[/bold cyan]"))
        self._add_to_history("user", phase1_message)
        raw1 = await self._run_with_retry(system, phase1_message)
        self._add_to_history("assistant", raw1 or "")
        console.print(Rule())
        if not raw1:
            raise ValueError(f"{self.name} ({phase1_label}) returned empty response.")
        try:
            data = self._extract_json(raw1)
        except Exception as e:
            # Self-heal phase 1 — it carries the main artifact body so failure is fatal
            self._emit_event("parse_error", f"Phase 1 parse error — attempting self-heal", detail=str(e)[:300])
            console.print(f"[red]Phase 1 parse error in {self.name}:[/red] {e}")
            healed = await self._self_heal(system, raw1, e, model_class)
            return healed
        data.setdefault(merge_key, [])

        # ── Phase 2 ──────────────────────────────────────────────────────────
        console.print(Rule(f"[bold cyan]{self.name} — {phase2_label}[/bold cyan]"))
        self._add_to_history("user", phase2_message)
        raw2 = await self._run_with_retry(system, phase2_message)
        self._add_to_history("assistant", raw2 or "")
        console.print(Rule())
        if raw2:
            try:
                d2 = self._extract_json(raw2)
                # Support both {"decisions": [...]} and {"issues": [...]} shapes
                if merge_key in d2:
                    data[merge_key] = d2[merge_key]
                else:
                    # merge_key may be a top-level list of dicts — or a sub-object
                    data.update({k: v for k, v in d2.items() if k not in data or not data[k]})
            except Exception:
                pass  # phase 2 is non-critical

        try:
            return model_class(**data)
        except Exception as e:
            console.print(f"[red]Two-phase parse error in {self.name}:[/red] {e}")
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
                        # Single-file fill calls only need ~8k tokens max
                        fill_raw = await self._raw_query(fill_system, fill_msg, max_tokens=8192)
                        content = self._extract_content_field(fill_raw)
                        if content:
                            file_list[i]["content"] = content
                            break
                    except Exception as e:
                        if attempt == MAX_RETRIES:
                            console.print(f"[yellow]  ⚠ Could not generate {path}: {e}[/yellow]")
                            file_list[i]["content"] = f"# TODO: generate {path}\n"
                        else:
                            await asyncio.sleep(RETRY_DELAY)
                # Pause between fill calls — longer for Anthropic to stay under
                # the 10k output-tokens/min org rate limit.
                _inter_call_delay = 2.0 if "anthropic.com" in _BASE_URL else 0.5
                await asyncio.sleep(_inter_call_delay)

            data[key] = file_list

        try:
            return model_class(**data)
        except Exception as e:
            console.print(f"[red]Chunked parse error in {self.name}:[/red] {e}")
            raise

    async def _patch_files_chunked(
        self,
        system: str,
        existing_artifact: "BaseModel",
        feedback: "ReviewFeedback",
        model_class: Type[T],
        file_keys: List[str],
        spec_context: str = "",
    ) -> T:
        """Targeted patching mode for review feedback iterations.

        Instead of regenerating all files from scratch, this method:
        1. Preserves all non-file fields from the existing artifact (tech stack, env vars…)
        2. For each file: sends the CURRENT content + specific review issues to the LLM
        3. LLM produces a surgical fix rather than a full re-generation

        This prevents the "random regeneration" problem where the LLM introduces new bugs
        each review iteration because it cannot see the existing generated code.

        spec_context: optional contract/OpenAPI snippet injected into each patch prompt so
        the LLM knows the authoritative API shape when fixing DTOs, controllers, etc.
        """
        from llm_sdlc_workflow.models.artifacts import ReviewFeedback as _RF  # noqa: F401
        console.print(Rule(f"[bold yellow]{self.name} (patch)[/bold yellow]"))

        # Collect all issues (critical + high) into one list
        all_issues = list(feedback.critical_issues) + list(feedback.high_issues)

        # Dump existing artifact → mutable dict, preserving all non-file fields
        data: Dict = json.loads(existing_artifact.model_dump_json())

        # Build path → existing content map before resetting to __PENDING__
        content_map: Dict[str, str] = {}
        for key in file_keys:
            for fe in data.get(key, []):
                path = fe.get("path", "")
                content = fe.get("content", "")
                if path and content and content.strip() not in ("__PENDING__", ""):
                    content_map[path] = content
                fe["content"] = "__PENDING__"

        total = sum(len(data.get(k, [])) for k in file_keys)
        console.print(
            f"[dim]  Patching {total} files with targeted fixes (review iter {feedback.iteration})[/dim]"
        )
        _inter_call_delay = 2.0 if "anthropic.com" in _BASE_URL else 0.5

        for key in file_keys:
            file_list: List[Dict] = data.get(key, [])
            for i, file_entry in enumerate(file_list):
                path = file_entry.get("path", f"file_{i}")
                purpose = file_entry.get("purpose", "")
                existing_content = content_map.get(path, "")
                console.print(f"[dim]  ✍  Patching: {path}[/dim]")

                # Filter issues to those relevant to THIS specific file
                file_issues = _issues_for_file(all_issues, path)
                issues_str = (
                    "\n".join(f"  - {iss}" for iss in file_issues)
                    if file_issues
                    else "  (no specific issues for this file)"
                )

                # Inject authoritative API contract so the LLM knows the
                # correct DTO shapes, endpoint signatures, and response bodies
                # when fixing controllers, services, and data classes.
                spec_block = (
                    f"\n## API Contract (authoritative — your code MUST conform):\n"
                    f"```yaml\n{spec_context}\n```\n"
                    if spec_context else ""
                )

                if existing_content:
                    fill_msg = (
                        f"Fix specific code-review issues in this existing file.\n\n"
                        f"File: {path}\n"
                        f"Purpose: {purpose}\n"
                        f"{spec_block}\n"
                        f"## Issues to fix (only those relevant to THIS file):\n{issues_str}\n\n"
                        f"## Existing file content (apply fixes, keep everything else intact):\n"
                        f"```\n{existing_content[:6000]}\n```\n\n"
                        "Output the COMPLETE corrected file. Do NOT truncate. No TODOs.\n"
                        'Return JSON: {"content": "<full corrected file content>"}\nValid json.'
                    )
                else:
                    fill_msg = (
                        f"Generate COMPLETE content for this new file.\n\n"
                        f"File: {path}\n"
                        f"Purpose: {purpose}\n"
                        f"{spec_block}\n"
                        f"## Known issues to avoid:\n{issues_str}\n\n"
                        'Return JSON: {"content": "<full file content>"}\nNo TODOs. Valid json.'
                    )

                for attempt in range(1, MAX_RETRIES + 1):
                    try:
                        fill_raw = await self._raw_query(system, fill_msg, max_tokens=8192)
                        content = self._extract_content_field(fill_raw)
                        if content:
                            file_list[i]["content"] = content
                            break
                    except Exception as e:
                        if attempt == MAX_RETRIES:
                            console.print(f"[yellow]  ⚠ Could not patch {path}: {e}[/yellow]")
                            # Fall back to existing content — a known-broken file is better than __PENDING__
                            file_list[i]["content"] = existing_content or f"# TODO: generate {path}\n"
                        else:
                            await asyncio.sleep(RETRY_DELAY)
                await asyncio.sleep(_inter_call_delay)

            data[key] = file_list

        try:
            return model_class(**data)
        except Exception as e:
            console.print(f"[red]Patch parse error in {self.name}:[/red] {e}")
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
                    self._emit_event(
                        "retry",
                        f"Attempt {attempt}/{MAX_RETRIES} failed — retrying in {RETRY_DELAY}s",
                        detail=str(e)[:200],
                    )
                    console.print(
                        f"[yellow][{self.name}] Attempt {attempt} failed: {e}. "
                        f"Retrying in {RETRY_DELAY}s…[/yellow]"
                    )
                    await asyncio.sleep(RETRY_DELAY)
        raise last_err  # type: ignore

    async def _raw_query(self, system: str, user_message: str, max_tokens: int = 16384) -> str:
        """Single call to the LLM API with json_object output.

        Protected by a module-level asyncio.Semaphore so that at most N
        concurrent LLM calls are ever in flight (N=1 for Anthropic, 2 otherwise).
        Pass max_tokens=8192 for fill-phase calls that only generate one file.
        """
        global _SPINNER_ACTIVE
        client = _make_client()
        # Anthropic's OpenAI-compat endpoint does not support json_object —
        # only json_schema (or no response_format at all).  All our prompts
        # already instruct the model to reply with a raw JSON block, so we
        # can safely omit response_format for Anthropic and keep it for others.
        _is_anthropic = "anthropic.com" in _BASE_URL
        extra: dict = {} if _is_anthropic else {"response_format": {"type": "json_object"}}
        # Re-read at call time so --model / PIPELINE_MODEL set after import takes effect
        _model = os.getenv("PIPELINE_MODEL", _DEFAULT_MODEL)

        spinner_label = f"[dim cyan]  ⏳  {self.name} — thinking with {_friendly_model_name(_model)}…[/dim cyan]"
        t0 = time.monotonic()

        async with _get_semaphore():
            if not _SPINNER_ACTIVE:
                _SPINNER_ACTIVE = True
                try:
                    with console.status(spinner_label, spinner="dots"):
                        response = await client.chat.completions.create(
                            model=_model,
                            messages=[
                                {"role": "system", "content": system},
                                {"role": "user",   "content": user_message},
                            ],
                            max_tokens=max_tokens,
                            **extra,
                        )
                finally:
                    _SPINNER_ACTIVE = False
            else:
                response = await client.chat.completions.create(
                    model=_model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user_message},
                    ],
                    max_tokens=max_tokens,
                    **extra,
                )

        elapsed = time.monotonic() - t0
        console.print(f"[dim]  ✓ response in {elapsed:.1f}s[/dim]")
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

    def _extract_content_field(self, text: str) -> str:
        """Extract the 'content' value from a single-key {"content": "..."} response.

        Handles cases where the content contains backticks (Markdown code fences)
        or backslash sequences (Kotlin/Java regex) that make json.loads fail.
        Falls back to a regex that grabs everything between the first
        '"content":' and the final closing quote before '}'.
        """
        # 1. Happy path — well-formed JSON
        try:
            data = self._extract_json(text)
            if isinstance(data, dict) and "content" in data:
                return data["content"]
        except Exception:
            pass

        # 2. Strip outer ```json ... ``` fences if present
        stripped = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.DOTALL)
        stripped = re.sub(r"\s*```$", "", stripped, flags=re.DOTALL).strip()

        # 3. Robust fallback: find "content": then grab everything up to the
        #    last '"' before the closing '}' — tolerates backticks and
        #    unescaped backslashes inside the value.
        m = re.search(r'"content"\s*:\s*"(.*)"|"content"\s*:\s*\'(.*)\'',
                      stripped, re.DOTALL)
        if m:
            raw = m.group(1) if m.group(1) is not None else m.group(2)
            # Unescape only the JSON sequences Claude reliably emits
            raw = raw.replace("\\n", "\n").replace("\\t", "\t")
            raw = raw.replace('\\"', '"').replace("\\\\", "\\")
            return raw

        raise ValueError(f"Could not extract 'content' field: {text[:200]}")

    def _extract_json(self, text: str) -> Dict:
        # 1. Raw parse first — model sometimes returns plain JSON without fences
        stripped = text.strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                pass

        # 2. Greedy fence match — .*  (not .*?) so we stop at the LAST ``` in the
        #    text rather than the first.  This handles cases where the JSON value
        #    itself contains embedded ```json ... ``` blocks (e.g. requirements text
        #    with code examples), which would prematurely terminate a non-greedy match.
        m = re.search(r"```json\s*(.*)\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        m = re.search(r"```\s*([\[{].*)\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        # 3. Brace-balanced extraction — scan character-by-character to find the
        #    outermost JSON object/array, correctly ignoring braces inside strings.
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            start = text.find(open_ch)
            if start == -1:
                continue
            depth = 0
            in_str = False
            esc = False
            end = -1
            for i, ch in enumerate(text[start:], start):
                if esc:
                    esc = False
                    continue
                if ch == "\\" and in_str:
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == open_ch:
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end != -1:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass

        raise ValueError("No JSON object found in agent response.")

    def _add_to_history(self, role: str, content: str) -> None:
        self.history.append({
            "role": role,
            "content": content,
            "agent": self.name,
            "timestamp": datetime.now().isoformat(),
        })
