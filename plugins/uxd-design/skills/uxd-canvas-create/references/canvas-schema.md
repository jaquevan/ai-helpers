# JSON Canvas fields and extensions

Use standard JSON Canvas fields whenever possible. The bundled viewer preserves the standard structure and supports optional presentation fields.

## Root

```json
{
  "nodes": [],
  "edges": []
}
```

Coordinates and dimensions are canvas units. Negative coordinates are valid.

## Nodes

Every node requires a unique string `id`, `type`, numeric `x` and `y`, and positive numeric `width` and `height`.

| Type | Required content | Notes |
|---|---|---|
| `text` | `text` | Markdown. The bundled viewer also supports `subtype: "sticky"` and `subtype: "drawing"`. |
| `file` | `file` | Prefer a relative path under `assets/`. |
| `link` | `url` | Optional `linkMeta` can cache a title, description, image, and site name. |
| `group` | `label` recommended | Visual container; the label occupies 24 units above its inner area. |
| `jira` / `task` | corresponding issue/task data | Optional viewer extensions. Use only when the destination supports these records. |

Common optional fields:

- `color`: JSON Canvas palette ID `"1"`–`"7"`, `"none"`, or a destination-supported color.
- `colorOpacity`: `0`–`100`.
- `fontSize`: `small`, `medium`, `large`, or `xl`.
- `textAlign`: `left`, `center`, or `right`.
- `verticalAlign`: `top`, `middle`, or `bottom`.
- `nodeStyle`: `wireframe` or `placeholder`.
- `reactions`: optional reaction records supported by the bundled viewer.

Sticky note:

```json
{
  "id": "pain-point",
  "type": "text",
  "subtype": "sticky",
  "x": 40,
  "y": 120,
  "width": 220,
  "height": 180,
  "color": "3",
  "text": "Context is spread across tools"
}
```

Drawing nodes use `subtype: "drawing"` and `drawingData.paths[]`; each path has `points` as `[x,y]` pairs plus optional `color` and `strokeWidth`.

Mermaid diagram:

```json
{
  "id": "checkout-flow",
  "type": "text",
  "subtype": "mermaid",
  "x": 40,
  "y": 40,
  "width": 480,
  "height": 320,
  "text": "flowchart LR\n  discover[Discover] --> decide[Decide]"
}
```

`text` is the Mermaid source. Use this for a flowchart, sequence diagram, ERD, or class diagram stored in a local canvas. The bundled viewer shows that source and does not render it. Do not use it for a journey map, service blueprint, or affinity map.

Optional `miroId` on a node or edge is the Miro widget id from a board read or write. Preserve it on snapshots so the next board update patches the same widget. Omit it on a local-only canvas.

## Edges

Every edge requires a unique string `id`, `fromNode`, and `toNode`. Both node IDs must exist.

Optional fields:

- `fromSide` / `toSide`: `top`, `right`, `bottom`, or `left`.
- `label`: short relationship label.
- `color`: palette ID.
- `lineStyle`: `solid`, `dashed`, or `dotted`.
- `fromEnd` / `toEnd`: `none`, `arrow`, `diamond`, or `circle`.

```json
{
  "id": "edge-discover-define",
  "fromNode": "phase-discover",
  "fromSide": "right",
  "toNode": "phase-define",
  "toSide": "left",
  "toEnd": "arrow",
  "label": "informs"
}
```

## Palette and defaults

The bundled viewer maps palette IDs as follows: red `1`, orange `2`, yellow `3`, green `4`, cyan `5`, purple `6`, white `7`. Default node size is `250×120`; sticky notes default to `200×200`; the grid is 20 units.
