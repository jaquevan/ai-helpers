#!/usr/bin/env python3
"""Create evaluator extraction artifacts from host-staged Jira MCP JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jira_context import load_jira_context
from run_evaluator import resolve_base_ref


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PERSONA_CATALOG = SKILL_DIR.parents[1] / "knowledge" / "personas" / "catalog.yaml"
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+)$")
URL = re.compile(r"https?://[^\s)>\]]+")


def markdown_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        match = HEADING.match(line)
        if match:
            current = re.sub(r"[^a-z0-9]+", " ", match.group(1).lower()).strip()
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def list_items(text: str) -> list[str]:
    items: list[str] = []
    for raw in text.splitlines():
        match = LIST_ITEM.match(raw)
        if match:
            item = re.sub(r"^\[[ xX]\]\s*", "", match.group(1)).strip()
            if item:
                items.append(item)
        elif items and raw.startswith(("  ", "\t")) and raw.strip():
            items[-1] += " " + raw.strip()
    return items


def issue_criteria(issue: dict[str, Any], *, allow_definition_of_done: bool) -> list[str]:
    explicit = issue.get("acceptance_criteria")
    if isinstance(explicit, list):
        return [str(item).strip() for item in explicit if str(item).strip()]
    if isinstance(explicit, str) and explicit.strip():
        parsed = list_items(explicit)
        return parsed or [explicit.strip()]

    sections = markdown_sections(str(issue.get("description") or ""))
    accepted = []
    for name, content in sections.items():
        if "acceptance criteria" in name:
            accepted.extend(list_items(content))
    if accepted:
        return accepted
    if allow_definition_of_done:
        for name, content in sections.items():
            if name in {"definition of done", "done"}:
                accepted.extend(list_items(content))
    return accepted


def select_criteria_source(context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    issues = [context["ticket"], *(context.get("related_issues") or [])]
    for issue in issues:
        criteria = issue_criteria(issue, allow_definition_of_done=False)
        if criteria:
            return issue, criteria
    for issue in issues:
        criteria = issue_criteria(issue, allow_definition_of_done=True)
        if criteria:
            return issue, criteria
    raise ValueError("No Acceptance Criteria or Definition of Done items found in staged Jira context")


def _catalog() -> tuple[list[dict[str, Any]], list[str]]:
    personas: list[dict[str, Any]] = []
    defaults = ["data-scientist+junior", "data-scientist+senior"]
    current: dict[str, Any] | None = None
    list_field = None
    for raw in PERSONA_CATALOG.read_text().splitlines():
        stripped = raw.strip()
        if raw.startswith("  - id:"):
            if current:
                personas.append(current)
            current = {"id": stripped.split(":", 1)[1].strip(), "aliases": [], "experience": []}
            list_field = None
        elif current and raw.startswith("    role:"):
            current["role"] = stripped.split(":", 1)[1].strip()
            list_field = None
        elif current and raw.startswith("    aliases:"):
            list_field = "aliases"
        elif current and raw.startswith("    default_experience:"):
            list_field = "experience"
        elif current and raw.startswith("      - ") and list_field:
            current[list_field].append(stripped[2:].strip())
        elif raw.startswith("  pair:"):
            match = re.search(r"\[(.*)]", raw)
            if match:
                defaults = [item.strip() for item in match.group(1).split(",") if item.strip()]
    if current:
        personas.append(current)
    return personas, defaults


def select_personas(text: str, source_key: str) -> dict[str, Any]:
    personas, defaults = _catalog()
    lowered = text.lower()
    for persona in personas:
        terms = [persona["id"].replace("-", " "), persona.get("role", ""), *persona["aliases"]]
        matched = next((term for term in terms if term and term.lower() in lowered), None)
        if not matched:
            continue
        experience = persona["experience"] or ["experienced"]
        preferred = [level for level in ("junior", "senior") if level in experience]
        selected_levels = preferred or experience[:2]
        selected = [f"{persona['id']}+{level}" for level in selected_levels]
        return {
            "method": "automatic",
            "selected": selected,
            "target_audience_text": text,
            "target_audience_source": source_key,
            "reasoning": f"Matched persona catalog term '{matched}' to {persona['id']}",
            "considered_but_rejected": [],
        }
    return {
        "method": "automatic",
        "selected": defaults,
        "target_audience_text": text,
        "target_audience_source": source_key,
        "reasoning": "No audience keywords matched; using catalog defaults",
        "considered_but_rejected": [],
    }


def audience_text(description: str) -> str:
    problem = markdown_sections(description).get("problem statement", description)
    sentence = re.split(r"(?<=[.!?])\s+", problem.strip())[0]
    return sentence or "Audience not explicitly stated"


def task_from_problem(problem: str, objective: str, ac_ids: list[str]) -> dict[str, Any]:
    sentence = re.split(r"(?<=[.!?])\s+", problem.strip())[0]
    action = None
    for pattern in (r"\bcannot easily\s+(.+)", r"\bneed to\s+(.+)", r"\bneeds to\s+(.+)"):
        match = re.search(pattern, sentence, flags=re.IGNORECASE)
        if match:
            action = match.group(1).rstrip(".")
            break
    if not action:
        action = objective.strip().splitlines()[0].rstrip(".") if objective.strip() else "complete the primary workflow"
    return {
        "task": f"Use the prototype to {action[0].lower() + action[1:] if action else action}",
        "source": f"Problem statement: {sentence}" if sentence else "Jira objective",
        "covers_acs": ac_ids,
    }


def git_delta(workspace: Path) -> dict[str, Any]:
    base_ref = resolve_base_ref(workspace)
    changed: list[dict[str, str]] = []
    if base_ref:
        result = subprocess.run(
            ["git", "-C", str(workspace), "diff", "--name-status", base_ref, "--"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                changed.append({"status": parts[0], "file": parts[-1]})
    untracked = subprocess.run(
        ["git", "-C", str(workspace), "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=False,
    )
    known_files = {item["file"] for item in changed}
    for path in untracked.stdout.splitlines():
        if path and not path.startswith(".artifacts/") and path not in known_files:
            changed.append({"status": "A", "file": path})
    changed = [item for item in changed if not item["file"].startswith(".artifacts/")]
    new_files = [item["file"] for item in changed if item["status"].startswith("A")]
    modified_files = [item["file"] for item in changed if item["status"].startswith(("M", "R"))]
    deleted_files = [item["file"] for item in changed if item["status"].startswith("D")]
    files = [item["file"] for item in changed]
    return {
        "base_ref": base_ref,
        "changed_files": files,
        "new_files": new_files,
        "modified_files": modified_files,
        "deleted_files": deleted_files,
        "categories": {
            "styles": [path for path in files if path.endswith((".css", ".scss"))],
            "tests": [path for path in files if "test" in path.lower()],
            "routes_or_navigation": [path for path in files if re.search(r"route|nav", path, re.I)],
            "components": [path for path in files if path.endswith((".tsx", ".jsx", ".html"))],
        },
        "navigation_gap": bool(
            any("page" in path.lower() for path in new_files)
            and not any(re.search(r"route|nav", path, re.I) for path in files)
        ),
    }


def extract_context(
    *, key: str, context_file: Path, workspace: Path, artifacts_dir: Path
) -> dict[str, Any]:
    context = load_jira_context(context_file, key)
    source_issue, criteria = select_criteria_source(context)
    description = str(source_issue.get("description") or "")
    sections = markdown_sections(description)
    ac_list = [
        {
            "criterion_id": f"AC-{index}",
            "source": "jira",
            "source_ticket": source_issue["key"],
            "text": text,
            "references": URL.findall(text),
        }
        for index, text in enumerate(criteria, start=1)
    ]
    ac_ids = [item["criterion_id"] for item in ac_list]
    audience = audience_text(description)
    personas = select_personas(audience, source_issue["key"])
    primary_persona = personas["selected"][0].split("+", 1)[0]
    problem = sections.get("problem statement", "")
    objective = sections.get("objective", "")
    related_rfe = next(
        (item for item in context.get("related_issues", []) if "rfe" in str(item.get("issue_type", "")).lower()),
        None,
    )
    delta = git_delta(workspace)
    extract = {
        "key": key,
        "title": context["ticket"].get("summary") or source_issue.get("summary") or key,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "ac_content_hash": hashlib.md5(description.encode()).hexdigest(),
        "ac_list": ac_list,
        "feature_context": {
            "background": problem or None,
            "problem_statement": problem or None,
            "user_stories": list_items(sections.get("user stories", "")),
            "ui_enhancements": objective or None,
            "source_ticket": source_issue["key"],
        },
        "journey_definitions": [{
            "id": "journey-1",
            "title": source_issue.get("summary") or context["ticket"].get("summary") or key,
            "persona": primary_persona,
            "source": f"Jira acceptance criteria from {source_issue['key']}",
            "ac_ids": ac_ids,
            "expected_path": [],
        }],
        "tasks_to_be_done": [task_from_problem(problem, objective, ac_ids)],
        "phase_a_only_acs": [],
        "breadcrumb": {
            "outcome": None,
            "rfe": {"key": related_rfe["key"], "validated": True} if related_rfe else None,
            "strat": {"key": key, "title": context["ticket"].get("summary"), "validated": True},
            "prototype": {"workspace": str(workspace)},
            "mr": None,
        },
        "persona_selection": personas,
        "rfe_key": related_rfe["key"] if related_rfe else None,
        "decision_context": {"has_decisions": False, "deliberate_descopes": []},
        "raw_parent": context["ticket"].get("parent"),
        "raw_issuelinks": context["ticket"].get("issue_links") or [],
    }
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "extract-state.json").write_text(json.dumps(extract, indent=2) + "\n")
    (artifacts_dir / "mr-delta.json").write_text(json.dumps(delta, indent=2) + "\n")
    return {
        "status": "completed",
        "phase": "eval-extract",
        "model_invoked": False,
        "source_ticket": source_issue["key"],
        "acceptance_criteria": len(ac_list),
        "personas": personas["selected"],
        "changed_files": len(delta["changed_files"]),
        "outputs": [
            str(artifacts_dir / "extract-state.json"),
            str(artifacts_dir / "mr-delta.json"),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", required=True)
    parser.add_argument("--jira-context", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    args = parser.parse_args()
    try:
        result = extract_context(
            key=args.key,
            context_file=Path(args.jira_context).resolve(),
            workspace=Path(args.workspace).resolve(),
            artifacts_dir=Path(args.artifacts_dir).resolve(),
        )
    except (OSError, ValueError) as error:
        result = {"status": "failed", "error": str(error), "model_invoked": False}
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
