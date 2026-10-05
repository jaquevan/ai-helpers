---
name: uxd-canvas-export
version: 0.1.0
description: >-
  Export a canvas as a local HTML viewer, canvas.json, or Mermaid. Accepts a
  local canvas or a Miro board. Use when sharing a journey map locally,
  producing a static file, or preparing a canvas for publish. Does not update
  Miro.
---

# Export Canvas

Turn a canvas into a portable local export. The default is a single HTML file with the viewer and local assets inlined. Do not push, deploy, or write to Miro from this skill. Static hosting is `uxd-canvas-publish`. Creating or updating a board is `uxd-canvas-create`.

The viewer source lives next to the export script:

```text
viewer/
├── index.html
├── viewer.css
└── viewer.js
```

`scripts/export-canvas.mjs` inlines those files with the canvas JSON into a single `index.html` when `--viewer html`. Do not copy the separate CSS or JS into the export. A Mermaid node in that file shows its source. It does not load a Mermaid library. `--mermaid` writes `diagram.mmd` for a tool or a Miro board that can render it.

Family: `uxd-canvas-create` → **export** → `uxd-canvas-publish`.

## Requirements

- Node.js 18 or later to build the static viewer.
- Python 3 or another local static server for browser verification of HTML exports.
- The Miro connection, when the input is a board URL. Load the Miro canvas-composer instructions before reading SVG.

## Inputs and output

Accept a canvas directory or a path to `canvas.json`. A canvas directory can also contain `metadata.json` and `assets/`. The export script accepts only that local path.

If the input is a Miro board URL, snapshot it locally before running the script:

1. Read the board, or one frame if it is large, into the JSON Canvas working model. The board stays canonical.
2. Write a snapshot `canvas.json` only as input to the exporter. Keep it when the user wants a snapshot; otherwise use a temporary directory. Preserve `miroId` and metadata `source`.
3. Do not describe that snapshot as the source of truth, and do not write widgets back.

Default output is `.artifacts/{ID}/export/` when the source lives in `canvas/`; otherwise `<canvas-dir>/export/`.

```text
export/
├── index.html             # viewer + canvas data + inlined assets
└── export-manifest.json
```

Optional files, depending on flags:

```text
export/
├── index.html
├── canvas.json
├── diagram.mmd
├── assets/
└── export-manifest.json
```

## Flags

$ARGUMENTS

Parse as: `<canvas-path> [--output <dir>] [--viewer html|none] [--json|--no-json] [--assets inline|folder] [--chrome viewer|none] [--mermaid] [--title <text>]`.

| Flag | Default | Meaning |
|---|---|---|
| `--output` | sibling `export/` when source is `canvas/`; else `<canvas-dir>/export/` | Export destination |
| `--viewer html\|none` | `html` | Include or omit the interactive HTML viewer |
| `--json` / `--no-json` | `--no-json` with HTML; `--json` with `--viewer none` | Write a sidecar `canvas.json` |
| `--assets inline\|folder` | `inline` with HTML; `folder` with `--viewer none` | Embed local files as data URIs, or copy `assets/` |
| `--chrome viewer\|none` | `viewer` | Include or omit the top toolbar and status pill (HTML only) |
| `--mermaid` | off | Write `diagram.mmd` from Mermaid nodes or a simple flow |
| `--title` | `metadata.json` title or folder name | Viewer title |

`--no-viewer` is an alias for `--viewer none`. An export with no viewer, no JSON, and no Mermaid is an error.

`--chrome viewer` includes theme, grid, mouse/trackpad, zoom in, zoom out, reset-view controls, node/edge status, pan, wheel/pinch zoom, touch gestures, and keyboard zoom shortcuts. `--chrome none` hides the toolbar and status pill but retains pan, zoom, touch, link, and scroll interactions.

Do not pass `--mermaid` for a journey map, service blueprint, or affinity map. Mermaid drops lanes, phases, and evidence. The script skips that conversion and warns. Use `--mermaid` for a canvas that already has `subtype: "mermaid"` nodes, or for a simple node-and-edge flow.

## Build

1. Confirm the input. For a local canvas, `canvas.json` must exist and every referenced local asset must be available. For a Miro URL, follow the read steps above first.
2. Review canvas text, URLs, issue records, reactions, and images for confidential or personal data before suggesting publish.
3. Export. Default is a shareable HTML file:

```bash
node "${CLAUDE_SKILL_DIR}/scripts/export-canvas.mjs" \
  <canvas-path> \
  --output <export-dir>
```

Examples:

```bash
# HTML viewer plus a portable canvas.json, assets copied beside them
node "${CLAUDE_SKILL_DIR}/scripts/export-canvas.mjs" <canvas-path> --json --assets folder

# JSON Canvas only, for other JSON Canvas tools
node "${CLAUDE_SKILL_DIR}/scripts/export-canvas.mjs" <canvas-path> --no-viewer

# Mermaid source for a flowchart already stored on the canvas
node "${CLAUDE_SKILL_DIR}/scripts/export-canvas.mjs" <canvas-path> --mermaid
```

4. If the export includes HTML, serve it locally and inspect the initial fit, node content, edges, assets, links, theme choices, pan, and zoom. A simple server is enough: `python3 -m http.server --directory <export-dir> 8000`. For `--viewer none`, confirm `canvas.json`, `diagram.mmd`, and any `assets/` instead. A Mermaid node should show its source text.
5. Report the local output, including viewer, json, mermaid, and assets mode. Suggest `uxd-canvas-publish` only when the user wants a static host. Suggest `uxd-canvas-create` when they want to change the Miro board.

## Completion check

- HTML exports open through a local HTTP server with no application-server dependency.
- Viewer chrome matches `--chrome` when HTML is included; interactions remain available in both chrome modes.
- `--assets inline` produces no `assets/` folder; `--assets folder` copies local files next to the export.
- `--json` writes `canvas.json`; it is omitted by default when HTML is included.
- `--mermaid` writes `diagram.mmd`, or reports that a journey map, blueprint, or affinity map was skipped.
- Mermaid nodes in the HTML viewer show their source. The export does not load a Mermaid library.
- `export-manifest.json` records title, viewer, json, assets, chrome, mermaid, and written files, including itself.
- All nodes, edges, labels, styles, and local assets render.
- A Miro input was read only. The board was not written.
- No unintended internal data, credentials, inaccessible URLs, or local absolute paths are included.
- The final response identifies the local path and export mode. Do not deploy.
