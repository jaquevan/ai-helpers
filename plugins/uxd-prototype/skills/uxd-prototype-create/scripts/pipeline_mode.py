#!/usr/bin/env python3
"""Local serve and observability bridge for prototype creation.

This command handles deterministic create/serve checks and zero-spend estimates.
Paid create-* phases run through creator-phase-runner.py, which shares only the
OpenAI cost-authority contract with the evaluator and keeps a creator-only cap.
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import re
import socketserver
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from functools import partial
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
LOGIN_PATTERN = re.compile(r"\b(?:sign[ -]?in|log[ -]?in|authenticate)\b", re.IGNORECASE)
BUILD_OUTPUTS = ("dist", "build", "out", "public")
DETERMINISTIC_PHASES = frozenset({
    "create-intake", "create-workspace", "create-verify", "create-serve",
    "create-export", "create-report",
})
CREATOR_OPENAI_CAP_USD = 15.0
CREATOR_LEDGER_FILENAME = "openai-budget-ledger-creator.json"
CREATOR_ROUTING_PATH = SCRIPT_PATH.parent.parent / "config" / "model-routing.json"
EVALUATOR_SCRIPTS_DIR = (
    SCRIPT_PATH.parents[4]
    / "uxd-prototype"
    / "skills"
    / "uxd-prototype-evaluate"
    / "scripts"
)
if str(EVALUATOR_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(EVALUATOR_SCRIPTS_DIR))
EVALUATOR_TRACE_PATH = EVALUATOR_SCRIPTS_DIR / "langfuse_trace.py"
EVALUATOR_VERIFY_PATH = EVALUATOR_SCRIPTS_DIR / "verify-langfuse.py"


def load_creator_routing() -> dict[str, Any]:
    try:
        routing = json.loads(CREATOR_ROUTING_PATH.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Creator model routing is unavailable: {CREATOR_ROUTING_PATH}") from error
    if routing.get("provider") != "openai" or not isinstance(routing.get("phases"), dict):
        raise RuntimeError("Creator routing must configure OpenAI phases")
    if float(routing.get("cap_usd", 0)) != CREATOR_OPENAI_CAP_USD:
        raise RuntimeError("Creator routing cap does not match the creator ledger cap")
    return routing


CREATOR_OPENAI_PHASE_BOUNDS: dict[str, tuple[int, int]] = {
    name: (int(spec["input_tokens_bound"]), int(spec["output_tokens_bound"]))
    for name, spec in load_creator_routing()["phases"].items()
}
def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_key(value: str) -> str:
    if not KEY_PATTERN.fullmatch(value):
        raise ValueError("--key must contain only letters, numbers, dots, underscores, or hyphens")
    return value


def digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def validated_url(value: str | None, flag: str) -> str | None:
    if not value:
        return None
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{flag} must be an http(s) URL")
    return value


def verify_workspace_identity(workspace: Path, gitlab_url: str | None, source_revision: str | None) -> None:
    """Confirm an optional real-case checkout matches its declared repo and revision."""
    if not gitlab_url and not source_revision:
        return
    if not (workspace / ".git").exists():
        raise RuntimeError("real-case workspace must be a Git checkout")
    if gitlab_url:
        remote = subprocess.run(
            ["git", "-C", str(workspace), "remote", "get-url", "origin"],
            capture_output=True, text=True, check=False,
        )
        if remote.returncode or remote.stdout.strip().rstrip("/") != gitlab_url.rstrip("/"):
            raise RuntimeError("workspace origin does not match --gitlab-url")
    if source_revision:
        revision = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False,
        )
        if revision.returncode or revision.stdout.strip() != source_revision:
            raise RuntimeError("workspace revision does not match --source-revision")


def artifact_dir_for(args: argparse.Namespace) -> Path:
    root = Path(args.artifacts_dir).expanduser() if args.artifacts_dir else Path(".artifacts") / args.key
    return root.resolve()


def benchmark_dir_for(args: argparse.Namespace, artifacts_dir: Path) -> Path:
    return (Path(args.benchmark_dir).expanduser() if args.benchmark_dir else artifacts_dir / "benchmark").resolve()


def creator_trace_context_path(benchmark_dir: Path, run_id: str) -> Path:
    """Keep one private parent-span file per creator run identity."""
    suffix = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
    return Path(benchmark_dir) / f"langfuse-trace-context-{suffix}.json"


def creator_cost_authority(benchmark_dir: Path, *, phase_bounds: dict[str, tuple[int, int]] | None = None):
    """Create the creator-only $15 authority using the evaluator's shared contract."""
    spec = importlib.util.spec_from_file_location("creator_shared_cost_authority", EVALUATOR_TRACE_PATH)
    if not spec or not spec.loader:
        raise RuntimeError("shared OpenAI cost authority could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.OpenAICostAuthority(
        cap_usd=CREATOR_OPENAI_CAP_USD,
        ledger_path=benchmark_dir / CREATOR_LEDGER_FILENAME,
        phase_bounds=CREATOR_OPENAI_PHASE_BOUNDS if phase_bounds is None else phase_bounds,
        reservation_namespace="create",
    )


def evaluator_verifier():
    """Load the evaluator's dotenv and read-only Langfuse preflight helpers."""
    spec = importlib.util.spec_from_file_location("creator_langfuse_verifier", EVALUATOR_VERIFY_PATH)
    if not spec or not spec.loader:
        raise RuntimeError("shared Langfuse verifier could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def force_creator_langfuse_env(env_file: Path) -> None:
    """Make .env.creator authoritative when evaluator keys are already exported."""
    try:
        lines = env_file.read_text().splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        if not separator or not name.strip().replace("_", "").isalnum():
            continue
        name = name.strip()
        if name not in {"LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"}:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[name] = value


def export_create_serve_trace(
    args: argparse.Namespace,
    artifacts_dir: Path,
    program_run_id: str,
) -> dict[str, Any] | None:
    """Export the run's latest deterministic phase states under one creator trace."""
    if not args.env_file:
        return None
    verifier = evaluator_verifier()
    env_path = verifier.load_env_file(Path(args.env_file))
    if env_path is None:
        raise RuntimeError(f"Langfuse environment file does not exist: {args.env_file}")
    force_creator_langfuse_env(env_path)
    required = ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"missing required environment variables: {', '.join(missing)}")
    host = os.environ["LANGFUSE_HOST"]
    verifier.check_health(host)
    verifier.check_auth(host, os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])

    allowed_event_fields = {
        "at", "component", "phase", "privacy_mode", "model_invoked",
        "llm_cost_usd", "status", "server_type", "http_status",
        "journey_http_status", "jira_url", "gitlab_url", "prototype_url",
        "source_revision",
    }
    events_by_phase: dict[str, dict[str, Any]] = {}
    for line in (artifacts_dir / "creator-phase-events.jsonl").read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            event.get("program_run_id") != program_run_id
            or event.get("phase") not in DETERMINISTIC_PHASES
        ):
            continue
        exported_event = {key: value for key, value in event.items() if key in allowed_event_fields}
        # Keep one current result per deterministic phase. Earlier retry
        # records remain in the local journal and the manifest hash.
        events_by_phase[event["phase"]] = exported_event
    events = list(events_by_phase.values())
    completed = events_by_phase.get("create-serve", {})
    sanitized_output = {
        "status": completed.get("status", "unknown"),
        "phase": "create-serve",
        "server_type": completed.get("server_type"),
        "http_status": completed.get("http_status"),
        "journey_http_status": completed.get("journey_http_status"),
        "model_invoked": False,
        "llm_cost_usd": 0,
    }
    trace_payload = {
        "component": "creator",
        "pipeline": "prototype-creator",
        "prototype_key": args.key,
        "jira_url": args.jira_url,
        "source_revision": args.source_revision,
        "eval_run_id": program_run_id,
        "program_run_id": program_run_id,
        "provider": "local",
        "invocation": "creator-deterministic-phase",
        "privacy_mode": "metadata_only",
        "trace_content": "metadata",
        "trace_context_path": str(creator_trace_context_path(
            benchmark_dir_for(args, artifacts_dir), program_run_id
        )),
        "benchmark": {"benchmark_name": args.benchmark_name},
    }
    trace = verifier.langfuse_trace.LivePipelineTrace(trace_payload)
    with trace:
        if not trace.client:
            raise RuntimeError("Langfuse client unavailable for the metadata-only creator trace")
        trace_phases = []
        for event in events:
            phase_input = {
                key: event[key]
                for key in (
                    "phase", "status", "server_type", "http_status",
                    "journey_http_status", "gitlab_url", "prototype_url",
                    "jira_url", "source_revision",
                )
                if event.get(key) is not None
            }
            phase_input.update({"model_invoked": False, "llm_cost_usd": 0})
            observation = trace.start_phase(
                name=phase_input["phase"], model=None, provider="local",
                input_text=json.dumps(phase_input, sort_keys=True),
            )
            trace_phase = {
                **phase_input,
                "provider": "local",
                "known_usage_cost_usd": 0,
                "usage_known": True,
                "usage_unknown": False,
                "validation": f"deterministic phase recorded with status {phase_input['status']}",
                "duration_ms": 0,
            }
            trace.finish_phase(
                observation,
                phase=trace_phase,
                output_text=json.dumps(phase_input, sort_keys=True),
            )
            trace_phases.append(trace_phase)
        result = trace.finish({
            **trace_payload,
            "run_result": {
                "status": "completed",
                "exit_code": 0,
                "cost_usd": 0,
                "billing_source": "local_no_model_cost",
                "usage_known": True,
                "usage_unknown": False,
                "duration_s": 0,
                "token_usage": {"input_tokens": 0, "output_tokens": 0},
            },
            "phases": trace_phases,
        })
    if not result.get("logged"):
        raise RuntimeError("Langfuse did not confirm the metadata-only creator trace")
    return result


def creator_estimate_only(args: argparse.Namespace, artifacts_dir: Path) -> dict[str, Any]:
    """Estimate all configured creator phases without calling a model."""
    benchmark_dir = benchmark_dir_for(args, artifacts_dir)
    authority = creator_cost_authority(benchmark_dir)
    authority.initialize()
    routing = load_creator_routing()
    phases = []
    for name, spec in routing["phases"].items():
        cost = authority.estimate(name, spec["model"])
        phases.append({
            "phase": name,
            "provider": routing["provider"],
            "model": spec["model"],
            "input_tokens_bound": int(spec["input_tokens_bound"]),
            "output_tokens_bound": int(spec["output_tokens_bound"]),
            "reserved_estimate_usd": cost,
        })
    estimated_total = round(sum(phase["reserved_estimate_usd"] for phase in phases), 8)
    active_reserved = round(sum(authority.active_reservations.values()), 8)
    completed = round(authority.completed_usd, 8)
    remaining = round(
        authority.cap_usd - completed - active_reserved - estimated_total, 8
    )
    return {
        "status": "ready" if remaining >= 0 else "blocked",
        "component": "creator",
        "model_invoked": False,
        "privacy_mode": "metadata_only",
        "approval_required": True,
        "cap_usd": authority.cap_usd,
        "ledger_path": str(authority.ledger_path),
        "model_defaults": {
            "skill": routing["default_model"],
            "judge": routing["judge_model"],
        },
        "estimated_openai_cost_usd": estimated_total,
        "completed_openai_usd": completed,
        "active_reserved_openai_usd": active_reserved,
        "remaining_cap_after_estimate_usd": remaining,
        "paid_phases": phases,
        "detail": "Estimate uses configured per-phase token ceilings and the pinned OpenAI price card; it is not an invoice.",
    }


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def metadata_title(artifacts_dir: Path) -> str | None:
    title = read_json(artifacts_dir / "metadata.json").get("title")
    return title.strip() if isinstance(title, str) and title.strip() else None


def append_event(artifacts_dir: Path, *, phase: str, status: str, program_run_id: str,
                 key: str, details: dict[str, Any] | None = None) -> None:
    """Append an allowlisted metadata-only event; never store page/source text."""
    event = {
        "at": now(),
        "root_trace": f"create/{key}",
        "program_run_id": program_run_id,
        "component": "creator",
        "phase": phase,
        "prototype_key": key,
        "invocation": "local",
        "privacy_mode": "metadata_only",
        "model_invoked": False,
        "llm_cost_usd": 0,
        "status": status,
    }
    if details:
        event.update(details)
    with (artifacts_dir / "creator-phase-events.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps(event, sort_keys=True) + "\n")


def write_observability_config(artifacts_dir: Path, payload: dict[str, Any]) -> None:
    """Preserve the existing pipeline block and own only the trailing observability block."""
    path = artifacts_dir / "pipeline-config.yaml"
    previous = path.read_text() if path.is_file() else ""
    previous = re.sub(r"\n?observability:\n[\s\S]*\Z", "", previous).rstrip()

    def quoted(value: Any) -> str:
        return json.dumps(str(value))

    lines = [previous, "", "observability:"] if previous else ["observability:"]
    lines.extend([
        "  schema_version: 1",
        f"  program_run_id: {quoted(payload['program_run_id'])}",
        "  component: creator",
        f"  root_trace: {quoted(payload['root_trace'])}",
        "  privacy_mode: metadata_only",
        "  model_invoked: false",
        "  phases:",
        "    - name: create-serve",
        f"      status: {payload['status']}",
        "      llm_cost_usd: 0",
        "  server:",
        f"    status: {payload['status']}",
        f"    type: {quoted(payload.get('server_type', 'unavailable'))}",
        f"    url: {quoted(payload.get('url', ''))}",
        f"    pid: {int(payload.get('pid') or 0)}",
        f"    log_path: {quoted(payload['log_path'])}",
        "  evaluator:",
        "    preflight: pending",
        "    estimate: pending",
        "    approval_required: true",
        "    model_invoked: false",
    ])
    if payload.get("jira_url") or payload.get("gitlab_url") or payload.get("source_revision"):
        lines.extend([
            "  source:",
            f"    jira_url: {quoted(payload.get('jira_url', ''))}",
            f"    gitlab_url: {quoted(payload.get('gitlab_url', ''))}",
            f"    prototype_url: {quoted(payload.get('prototype_url', payload.get('url', '')))}",
            f"    source_revision: {quoted(payload.get('source_revision', ''))}",
        ])
    path.write_text("\n".join(lines) + "\n")


def choose_package_manager(workspace: Path) -> list[str]:
    if (workspace / "pnpm-lock.yaml").is_file():
        return ["pnpm"]
    if (workspace / "yarn.lock").is_file():
        return ["yarn"]
    return ["npm"]


def build_workspace(workspace: Path, log_path: Path) -> Path:
    package_path = workspace / "package.json"
    package = read_json(package_path)
    if not package_path.is_file() or not isinstance(package.get("scripts"), dict):
        raise ValueError("workspace mode requires package.json with a build script")
    if not isinstance(package["scripts"].get("build"), str):
        raise ValueError("workspace package.json has no build script")
    manager = choose_package_manager(workspace)
    install = manager + (["ci"] if manager == ["npm"] and (workspace / "package-lock.json").is_file() else ["install"])
    build = manager + (["run", "build"] if manager != ["yarn"] else ["build"])
    with log_path.open("a", encoding="utf-8") as log:
        for command in (install, build):
            log.write("$ " + " ".join(command) + "\n")
            completed = subprocess.run(command, cwd=workspace, stdout=log, stderr=subprocess.STDOUT, check=False)
            if completed.returncode:
                raise RuntimeError("workspace dependency install or build failed; see server.log")
    for name in BUILD_OUTPUTS:
        candidate = workspace / name
        if (candidate / "index.html").is_file():
            return candidate
    raise RuntimeError("workspace build did not produce index.html in dist, build, out, or public")


def serve_directory(args: argparse.Namespace) -> None:
    directory = Path(args.serve_child).resolve()
    ready_path = Path(args.ready_file).resolve()
    handler = partial(PrototypeHandler, directory=str(directory))
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as server:
        ready_path.write_text(json.dumps({"pid": os.getpid(), "port": server.server_address[1]}) + "\n")
        server.serve_forever()


class PrototypeHandler(http.server.SimpleHTTPRequestHandler):
    """Static handler with an index fallback so SPA journey routes are probeable."""

    def send_head(self):  # type: ignore[no-untyped-def]
        path = self.translate_path(self.path)
        if not os.path.exists(path):
            self.path = "/index.html"
        return super().send_head()

    def log_message(self, _format: str, *_args: object) -> None:
        # Request logs contain paths that need not become part of a trace artifact.
        return


def start_server(serve_dir: Path, artifacts_dir: Path, port: int) -> tuple[int, str]:
    ready = artifacts_dir / "server-ready.json"
    ready.unlink(missing_ok=True)
    log_path = artifacts_dir / "server.log"
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT_PATH), "--serve-child", str(serve_dir), "--ready-file", str(ready), "--port", str(port)],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    for _ in range(50):
        if ready.is_file():
            data = read_json(ready)
            ready.unlink(missing_ok=True)
            actual_port = data.get("port")
            if isinstance(actual_port, int):
                return process.pid, f"http://127.0.0.1:{actual_port}"
        if process.poll() is not None:
            break
        time.sleep(0.1)
    raise RuntimeError("local server exited before it reported readiness; see server.log")


def fetch(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read(1_000_000).decode("utf-8", errors="replace")
            return response.status, body
    except urllib.error.URLError as error:
        raise RuntimeError("local server is unreachable") from error


def verify_identity(url: str, expected_text: str | None, journey_route: str) -> dict[str, int]:
    status, body = fetch(url)
    if status != 200:
        raise RuntimeError("prototype root did not return HTTP 200")
    title = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    heading = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.IGNORECASE | re.DOTALL)
    identity_text = " ".join(value for value in (title.group(1) if title else "", heading.group(1) if heading else ""))
    if LOGIN_PATTERN.search(identity_text):
        raise RuntimeError("prototype identity resembles an authentication or login page")
    if expected_text and expected_text not in body:
        raise RuntimeError("prototype identity text was not found in the rendered page")
    if not journey_route.startswith("/"):
        raise ValueError("--journey-route must start with /")
    route_status, _ = fetch(url.rstrip("/") + journey_route)
    if route_status != 200:
        raise RuntimeError("configured journey route did not return HTTP 200")
    return {"root_status": status, "journey_status": route_status}


def stop_server(artifacts_dir: Path) -> int:
    config = (artifacts_dir / "pipeline-config.yaml").read_text() if (artifacts_dir / "pipeline-config.yaml").is_file() else ""
    match = re.search(r"^    pid: (\d+)$", config, re.MULTILINE)
    if not match or int(match.group(1)) <= 0:
        return 0
    pid = int(match.group(1))
    try:
        os.kill(pid, 15)
    except ProcessLookupError:
        return 0
    return pid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve and verify a create artifact with metadata-only phase events")
    parser.add_argument("--key", required=False)
    parser.add_argument("--artifacts-dir")
    parser.add_argument("--workspace", default="standalone")
    parser.add_argument("--prototype-url", help="verify an already-running prototype instead of starting a server")
    parser.add_argument("--jira-url", help="Jira issue URL recorded as real-case trace metadata")
    parser.add_argument("--gitlab-url", help="GitLab repository URL recorded and checked against workspace origin")
    parser.add_argument("--source-revision", help="full Git revision required for a real-case workspace")
    parser.add_argument("--expected-text")
    parser.add_argument("--journey-route", default="/")
    parser.add_argument("--port", type=int, default=0, help="localhost port; 0 allocates one atomically")
    parser.add_argument("--program-run-id")
    parser.add_argument("--benchmark-dir", help="creator-only benchmark ledger directory")
    parser.add_argument("--env-file", help="gitignored Langfuse dotenv file for metadata-only export")
    parser.add_argument("--benchmark-name", default="creator-create-serve")
    parser.add_argument("--estimate-only", action="store_true",
                        help="report the creator $15 authority without a model call")
    parser.add_argument("--record-phase", choices=sorted(DETERMINISTIC_PHASES),
                        help="append a metadata-only completed deterministic phase event")
    parser.add_argument("--phase-status", choices=("completed", "failed", "skipped"), default="completed")
    parser.add_argument("--stop", action="store_true", help="stop the server recorded in pipeline-config.yaml")
    parser.add_argument("--serve-child", help=argparse.SUPPRESS)
    parser.add_argument("--ready-file", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.serve_child:
        if not args.ready_file:
            raise SystemExit("--ready-file is required with --serve-child")
        serve_directory(args)
        return 0
    if not args.key:
        raise SystemExit("--key is required")
    started_pid = 0
    try:
        safe_key(args.key)
        artifacts_dir = artifact_dir_for(args)
        if args.stop:
            pid = stop_server(artifacts_dir)
            print(json.dumps({"status": "stopped", "pid": pid, "model_invoked": False}))
            return 0
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        if args.estimate_only:
            estimate = creator_estimate_only(args, artifacts_dir)
            (artifacts_dir / "creator-cost-estimate.json").write_text(json.dumps(estimate, indent=2) + "\n")
            print(json.dumps(estimate))
            return 0 if estimate["status"] == "ready" else 2
        program_run_id = args.program_run_id or f"program-{args.key}-{uuid.uuid4().hex[:12]}"
        if args.record_phase:
            record_jira_url = validated_url(args.jira_url, "--jira-url")
            details = {"jira_url": record_jira_url} if record_jira_url else {}
            if args.source_revision:
                details["source_revision"] = args.source_revision
            append_event(artifacts_dir, phase=args.record_phase, status=args.phase_status,
                         program_run_id=program_run_id, key=args.key,
                         details=details or None)
            print(json.dumps({"status": args.phase_status, "phase": args.record_phase,
                              "program_run_id": program_run_id, "model_invoked": False,
                              "privacy_mode": "metadata_only"}))
            return 0
        log_path = artifacts_dir / "server.log"
        args.prototype_url = validated_url(args.prototype_url, "--prototype-url")
        args.jira_url = validated_url(args.jira_url, "--jira-url")
        args.gitlab_url = validated_url(args.gitlab_url, "--gitlab-url")
        append_event(artifacts_dir, phase="create-serve", status="started", program_run_id=program_run_id, key=args.key)
        if args.prototype_url:
            if args.workspace == "standalone":
                raise ValueError("--prototype-url real-case tracing requires --workspace")
            workspace = Path(args.workspace).expanduser().resolve()
            if not workspace.is_dir():
                raise RuntimeError("workspace path does not exist")
            verify_workspace_identity(workspace, args.gitlab_url, args.source_revision)
            pid, url = 0, args.prototype_url
            server_type = "existing-prototype"
        elif args.workspace == "standalone":
            serve_dir = artifacts_dir / "prototype"
            server_type = "standalone-static"
            if not (serve_dir / "index.html").is_file():
                raise RuntimeError("standalone mode requires .artifacts/{ID}/prototype/index.html")
        else:
            workspace = Path(args.workspace).expanduser().resolve()
            if not workspace.is_dir():
                raise RuntimeError("workspace path does not exist")
            serve_dir = build_workspace(workspace, log_path)
            server_type = "workspace-build"
        if not args.prototype_url:
            pid, url = start_server(serve_dir, artifacts_dir, args.port)
            started_pid = pid
        expected_text = args.expected_text or metadata_title(artifacts_dir)
        status = verify_identity(url, expected_text, args.journey_route)
        config = {
            "program_run_id": program_run_id, "root_trace": f"create/{args.key}", "status": "completed",
            "server_type": server_type, "url": url, "pid": pid, "log_path": str(log_path),
            "jira_url": args.jira_url, "gitlab_url": args.gitlab_url,
            "prototype_url": url, "source_revision": args.source_revision,
        }
        write_observability_config(artifacts_dir, config)
        append_event(artifacts_dir, phase="create-serve", status="completed", program_run_id=program_run_id,
                     key=args.key, details={"server_type": server_type, "http_status": status["root_status"],
                                            "journey_http_status": status["journey_status"],
                                            "expected_text_sha256": digest(expected_text or ""),
                                            "jira_url": args.jira_url, "gitlab_url": args.gitlab_url,
                                            "prototype_url": url, "source_revision": args.source_revision})
        trace = export_create_serve_trace(args, artifacts_dir, program_run_id)
        print(json.dumps({"status": "completed", "url": url, "pid": pid, "program_run_id": program_run_id,
                          "model_invoked": False, "privacy_mode": "metadata_only",
                          "langfuse": trace}))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        if started_pid:
            try:
                os.kill(started_pid, 15)
            except ProcessLookupError:
                pass
        if args.key:
            artifacts_dir = artifact_dir_for(args)
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            program_run_id = args.program_run_id or f"program-{args.key}-failed"
            append_event(artifacts_dir, phase="create-serve", status="failed", program_run_id=program_run_id,
                         key=args.key, details={"error_category": "serve_or_identity"})
        print(f"Creator pipeline failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
