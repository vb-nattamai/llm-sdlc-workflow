"""
PipelineConfig — controls which agents run and what tech stack they target.

All fields have sensible defaults so existing code continues to work unchanged.
Pass an instance to Pipeline(..., config=PipelineConfig(...)) to customise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ─── Component toggles ────────────────────────────────────────────────────────

@dataclass
class ComponentConfig:
    """Which service sub-agents are enabled.

    ``mobile_platforms`` is a list of platform names to generate simultaneously.
    Each entry spawns an independent MobileAgent running in parallel.

    Examples::

        ComponentConfig(mobile_platforms=["React Native"])          # single
        ComponentConfig(mobile_platforms=["iOS (Swift)", "Android (Kotlin)"])  # both native
        ComponentConfig(mobile_platforms=["Flutter"])               # cross-platform
    """
    backend: bool = True
    bff: bool = True
    frontend: bool = True
    mobile_platforms: List[str] = field(default_factory=list)
    # ^ empty list = mobile disabled; one or more entries = that many parallel agents

    @property
    def mobile(self) -> bool:
        """True when at least one mobile platform is configured."""
        return bool(self.mobile_platforms)


# ─── Tech-stack preferences ───────────────────────────────────────────────────

@dataclass
class TechConfig:
    """
    Language / framework preferences forwarded to each sub-agent via the
    system prompt.  Leave None to keep each agent's built-in default.
    """

    # Backend
    backend_language: Optional[str] = None       # e.g. "Python", "Kotlin", "Go", "Node.js"
    backend_framework: Optional[str] = None      # e.g. "FastAPI", "Spring Boot", "Gin", "Express"

    # BFF
    bff_language: Optional[str] = None           # e.g. "Kotlin", "Node.js"
    bff_framework: Optional[str] = None          # e.g. "Spring WebFlux", "NestJS"

    # Frontend
    frontend_framework: Optional[str] = None     # e.g. "React", "Vue", "Angular", "Next.js"
    frontend_language: Optional[str] = None      # e.g. "TypeScript", "JavaScript"

    def backend_hint(self) -> str:
        """Short human-readable hint, e.g. 'Python / FastAPI'."""
        parts = [p for p in [self.backend_language, self.backend_framework] if p]
        return " / ".join(parts) if parts else ""

    def bff_hint(self) -> str:
        parts = [p for p in [self.bff_language, self.bff_framework] if p]
        return " / ".join(parts) if parts else ""

    def frontend_hint(self) -> str:
        parts = [p for p in [self.frontend_framework, self.frontend_language] if p]
        return " / ".join(parts) if parts else ""


def platform_slug(platform: str) -> str:
    """Convert a platform name to a safe directory / dict key.

    Examples::

        platform_slug("React Native")      → "mobile_react_native"
        platform_slug("iOS (Swift)")        → "mobile_ios_swift"
        platform_slug("Android (Kotlin)")   → "mobile_android_kotlin"
        platform_slug("Flutter")            → "mobile_flutter"
    """
    slug = re.sub(r"[^a-z0-9]+", "_", platform.lower()).strip("_")
    return f"mobile_{slug}"


# ─── Top-level config ─────────────────────────────────────────────────────────

@dataclass
class PipelineConfig:
    """
    Full pipeline configuration.

    Usage
    -----
    # Default (Kotlin BE + BFF + React FE — same as before)
    Pipeline(config=PipelineConfig())

    # Python/FastAPI backend only, no BFF, no frontend
    Pipeline(config=PipelineConfig(
        components=ComponentConfig(bff=False, frontend=False),
        tech=TechConfig(backend_language="Python", backend_framework="FastAPI"),
    ))

    # Single React Native mobile app
    Pipeline(config=PipelineConfig(
        components=ComponentConfig(mobile_platforms=["React Native"]),
    ))

    # Dual native: iOS + Android generated in parallel
    Pipeline(config=PipelineConfig(
        components=ComponentConfig(
            mobile_platforms=["iOS (Swift)", "Android (Kotlin)"],
        ),
    ))

    # Full custom stack
    Pipeline(config=PipelineConfig(
        components=ComponentConfig(bff=False),
        tech=TechConfig(
            backend_language="Go", backend_framework="Gin",
            frontend_framework="Vue", frontend_language="TypeScript",
        ),
    ))
    """
    components: ComponentConfig = field(default_factory=ComponentConfig)
    tech: TechConfig = field(default_factory=TechConfig)
    max_review_iterations: int = 3  # max review/patch cycles (overridable via pipeline.yaml)

    @classmethod
    def from_dict(cls, d: dict) -> "PipelineConfig":
        """Build from a plain dict (e.g. loaded from pipeline.yaml).

        Supports both the new list form and the old scalar for backward compat::

            # new
            components:
              mobile_platforms: ["iOS (Swift)", "Android (Kotlin)"]

            # old (still works)
            components:
              mobile: true
            tech:
              mobile_platform: "Flutter"
        """
        comp = d.get("components", {})
        tech = d.get("tech", {})

        # Resolve mobile_platforms — new list form takes precedence
        mobile_platforms: List[str] = comp.get("mobile_platforms") or []
        if not mobile_platforms:
            # Backward compat: components.mobile: true + (optional) tech.mobile_platform
            if comp.get("mobile"):
                plat = tech.get("mobile_platform") or "React Native"
                mobile_platforms = [plat]

        return cls(
            components=ComponentConfig(
                backend=comp.get("backend", True),
                # Default to False when key is absent — pipeline.yaml is CLI-driven
                # (API-only by default).  Explicit true enables the sub-agent.
                bff=comp.get("bff", False),
                frontend=comp.get("frontend", False),
                mobile_platforms=mobile_platforms,
            ),
            tech=TechConfig(
                backend_language=tech.get("backend_language"),
                backend_framework=tech.get("backend_framework"),
                bff_language=tech.get("bff_language"),
                bff_framework=tech.get("bff_framework"),
                frontend_framework=tech.get("frontend_framework"),
                frontend_language=tech.get("frontend_language"),
            ),
            max_review_iterations=int(
                d.get("pipeline", {}).get("max_review_iterations", 3)
            ),
        )

    def enabled_services(self) -> List[str]:
        """Return list of enabled service names, in order."""
        svcs = []
        if self.components.backend:
            svcs.append("backend")
        if self.components.bff:
            svcs.append("bff")
        if self.components.frontend:
            svcs.append("frontend")
        for p in self.components.mobile_platforms:
            svcs.append(platform_slug(p))
        return svcs

    def summary(self) -> str:
        """One-line human-readable summary for console output."""
        svcs = self.enabled_services()
        tech_parts = []
        if self.components.backend and self.tech.backend_hint():
            tech_parts.append(f"BE:{self.tech.backend_hint()}")
        if self.components.bff and self.tech.bff_hint():
            tech_parts.append(f"BFF:{self.tech.bff_hint()}")
        if self.components.frontend and self.tech.frontend_hint():
            tech_parts.append(f"FE:{self.tech.frontend_hint()}")
        for p in self.components.mobile_platforms:
            tech_parts.append(f"Mobile:{p}")
        tech_str = f"  [{', '.join(tech_parts)}]" if tech_parts else ""
        return f"Services: {', '.join(svcs)}{tech_str}"


# ─── Topology contract ───────────────────────────────────────────────────────

@dataclass
class TopologyContract:
    """
    Computed once from PipelineConfig before any agent runs.

    This is the single source of truth for which services exist, what ports
    they use, and which service is externally exposed.  All agents receive
    relevant fields from this contract so they never have to guess or hardcode.

    Port assignment rules
    ---------------------
    - The externally-exposed service gets port 8080 (or 3000 for frontend).
    - Internal services get sequential ports starting at 8081.

    Topology        | backend | bff  | frontend | primary
    ----------------|---------|------|----------|---------------------------
    backend only    | 8080    |  —   |    —     | backend:8080
    back + bff      | 8081    | 8080 |    —     | bff:8080
    full 3-tier     | 8081    | 8082 | 3000     | frontend:3000→bff:8082→backend:8081
    back + frontend | 8081    |  —   | 3000     | frontend:3000→backend:8081
    """

    enabled_services: List[str]          # e.g. ["backend"] or ["backend", "bff", "frontend"]
    service_ports: Dict[str, int]        # {"backend": 8080} or {"backend": 8081, "bff": 8080, ...}
    primary_service: str                 # externally-exposed service name
    primary_port: int                    # host port clients connect to
    has_bff: bool
    has_frontend: bool
    architecture_diagram: str            # ASCII string built from actual topology

    @classmethod
    def from_config(cls, cfg: "PipelineConfig") -> "TopologyContract":
        services = cfg.enabled_services()
        has_bff = cfg.components.bff
        has_frontend = cfg.components.frontend

        # Assign ports based on topology
        ports: Dict[str, int] = {}
        if "backend" in services:
            # Backend is external (8080) only when it is the sole service
            ports["backend"] = 8080 if (not has_bff and not has_frontend) else 8081
        if "bff" in services:
            ports["bff"] = 8080
        if "frontend" in services:
            ports["frontend"] = 3000
        for svc in services:
            if svc.startswith("mobile_"):
                ports[svc] = 0  # mobile clients connect via URL, no server port

        # Determine primary (externally-reachable) service and host port
        if has_frontend:
            primary, primary_port = "frontend", 3000
        elif has_bff:
            primary, primary_port = "bff", 8080
        else:
            primary, primary_port = "backend", 8080

        diagram = cls._build_diagram(services, ports)

        return cls(
            enabled_services=services,
            service_ports=ports,
            primary_service=primary,
            primary_port=primary_port,
            has_bff=has_bff,
            has_frontend=has_frontend,
            architecture_diagram=diagram,
        )

    @staticmethod
    def _build_diagram(services: List[str], ports: Dict[str, int]) -> str:
        parts = ["Browser"]
        for svc in ["frontend", "bff", "backend"]:
            if svc in services:
                p = ports.get(svc, "?")
                parts.append(f"{svc.upper()} ({p})")
        if "backend" in services:
            parts.append("DB")
        return " → ".join(parts)

    def topology_section(self) -> str:
        """Formatted string ready for injection into any agent prompt."""
        lines = [
            "## Deployment topology (authoritative — use EXACTLY these values)",
            f"Services         : {', '.join(self.enabled_services)}",
            f"Architecture     : {self.architecture_diagram}",
            f"Primary service  : {self.primary_service} (host port {self.primary_port})",
            "",
            "Port assignments (use in EXPOSE, HEALTHCHECK, server.port, docker-compose):",
        ]
        for svc, port in self.service_ports.items():
            if port == 0:
                lines.append(f"  {svc}: N/A (mobile client, no server port)")
                continue
            role = (
                "external — directly accessed by clients"
                if svc == self.primary_service
                else "internal — not directly exposed to host"
            )
            lines.append(f"  {svc}: {port}  [{role}]")
        if self.has_bff and "backend" in self.service_ports and "bff" in self.service_ports:
            lines.append(
                f"\nInter-service URL (use Docker Compose service name, NOT localhost):"
                f"\n  backend base URL as seen by bff: "
                f"http://backend:{self.service_ports['backend']}"
            )
        return "\n".join(lines)
