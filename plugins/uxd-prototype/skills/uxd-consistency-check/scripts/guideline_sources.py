#!/usr/bin/env python3
"""Resolve workspace guidelines plus explicit local/URL supplements."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request


GUIDELINE_PATH = Path(".design/product/design-guidelines")
MAX_URL_BYTES = 2_000_000


def parse_metadata(text: str) -> dict:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    result = {}
    if match:
        for line in match[1].splitlines():
            key, separator, value = line.partition(":")
            if separator:
                value = value.strip().strip("\"'")
                result[key.strip()] = {"true": True, "false": False}.get(value, value)
    return result


def _url_text(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Guideline URLs must be HTTP(S) URLs without embedded credentials")
    request = urllib.request.Request(url, headers={"Accept": "text/markdown, text/plain"})
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.headers.get_content_type() == "text/html":
            raise ValueError("Use a raw Markdown URL, not a repository tree/login/web page; stage authenticated documents locally")
        content = response.read(MAX_URL_BYTES + 1)
    if len(content) > MAX_URL_BYTES:
        raise ValueError("Guideline URL exceeds the 2 MB document limit")
    text = content.decode("utf-8-sig")
    if re.search(r"<html\b|<!doctype\s+html", text[:1000], re.I):
        raise ValueError("Guideline URL returned HTML; provide raw Markdown or a locally staged document")
    return text


def load_guidelines(workspace: str | Path, provided: list[str] | None = None) -> dict:
    workspace = Path(workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"Workspace directory does not exist: {workspace}")
    default = workspace / GUIDELINE_PATH
    requested = [(str(default), "workspace")] if default.is_dir() else []
    requested.extend((value, "explicit") for value in (provided or []))
    documents = {}
    sources = []
    visited = set()
    for value, kind in requested:
        directory_source = False
        parsed = urllib.parse.urlsplit(value)
        remote = parsed.scheme in {"http", "https"}
        if parsed.scheme and not remote and not (len(parsed.scheme) == 1 and value[1:2] == ":"):
            raise ValueError("Use a local path or an HTTP(S) raw Markdown URL")
        if remote:
            location = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            entries = [(None, _url_text(value), Path(parsed.path).stem or "uploaded-guideline")]
        else:
            root = Path(value).expanduser()
            if not root.is_absolute():
                root = workspace / root
            root = root.resolve()
            if root.is_dir() and (root / GUIDELINE_PATH).is_dir():
                root = root / GUIDELINE_PATH
            if not root.exists():
                raise ValueError(f"Guideline path does not exist: {root}")
            location = str(root)
            directory_source = root.is_dir()
            paths = sorted(root.rglob("*.md")) if root.is_dir() else [root]
            entries = [
                (path, path.read_text(encoding="utf-8-sig"), path.stem)
                for path in paths
                if not root.is_dir() or (
                    "tools" not in path.relative_to(root).parts
                    and not path.is_symlink()
                )
            ]
        if location in visited:
            continue
        visited.add(location)
        source = {"kind": kind, "location": location, "remote": remote, "document_ids": []}
        for path, text, fallback_id in entries:
            if not text.strip():
                continue
            metadata = parse_metadata(text)
            if directory_source and path.name.lower() == 'readme.md' and not metadata.get('id') and not re.search(r'(?im)^#{1,6}\s+(?:Rule|Rules|Conventions)\b', text):
                continue
            fallback_id = re.sub(r'[^A-Za-z0-9._-]+', '-', fallback_id).strip('._-') or 'provided-guideline'
            identity = str(metadata.get("id") or fallback_id)
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", identity):
                raise ValueError(f"Invalid guideline ID: {identity}")
            fingerprint = hashlib.sha256(text.strip().encode()).hexdigest()
            if identity in documents:
                if documents[identity]["sha256"] != fingerprint:
                    raise ValueError(f"Conflicting guideline ID {identity!r}; reconcile the workspace and explicit sources before review")
                documents[identity]["sources"].append(location)
            else:
                documents[identity] = {
                    "id": identity, "title": str(metadata.get("title") or identity),
                    "category": str(metadata.get("category") or (path.parent.name if path else "provided")),
                    "metadata": metadata, "text": text,
                    "path": str(path) if path else None, "remote": remote,
                    "sources": [location], "sha256": fingerprint,
                    "original_source_url": metadata.get("source_url", ""),
                }
            source["document_ids"].append(identity)
        if kind == 'explicit' and not source['document_ids']:
            raise ValueError(f'Explicit guideline source contains no usable Markdown: {location}')
        sources.append(source)
    fingerprint = hashlib.sha256(json.dumps(
        sorted((identity, doc["sha256"]) for identity, doc in documents.items())
    ).encode()).hexdigest()
    return {
        "workspace": str(workspace), "sources": sources,
        "documents": list(documents.values()),
        "status": "available" if documents else "not_provided",
        "version": f"sha256:{fingerprint}" if documents else "none",
    }


def public_context(context: dict) -> dict:
    return {
        key: value for key, value in context.items() if key != "documents"
    } | {"documents": [
        {key: value for key, value in doc.items() if key not in {"text", "metadata"}}
        | ({"text": doc["text"]} if doc["remote"] else {})
        for doc in context["documents"]
    ]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--guidelines", action="append", default=[], help="Local file/directory/reference workspace or raw Markdown URL; repeat to supplement")
    args = parser.parse_args()
    try:
        print(json.dumps(public_context(load_guidelines(args.workspace, args.guidelines)), indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "needs_resolution", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
