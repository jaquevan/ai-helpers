(function() {
"use strict";

var CANVAS_TITLE = __CANVAS_TITLE__;
var CANVAS_DATA = __CANVAS_DATA__;
var ASSET_MAP = __ASSET_MAP__;
var THEMES = {
  dark: {
    id: "dark", name: "Dark",
    canvasBg: "#1a1a1a", gridColor: "rgba(255,255,255,0.03)",
    nodeTextColor: "#e0e0e0", nodeBg: "#252525", nodeBorder: "#444",
    edgeColor: "#666", groupBg: "rgba(255,255,255,0.10)",
    groupBgCollapsed: "rgba(255,255,255,0.15)", linkColor: "#4da6ff",
    groupColorFallback: "#555", placeholderText: "#888"
  },
  blueprint: {
    id: "blueprint", name: "Blueprint",
    canvasBg: "#0a2e5c", gridColor: "rgba(100,180,255,0.12)",
    nodeTextColor: "#c8ddf5", nodeBg: "rgba(15,50,100,0.85)",
    nodeBorder: "rgba(100,180,255,0.35)", edgeColor: "rgba(100,180,255,0.5)",
    groupBg: "rgba(100,180,255,0.10)", groupBgCollapsed: "rgba(100,180,255,0.16)",
    linkColor: "#7bb8f5", groupColorFallback: "rgba(100,180,255,0.4)",
    placeholderText: "rgba(150,190,230,0.5)"
  },
  light: {
    id: "light", name: "Light",
    canvasBg: "#f5f5f5", gridColor: "rgba(0,0,0,0.06)",
    nodeTextColor: "#1a1a1a", nodeBg: "#ffffff", nodeBorder: "#d0d0d0",
    edgeColor: "#999", groupBg: "rgba(0,0,0,0.06)",
    groupBgCollapsed: "rgba(0,0,0,0.10)", linkColor: "#0066cc",
    groupColorFallback: "#aaa", placeholderText: "#999"
  },
  draft: {
    id: "draft", name: "Draft",
    canvasBg: "#f0e8d8", gridColor: "rgba(160,140,100,0.12)",
    nodeTextColor: "#3a3225", nodeBg: "rgba(245,238,222,0.9)",
    nodeBorder: "rgba(160,140,100,0.4)", edgeColor: "rgba(120,105,75,0.6)",
    groupBg: "rgba(160,140,100,0.09)", groupBgCollapsed: "rgba(160,140,100,0.14)",
    linkColor: "#6b5c45", groupColorFallback: "rgba(160,140,100,0.5)",
    placeholderText: "rgba(120,105,75,0.5)"
  },
  graph: {
    id: "graph", name: "Graph Paper",
    canvasBg: "#fafcfa", gridColor: "rgba(80,160,80,0.12)",
    nodeTextColor: "#1a2a1a", nodeBg: "rgba(255,255,255,0.95)",
    nodeBorder: "rgba(80,160,80,0.35)", edgeColor: "rgba(80,160,80,0.5)",
    groupBg: "rgba(80,160,80,0.07)", groupBgCollapsed: "rgba(80,160,80,0.12)",
    linkColor: "#3a7a3a", groupColorFallback: "rgba(80,160,80,0.4)",
    placeholderText: "rgba(80,130,80,0.5)"
  }
};

var GRID_SIZE = 20;

var NODE_COLORS = {
  '1': '#fb464c', '2': '#e9973f', '3': '#e0de71',
  '4': '#44cf6e', '5': '#53dfdd', '6': '#a882ff', '7': '#ffffff'
};

var TASK_TYPE_COLORS = {
  'Epic': '#a882ff', 'Story': '#44cf6e', 'Task': '#2684FF',
  'Bug': '#fb464c', 'Spike': '#e9973f'
};

var FONT_SIZES = { small: '12px', medium: '14px', large: '18px', xl: '24px' };

// State
var currentTheme = 'graph';
var currentGrid = 'lines';
var inputDevice = 'mouse';
var zoom = 1;
var offsetX = 0, offsetY = 0;
var isPanning = false, panStartX = 0, panStartY = 0, panOffsetStartX = 0, panOffsetStartY = 0;

// Elements
var canvasWrap = document.getElementById('canvas-wrap');
var transformLayer = document.getElementById('transform-layer');
var gridLayer = document.getElementById('grid-layer');
var zoomDisplay = document.getElementById('zoom-display');
var statusBar = document.getElementById('status-bar');

// ---- Markdown rendering (minimal) ----
function renderMarkdown(text) {
  if (!text) return '';
  var html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(_, label, url) {
      var href = safeHref(url.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"'));
      if (!href) return label;
      return '<a href="' + escapeHtmlInline(href) + '" target="_blank" rel="noopener">' + label + '</a>';
    })
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
  // Wrap loose lines in <p>
  html = html.split('\n').map(function(line) {
    line = line.trim();
    if (!line) return '';
    if (/^<(h[1-6]|ul|ol|li|p|pre|blockquote|div)/.test(line)) return line;
    return '<p>' + line + '</p>';
  }).join('\n');
  return html;
}

// ---- Asset URL resolution ----
function mappedAsset(value) {
  if (!value) return '';
  if (/^(data:|https?:|blob:)/i.test(value)) return value;
  return 'assets/' + value;
}

function resolveAssetUrl(url) {
  if (!url) return '';
  if (ASSET_MAP[url]) return mappedAsset(ASSET_MAP[url]);
  var match = url.match(/\/assets\/([^?#]+)/);
  if (match && ASSET_MAP[match[1]]) return mappedAsset(ASSET_MAP[match[1]]);
  if (url.startsWith('/api/canvas/')) return 'assets/' + url.split('/assets/').pop();
  return url;
}

function isImageSrc(src) {
  if (!src) return false;
  if (/^data:image\//i.test(src)) return true;
  return /\.(jpg|jpeg|png|gif|webp|svg)(?:$|[?#])/i.test(src);
}

// ---- Hex to RGBA ----
function hexToRgba(hex, opacity) {
  var r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
  return 'rgba(' + r + ',' + g + ',' + b + ',' + (opacity/100) + ')';
}

// ---- Edge path ----
function edgePath(from, to) {
  var dx = to.x - from.x;
  var co = Math.abs(dx) / 2;
  return 'M ' + from.x + ' ' + from.y + ' C ' + (from.x+co) + ' ' + from.y + ', ' + (to.x-co) + ' ' + to.y + ', ' + to.x + ' ' + to.y;
}

function getNodeAttachPoint(node, side) {
  var top = node.type === 'group' ? node.y + 24 : node.y;
  var h = node.type === 'group' ? node.height - 24 : node.height;
  switch(side) {
    case 'top': return { x: node.x + node.width/2, y: top };
    case 'bottom': return { x: node.x + node.width/2, y: top + h };
    case 'left': return { x: node.x, y: top + h/2 };
    case 'right': default: return { x: node.x + node.width, y: top + h/2 };
  }
}

function getEdgeMidpoint(from, to) {
  var dx = to.x - from.x, co = Math.abs(dx)/2;
  var t = 0.5, mt = 0.5;
  var cx1 = from.x+co, cy1 = from.y, cx2 = to.x-co, cy2 = to.y;
  return {
    x: mt*mt*mt*from.x + 3*mt*mt*t*cx1 + 3*mt*t*t*cx2 + t*t*t*to.x,
    y: mt*mt*mt*from.y + 3*mt*mt*t*cy1 + 3*mt*t*t*cy2 + t*t*t*to.y
  };
}

// ---- SVG path from drawing points ----
function finiteNumber(value, fallback) {
  var n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function safeColor(value, fallback) {
  var color = String(value || '').trim();
  if (/^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(color)) return color;
  if (/^rgba?\(\s*(?:[01]?\d?\d|2[0-4]\d|25[0-5])\s*,\s*(?:[01]?\d?\d|2[0-4]\d|25[0-5])\s*,\s*(?:[01]?\d?\d|2[0-4]\d|25[0-5])\s*(?:,\s*(?:0|1|0?\.\d+)\s*)?\)$/.test(color)) return color;
  return fallback;
}

function safeHref(url) {
  var value = String(url || '').trim();
  if (!/^(https?:|mailto:)/i.test(value)) return '';
  if (/[\s"'<>\\]/.test(value)) return '';
  return value;
}

function pointsToPath(points) {
  if (!points || points.length < 2) return '';
  var coords = [];
  for (var i = 0; i < points.length; i++) {
    var pt = points[i];
    if (!pt || pt.length < 2) return '';
    var x = Number(pt[0]);
    var y = Number(pt[1]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return '';
    coords.push([x, y]);
  }
  var d = 'M ' + coords[0][0] + ' ' + coords[0][1];
  if (coords.length === 2) return d + ' L ' + coords[1][0] + ' ' + coords[1][1];
  for (var j = 1; j < coords.length - 1; j++) {
    var mx = (coords[j][0] + coords[j + 1][0]) / 2;
    var my = (coords[j][1] + coords[j + 1][1]) / 2;
    d += ' Q ' + coords[j][0] + ' ' + coords[j][1] + ', ' + mx + ' ' + my;
  }
  var last = coords[coords.length - 1];
  d += ' L ' + last[0] + ' ' + last[1];
  return d;
}

// ---- Render ----
function render() {
  var theme = THEMES[currentTheme] || THEMES.graph;
  var nodes = CANVAS_DATA.nodes || [];
  var edges = CANVAS_DATA.edges || [];
  nodes.forEach(function(node) {
    node.x = finiteNumber(node.x, 0);
    node.y = finiteNumber(node.y, 0);
    node.width = Math.max(0, finiteNumber(node.width, 0));
    node.height = Math.max(0, finiteNumber(node.height, 0));
  });
  var nodeMap = {};
  nodes.forEach(function(n) { nodeMap[n.id] = n; });

  // Update toolbar theme
  canvasWrap.style.background = theme.canvasBg;
  document.getElementById('theme-swatch').style.background = theme.canvasBg;
  document.getElementById('theme-name').textContent = theme.name;

  // Grid
  renderGrid(theme);

  // Build transform layer content
  var html = '';

  // SVG for edges
  html += '<svg style="position:absolute;top:0;left:0;width:10000px;height:10000px;overflow:visible;pointer-events:none;z-index:1">';
  html += '<defs>';
  html += '<marker id="ah" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0,10 3.5,0 7" fill="' + theme.edgeColor + '"/></marker>';
  html += '<marker id="ah-s" markerWidth="10" markerHeight="7" refX="1" refY="3.5" orient="auto"><polygon points="10 0,0 3.5,10 7" fill="' + theme.edgeColor + '"/></marker>';
  html += '<marker id="dm-e" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><polygon points="0 5,5 0,10 5,5 10" fill="' + theme.edgeColor + '"/></marker>';
  html += '<marker id="dm-s" markerWidth="10" markerHeight="10" refX="1" refY="5" orient="auto"><polygon points="0 5,5 0,10 5,5 10" fill="' + theme.edgeColor + '"/></marker>';
  html += '<marker id="cm-e" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><circle cx="4" cy="4" r="3" fill="' + theme.edgeColor + '"/></marker>';
  html += '<marker id="cm-s" markerWidth="8" markerHeight="8" refX="1" refY="4" orient="auto"><circle cx="4" cy="4" r="3" fill="' + theme.edgeColor + '"/></marker>';
  html += '</defs>';

  edges.forEach(function(edge) {
    var fn = nodeMap[edge.fromNode], tn = nodeMap[edge.toNode];
    if (!fn || !tn) return;
    var from = getNodeAttachPoint(fn, edge.fromSide || 'right');
    var to = getNodeAttachPoint(tn, edge.toSide || 'left');
    var color = edge.color ? (NODE_COLORS[edge.color] || theme.edgeColor) : theme.edgeColor;
    var dasharray = edge.lineStyle === 'dashed' ? '8,4' : edge.lineStyle === 'dotted' ? '2,4' : '';
    var markerEnd = '', markerStart = '';
    if (edge.toEnd === 'arrow') markerEnd = 'url(#ah)';
    else if (edge.toEnd === 'diamond') markerEnd = 'url(#dm-e)';
    else if (edge.toEnd === 'circle') markerEnd = 'url(#cm-e)';
    if (edge.fromEnd === 'arrow') markerStart = 'url(#ah-s)';
    else if (edge.fromEnd === 'diamond') markerStart = 'url(#dm-s)';
    else if (edge.fromEnd === 'circle') markerStart = 'url(#cm-s)';
    html += '<path d="' + edgePath(from, to) + '" stroke="' + color + '" stroke-width="2" fill="none"';
    if (dasharray) html += ' stroke-dasharray="' + dasharray + '"';
    if (edge.lineStyle === 'dotted') html += ' stroke-linecap="round"';
    if (markerEnd) html += ' marker-end="' + markerEnd + '"';
    if (markerStart) html += ' marker-start="' + markerStart + '"';
    html += '/>';

    if (edge.label) {
      var mid = getEdgeMidpoint(from, to);
      var tw = edge.label.length * 7 + 24;
      html += '<rect x="' + (mid.x - tw/2) + '" y="' + (mid.y - 11) + '" width="' + tw + '" height="20" rx="10" fill="rgba(255,255,255,0.9)" stroke="rgba(0,0,0,0.1)" stroke-width="0.5"/>';
      html += '<text x="' + mid.x + '" y="' + (mid.y + 3) + '" text-anchor="middle" fill="#555" font-size="11" font-weight="500" font-family="-apple-system,BlinkMacSystemFont,sans-serif" style="pointer-events:none;user-select:none">' + escapeHtmlInline(edge.label) + '</text>';
    }
  });
  html += '</svg>';

  // Nodes (groups first, then non-groups on top)
  var sortedNodes = nodes.slice().sort(function(a, b) {
    if (a.type === 'group' && b.type !== 'group') return -1;
    if (a.type !== 'group' && b.type === 'group') return 1;
    return 0;
  });

  sortedNodes.forEach(function(node) {
    html += renderNode(node, theme);
  });

  transformLayer.innerHTML = html;
  updateTransform();
  updateStatusBar(nodes, edges);
}

function renderNode(node, theme) {
  var isSticky = node.subtype === 'sticky';
  var isDrawing = node.subtype === 'drawing';
  var isMermaid = node.subtype === 'mermaid';
  var isWireframe = node.nodeStyle === 'wireframe';
  var isPlaceholder = node.nodeStyle === 'placeholder';
  var isGroup = node.type === 'group';
  var colorValue = (node.color && node.color !== 'none') ? NODE_COLORS[node.color] : null;
  var isNoColor = node.color === 'none';
  var effectiveOpacity = node.colorOpacity !== undefined ? node.colorOpacity : 100;

  var top = isGroup ? node.y + 24 : node.y;
  var height = isGroup ? node.height - 24 : node.height;

  // Background
  var bg;
  if (isNoColor) bg = 'transparent';
  else if (isDrawing) bg = 'transparent';
  else if (isSticky) {
    var sc = colorValue || '#e0de71';
    bg = 'linear-gradient(to bottom, rgba(255,255,255,0.10) 0%, transparent 45%, rgba(0,0,0,0.04) 100%), ' + hexToRgba(sc, effectiveOpacity);
  } else if (isGroup) {
    bg = colorValue ? hexToRgba(colorValue, effectiveOpacity) : (theme.groupBg || 'rgba(255,255,255,0.10)');
  } else {
    bg = colorValue ? hexToRgba(colorValue, effectiveOpacity) : (theme.nodeBg || '#252525');
  }

  // Border
  var borderColor = isSticky ? (isNoColor ? (theme.nodeBorder || '#444') : 'transparent') : (colorValue || (theme.nodeBorder || '#444'));
  var border = isDrawing ? 'none' : isPlaceholder ? '2px dashed #c8d4e0' : isWireframe ? '2px solid #555' : '2px solid ' + borderColor;
  var borderLeft = node.type === 'jira' ? '4px solid #2684FF' : node.type === 'task' ? '4px solid ' + (TASK_TYPE_COLORS[node.taskData && node.taskData.issueType] || '#2684FF') : border;

  var borderRadius = isPlaceholder ? (isGroup ? '0 16px 16px 16px' : '16px') : isWireframe ? '2px' : isSticky ? '6px' : (isGroup ? '0 8px 8px 8px' : '8px');
  var shadow = isSticky ? '1px 10px 20px -5px rgba(0,0,0,0.25), 0 4px 8px -2px rgba(0,0,0,0.12)' : isWireframe ? '1px 2px 0px rgba(0,0,0,0.15)' : 'none';
  var textColor = isSticky ? '#1a1a1a' : (theme.nodeTextColor || '#e0e0e0');

  var fontSize = '14px';
  if (node.fontSize && FONT_SIZES[node.fontSize]) fontSize = FONT_SIZES[node.fontSize];
  var stickyFontSize = node.fontSize && FONT_SIZES[node.fontSize] ? FONT_SIZES[node.fontSize] : '15px';
  var textAlign = node.textAlign || (isSticky ? 'center' : 'left');
  var verticalAlign = node.verticalAlign || 'top';
  var vJustify = verticalAlign === 'middle' ? 'center' : verticalAlign === 'bottom' ? 'flex-end' : 'flex-start';

  var overrideBg = isPlaceholder && !isDrawing ? '#f0f4f8' : isWireframe && !isDrawing ? '#fafaf5' : bg;
  var fontFamily = isWireframe ? '"Comic Sans MS","Comic Sans","Marker Felt",cursive' : 'inherit';

  var style = 'position:absolute;left:' + node.x + 'px;top:' + top + 'px;width:' + node.width + 'px;height:' + height + 'px;';
  style += 'background:' + overrideBg + ';border:' + border + ';border-left:' + borderLeft + ';';
  style += 'border-radius:' + borderRadius + ';box-shadow:' + shadow + ';overflow:visible;';
  style += 'z-index:' + (isGroup ? '0' : '2') + ';';

  var html = '<div class="cv-node" style="' + style + '">';

  // Group label
  if (isGroup && node.label) {
    var labelColor = colorValue || theme.groupColorFallback || '#888';
    html += '<div class="cv-group-label" style="color:' + labelColor + '">' + escapeHtmlInline(node.label) + '</div>';
  }

  var contentClass = 'cv-node-content' + (isSticky ? ' sticky-content' : '') + (isDrawing ? ' drawing-content' : '');
  var contentStyle = 'color:' + (isPlaceholder ? '#8c9baa' : isWireframe ? '#333' : textColor) + ';font-family:' + fontFamily + ';';
  html += '<div class="' + contentClass + '" style="' + contentStyle + '">';

  if (node.type === 'text' && isMermaid) {
    html += '<pre class="cv-mermaid">' + escapeHtmlInline(node.text || '') + '</pre>';
  }

  // Text node content
  if (node.type === 'text' && !isSticky && !isDrawing && !isMermaid) {
    if (isPlaceholder) {
      html += '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;gap:12px;padding:20px;user-select:none">';
      html += '<svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor" opacity="0.35"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V5h14v14zm-5-7l-3 3.72L9 13l-3 4h12l-4-5z"/></svg>';
      html += '<span style="font-size:13px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;opacity:0.5;text-align:center">' + escapeHtmlInline(node.text || 'Placeholder') + '</span>';
      html += '</div>';
    } else if (node.text) {
      html += '<div class="node-scrollable" style="overflow:auto;flex:1;font-size:' + fontSize + ';line-height:1.5;text-align:' + textAlign + ';display:flex;flex-direction:column;justify-content:' + vJustify + '">';
      html += renderMarkdown(node.text);
      html += '</div>';
    }
  }

  // Sticky note
  if (isSticky) {
    if (isPlaceholder) {
      html += '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;gap:12px;padding:20px;user-select:none">';
      html += '<span style="font-size:13px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;opacity:0.5;text-align:center">' + escapeHtmlInline(node.text || 'Placeholder') + '</span>';
      html += '</div>';
    } else if (node.text) {
      var sAlign = node.textAlign === 'left' ? 'flex-start' : node.textAlign === 'right' ? 'flex-end' : 'center';
      var sVJustify = node.verticalAlign === 'bottom' ? 'flex-end' : node.verticalAlign === 'middle' ? 'center' : (node.text.length < 60 ? 'center' : 'flex-start');
      html += '<div class="node-scrollable" style="overflow:auto;flex:1;font-size:' + stickyFontSize + ';line-height:1.5;font-weight:500;display:flex;flex-direction:column;align-items:' + sAlign + ';justify-content:' + sVJustify + ';text-align:' + (node.textAlign || 'center') + ';word-break:break-word">';
      html += renderMarkdown(node.text);
      html += '</div>';
    }
  }

  // Drawing node
  if (isDrawing && node.drawingData) {
    html += '<svg width="100%" height="100%" viewBox="0 0 ' + node.width + ' ' + node.height + '" style="position:absolute;top:0;left:0;pointer-events:none">';
    (node.drawingData.paths || []).forEach(function(p) {
      var strokeWidth = finiteNumber(p.strokeWidth, 2);
      if (strokeWidth < 0) strokeWidth = 2;
      html += '<path d="' + pointsToPath(p.points) + '" stroke="' + safeColor(p.color, '#e0e0e0') + '" stroke-width="' + strokeWidth + '" fill="none" stroke-linecap="round" stroke-linejoin="round"/>';
    });
    html += '</svg>';
  }

  // File/image node
  if (node.type === 'file') {
    var src = resolveAssetUrl(node.file);
    html += '<div style="flex:1;display:flex;align-items:center;justify-content:center;overflow:hidden">';
    if (isImageSrc(src)) {
      html += '<img class="node-image" src="' + escapeHtmlInline(src) + '" alt="Canvas asset" draggable="false"/>';
    } else {
      html += '<div style="text-align:center;opacity:0.5"><svg width="32" height="32" viewBox="0 0 24 24" fill="currentColor"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V5h14v14zm-5-7l-3 3.72L9 13l-3 4h12l-4-5z"/></svg>';
      html += '<div style="font-size:12px;margin-top:8px">' + escapeHtmlInline(node.file || 'No file') + '</div></div>';
    }
    html += '</div>';
  }

  // Link node
  if (node.type === 'link') {
    html += '<div style="display:flex;flex-direction:column;height:100%;overflow:hidden">';
    if (node.linkMeta && (node.linkMeta.title || node.linkMeta.description)) {
      if (node.linkMeta.image) {
        html += '<div style="flex:1;overflow:hidden;border-radius:6px 6px 0 0"><img src="' + escapeHtmlInline(node.linkMeta.image) + '" style="width:100%;height:100%;object-fit:cover" draggable="false"/></div>';
      }
      html += '<div style="padding:8px 4px 4px;flex-shrink:0">';
      if (node.linkMeta.title) html += '<div style="font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escapeHtmlInline(node.linkMeta.title) + '</div>';
      if (node.linkMeta.description) html += '<div style="font-size:11px;opacity:0.6;margin-top:2px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical">' + escapeHtmlInline(node.linkMeta.description) + '</div>';
      html += '</div>';
    }
    html += '<div style="margin-top:auto;padding:4px;font-size:11px;opacity:0.5;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">';
    var href = safeHref(node.url || '');
    if (href) {
      html += '<a href="' + escapeHtmlInline(href) + '" target="_blank" rel="noopener" style="color:' + theme.linkColor + '">' + escapeHtmlInline(node.url || '') + '</a>';
    } else {
      html += escapeHtmlInline(node.url || '');
    }
    html += '</div></div>';
  }

  // Task / Jira node (simplified display)
  if (node.type === 'jira' || node.type === 'task') {
    var td = node.taskData || node.jiraData || {};
    html += '<div style="display:flex;flex-direction:column;height:100%;gap:6px">';
    if (td.summary || node.jiraKey || td.key) {
      html += '<div style="font-size:14px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escapeHtmlInline(td.summary || td.key || node.jiraKey || '') + '</div>';
    }
    if (td.key || node.jiraKey) {
      html += '<div style="font-size:11px;opacity:0.5">' + escapeHtmlInline(td.key || node.jiraKey) + '</div>';
    }
    if (td.status) {
      html += '<div style="margin-top:auto;display:flex;gap:6px;flex-wrap:wrap">';
      html += '<span style="font-size:11px;padding:2px 8px;border-radius:10px;background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.15)">' + escapeHtmlInline(td.status) + '</span>';
      if (td.issueType) html += '<span style="font-size:11px;padding:2px 8px;border-radius:10px;background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.15)">' + escapeHtmlInline(td.issueType) + '</span>';
      html += '</div>';
    }
    html += '</div>';
  }

  html += '</div>'; // content

  // Reactions
  if (node.reactions && node.reactions.length > 0) {
    var groups = {};
    node.reactions.forEach(function(r) {
      if (!groups[r.emoji]) groups[r.emoji] = { emoji: r.emoji, count: 0 };
      groups[r.emoji].count++;
    });
    html += '<div class="reactions-row" style="position:absolute;bottom:-4px;left:8px">';
    Object.values(groups).forEach(function(g) {
      html += '<span class="reaction-badge" style="background:' + (theme.reactionBg || 'rgba(255,255,255,0.1)') + ';border:1px solid ' + (theme.reactionBorder || 'rgba(255,255,255,0.15)') + ';color:' + (theme.reactionText || '#e0e0e0') + '">' + escapeHtmlInline(g.emoji) + (g.count > 1 ? '<span style="font-size:10px;margin-left:2px">' + g.count + '</span>' : '') + '</span>';
    });
    html += '</div>';
  }

  html += '</div>'; // node
  return html;
}

function escapeHtmlInline(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ---- Grid ----
function renderGrid(theme) {
  if (currentGrid === 'none') { gridLayer.innerHTML = ''; return; }
  var gc = theme.gridColor;
  var gs = GRID_SIZE * zoom;
  var wideGs = GRID_SIZE * 4 * zoom;
  var ox = offsetX, oy = offsetY;

  if (currentGrid === 'dots') {
    gridLayer.innerHTML = '<div style="position:absolute;top:0;left:0;right:0;bottom:0;background-image:radial-gradient(circle,' + gc + ' 1px,transparent 1px);background-size:' + gs + 'px ' + gs + 'px;background-position:' + ox + 'px ' + oy + 'px"></div>';
  } else if (currentGrid === 'wide') {
    gridLayer.innerHTML = '<div style="position:absolute;top:0;left:0;right:0;bottom:0;background-image:linear-gradient(' + gc + ' 1px,transparent 1px),linear-gradient(90deg,' + gc + ' 1px,transparent 1px);background-size:' + wideGs + 'px ' + wideGs + 'px;background-position:' + ox + 'px ' + oy + 'px"></div>';
  } else if (currentGrid === 'cross') {
    gridLayer.innerHTML = '<svg style="position:absolute;top:0;left:0;width:100%;height:100%;overflow:hidden"><defs><pattern id="xp" width="' + gs + '" height="' + gs + '" patternUnits="userSpaceOnUse" x="' + (ox%gs) + '" y="' + (oy%gs) + '"><line x1="' + (gs/2-3) + '" y1="' + gs/2 + '" x2="' + (gs/2+3) + '" y2="' + gs/2 + '" stroke="' + gc + '" stroke-width="1"/><line x1="' + gs/2 + '" y1="' + (gs/2-3) + '" x2="' + gs/2 + '" y2="' + (gs/2+3) + '" stroke="' + gc + '" stroke-width="1"/></pattern></defs><rect width="100%" height="100%" fill="url(#xp)"/></svg>';
  } else {
    gridLayer.innerHTML = '<div style="position:absolute;top:0;left:0;right:0;bottom:0;background-image:linear-gradient(' + gc + ' 1px,transparent 1px),linear-gradient(90deg,' + gc + ' 1px,transparent 1px);background-size:' + gs + 'px ' + gs + 'px;background-position:' + ox + 'px ' + oy + 'px"></div>';
  }
}

function updateTransform() {
  transformLayer.style.transform = 'translate(' + offsetX + 'px,' + offsetY + 'px) scale(' + zoom + ')';
  zoomDisplay.textContent = Math.round(zoom * 100) + '%';
}

function updateStatusBar(nodes, edges) {
  statusBar.textContent = nodes.length + ' node' + (nodes.length !== 1 ? 's' : '') + ', ' + edges.length + ' edge' + (edges.length !== 1 ? 's' : '');
}

// ---- Toolbar interactions ----
document.getElementById('canvas-title').textContent = CANVAS_TITLE;

// Theme dropdown
var themeMenu = document.getElementById('theme-menu');
Object.keys(THEMES).forEach(function(key) {
  var t = THEMES[key];
  var opt = document.createElement('div');
  opt.className = 'theme-option';
  opt.innerHTML = '<span class="theme-swatch" style="background:' + t.canvasBg + ';border-color:' + (key === currentTheme ? '#0066cc' : '#555') + '"></span><span>' + t.name + '</span>';
  opt.addEventListener('click', function(e) {
    e.stopPropagation();
    currentTheme = key;
    render();
    closeAllDropdowns();
  });
  themeMenu.appendChild(opt);
});

// Grid dropdown
var gridMenu = document.getElementById('grid-menu');
['lines','wide','dots','cross','none'].forEach(function(g) {
  var names = { lines: 'Lines', wide: 'Wide Lines', dots: 'Dots', cross: 'Crosses', none: 'None' };
  var opt = document.createElement('div');
  opt.className = 'theme-option';
  opt.textContent = names[g];
  opt.addEventListener('click', function(e) {
    e.stopPropagation();
    currentGrid = g;
    document.getElementById('grid-name').textContent = names[g];
    render();
    closeAllDropdowns();
  });
  gridMenu.appendChild(opt);
});

// Device dropdown
var deviceMenu = document.getElementById('device-menu');
[{id:'mouse',name:'Mouse',desc:'Scroll wheel zooms'},{id:'trackpad',name:'Trackpad',desc:'Two-finger scroll pans, pinch zooms'}].forEach(function(d) {
  var opt = document.createElement('div');
  opt.className = 'theme-option';
  opt.innerHTML = '<span>' + d.name + '</span><span style="font-size:11px;opacity:0.5;margin-left:8px">' + d.desc + '</span>';
  opt.addEventListener('click', function(e) {
    e.stopPropagation();
    inputDevice = d.id;
    document.getElementById('device-name').textContent = d.name;
    closeAllDropdowns();
  });
  deviceMenu.appendChild(opt);
});

// Dropdown toggle logic
function closeAllDropdowns() {
  document.querySelectorAll('.dropdown-menu').forEach(function(m) { m.classList.remove('open'); });
}

['theme','grid','device'].forEach(function(id) {
  document.getElementById(id + '-toggle').addEventListener('click', function(e) {
    e.stopPropagation();
    var menu = document.getElementById(id + '-menu');
    var isOpen = menu.classList.contains('open');
    closeAllDropdowns();
    if (!isOpen) menu.classList.add('open');
  });
});

document.addEventListener('click', closeAllDropdowns);

// Zoom controls
document.getElementById('zoom-in').addEventListener('click', function() {
  zoom = Math.min(5, zoom * 1.2);
  updateTransform();
  renderGrid(THEMES[currentTheme] || THEMES.graph);
});

document.getElementById('zoom-out').addEventListener('click', function() {
  zoom = Math.max(0.1, zoom / 1.2);
  updateTransform();
  renderGrid(THEMES[currentTheme] || THEMES.graph);
});

document.getElementById('zoom-reset').addEventListener('click', function() {
  zoom = 1; offsetX = 0; offsetY = 0;
  updateTransform();
  renderGrid(THEMES[currentTheme] || THEMES.graph);
});

// ---- Pan and zoom interactions ----
canvasWrap.addEventListener('mousedown', function(e) {
  if (e.button === 0 || e.button === 1 || e.button === 2) {
    isPanning = true;
    panStartX = e.clientX; panStartY = e.clientY;
    panOffsetStartX = offsetX; panOffsetStartY = offsetY;
    canvasWrap.classList.add('panning');
    e.preventDefault();
  }
});

window.addEventListener('mousemove', function(e) {
  if (!isPanning) return;
  offsetX = panOffsetStartX + (e.clientX - panStartX);
  offsetY = panOffsetStartY + (e.clientY - panStartY);
  updateTransform();
  renderGrid(THEMES[currentTheme] || THEMES.graph);
});

window.addEventListener('mouseup', function() {
  if (isPanning) {
    isPanning = false;
    canvasWrap.classList.remove('panning');
  }
});

canvasWrap.addEventListener('wheel', function(e) {
  // Allow scrolling inside node content areas when they have overflow
  var scrollTarget = e.target.closest('.node-scrollable');
  if (scrollTarget) {
    var isScrollable = scrollTarget.scrollHeight > scrollTarget.clientHeight;
    if (isScrollable) {
      var atTop = scrollTarget.scrollTop === 0;
      var atBottom = scrollTarget.scrollTop + scrollTarget.clientHeight >= scrollTarget.scrollHeight - 1;
      var scrollingUp = e.deltaY < 0;
      var scrollingDown = e.deltaY > 0;
      if ((scrollingUp && !atTop) || (scrollingDown && !atBottom)) {
        return; // let the node content scroll naturally
      }
    }
  }
  e.preventDefault();
  if (inputDevice === 'trackpad') {
    if (e.ctrlKey) {
      // Pinch zoom
      var rect = canvasWrap.getBoundingClientRect();
      var mx = e.clientX - rect.left, my = e.clientY - rect.top;
      var oldZoom = zoom;
      zoom = Math.max(0.1, Math.min(5, zoom * (1 - e.deltaY * 0.01)));
      offsetX = mx - (mx - offsetX) * (zoom / oldZoom);
      offsetY = my - (my - offsetY) * (zoom / oldZoom);
    } else {
      offsetX -= e.deltaX;
      offsetY -= e.deltaY;
    }
  } else {
    // Mouse: wheel zooms
    var rect = canvasWrap.getBoundingClientRect();
    var mx = e.clientX - rect.left, my = e.clientY - rect.top;
    var oldZoom = zoom;
    var factor = e.deltaY > 0 ? 0.9 : 1.1;
    zoom = Math.max(0.1, Math.min(5, zoom * factor));
    offsetX = mx - (mx - offsetX) * (zoom / oldZoom);
    offsetY = my - (my - offsetY) * (zoom / oldZoom);
  }
  updateTransform();
  renderGrid(THEMES[currentTheme] || THEMES.graph);
}, { passive: false });

// Touch support
var touchState = { panning: false, pinching: false, startX: 0, startY: 0, startDist: 0, startZoom: 1 };

canvasWrap.addEventListener('touchstart', function(e) {
  if (e.touches.length === 1) {
    touchState.panning = true;
    touchState.startX = e.touches[0].clientX;
    touchState.startY = e.touches[0].clientY;
    panOffsetStartX = offsetX;
    panOffsetStartY = offsetY;
  } else if (e.touches.length === 2) {
    touchState.panning = false;
    touchState.pinching = true;
    var dx = e.touches[0].clientX - e.touches[1].clientX;
    var dy = e.touches[0].clientY - e.touches[1].clientY;
    touchState.startDist = Math.sqrt(dx*dx + dy*dy);
    touchState.startZoom = zoom;
  }
  e.preventDefault();
}, { passive: false });

canvasWrap.addEventListener('touchmove', function(e) {
  if (touchState.panning && e.touches.length === 1) {
    offsetX = panOffsetStartX + (e.touches[0].clientX - touchState.startX);
    offsetY = panOffsetStartY + (e.touches[0].clientY - touchState.startY);
    updateTransform();
    renderGrid(THEMES[currentTheme] || THEMES.graph);
  } else if (touchState.pinching && e.touches.length === 2) {
    var dx = e.touches[0].clientX - e.touches[1].clientX;
    var dy = e.touches[0].clientY - e.touches[1].clientY;
    var dist = Math.sqrt(dx*dx + dy*dy);
    zoom = Math.max(0.1, Math.min(5, touchState.startZoom * (dist / touchState.startDist)));
    updateTransform();
    renderGrid(THEMES[currentTheme] || THEMES.graph);
  }
  e.preventDefault();
}, { passive: false });

canvasWrap.addEventListener('touchend', function() {
  touchState.panning = false;
  touchState.pinching = false;
});

canvasWrap.addEventListener('contextmenu', function(e) { e.preventDefault(); });

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
  if (e.key === '=' || e.key === '+') { if (e.metaKey || e.ctrlKey) { e.preventDefault(); zoom = Math.min(5, zoom * 1.2); updateTransform(); renderGrid(THEMES[currentTheme]); } }
  if (e.key === '-') { if (e.metaKey || e.ctrlKey) { e.preventDefault(); zoom = Math.max(0.1, zoom / 1.2); updateTransform(); renderGrid(THEMES[currentTheme]); } }
  if (e.key === '0') { if (e.metaKey || e.ctrlKey) { e.preventDefault(); zoom = 1; offsetX = 0; offsetY = 0; updateTransform(); renderGrid(THEMES[currentTheme]); } }
});

// Fit to content on load
function fitToContent() {
  var nodes = CANVAS_DATA.nodes || [];
  if (!nodes.length) return;
  var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  nodes.forEach(function(n) {
    minX = Math.min(minX, n.x);
    minY = Math.min(minY, n.y);
    maxX = Math.max(maxX, n.x + n.width);
    maxY = Math.max(maxY, n.y + n.height);
  });
  var cw = maxX - minX, ch = maxY - minY;
  var rect = canvasWrap.getBoundingClientRect();
  var vw = rect.width, vh = rect.height;
  var padding = 80;
  zoom = Math.min(1, Math.min((vw - padding*2) / cw, (vh - padding*2) / ch));
  zoom = Math.max(0.1, zoom);
  offsetX = (vw / 2) - ((minX + cw/2) * zoom);
  offsetY = (vh / 2) - ((minY + ch/2) * zoom);
}

// Init
fitToContent();
render();

})();
