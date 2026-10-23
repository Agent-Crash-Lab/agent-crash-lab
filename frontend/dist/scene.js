import * as THREE from './vendor/three.module.js';
import { layoutTopology } from './topology.js?v=0.15.0';

void THREE;
const roleNames = {
  agent: 'Agent',
  runner: '실행 준비',
  approval: '승인',
  tool: '도구',
  database: '업무 DB',
  store: '지침·자료',
  report: '결과 보고',
  reviewer: '검사·검토'
};
const esc = v => String(v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function renderIsoScene(container, graph, data = {}, onSelect) {
  const layout = layoutTopology(graph);
  const layers = [...new Set(layout.nodes.map(n => n.layer))].sort((a, b) => a - b);
  const W = 960, H = 540, S = 94, cx = W * 0.5, cy = H * 0.52;
  const P = (x, y, z = 0) => [+(cx + (x - y) * 0.866 * S).toFixed(1), +(cy + (x + y) * 0.5 * S - z * S).toFixed(1)];
  const poly = (pts, fill, stroke = 'none', sw = 1, extra = '') => `<polygon points="${pts.map(p => p.join(',')).join(' ')}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" ${extra}/>`;

  const pos = {};
  const layerSpan = Math.max(layers.length - 1, 1);
  layers.forEach((layer, lIdx) => {
    const members = layout.nodes.filter(n => n.layer === layer);
    const lanes = members.map(m => m.lane ?? 0);
    const mid = (Math.min(...lanes) + Math.max(...lanes)) / 2;
    const y0 = (lIdx - layerSpan / 2) * 1.15;
    members.forEach(m => {
      const x0 = ((m.lane ?? 0) - mid) * 1.18;
      pos[m.id] = [x0, y0];
    });
  });

  let defs = `<defs>
    <linearGradient id="grad-platform-a" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="var(--iso-plat-grad-hi-1, #1e1e24)"/>
      <stop offset="100%" stop-color="var(--iso-plat-grad-hi-2, #141418)"/>
    </linearGradient>
    <linearGradient id="grad-platform-b" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="var(--iso-plat-grad-1, #1a1a20)"/>
      <stop offset="100%" stop-color="var(--iso-plat-grad-2, #101014)"/>
    </linearGradient>
    <linearGradient id="grad-fault-flare" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#ff8a5f" stop-opacity="1"/>
      <stop offset="50%" stop-color="#ff3e14" stop-opacity="0.8"/>
      <stop offset="100%" stop-color="#ff8a5f" stop-opacity="0"/>
    </linearGradient>
    <radialGradient id="grad-glow-active" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#ff6a3d" stop-opacity="0.45"/>
      <stop offset="70%" stop-color="#ff6a3d" stop-opacity="0.12"/>
      <stop offset="100%" stop-color="#ff6a3d" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="grad-glow-emerald" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#34b38a" stop-opacity="0.4"/>
      <stop offset="70%" stop-color="#34b38a" stop-opacity="0.1"/>
      <stop offset="100%" stop-color="#34b38a" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="laser-trail" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="1"/>
      <stop offset="60%" stop-color="#6fd4ab" stop-opacity="0.7"/>
      <stop offset="100%" stop-color="#34b38a" stop-opacity="0"/>
    </linearGradient>
    <filter id="f-glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3.5" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="f-intense" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="5.5" result="blur1"/>
      <feGaussianBlur stdDeviation="2.5" result="blur2"/>
      <feMerge><feMergeNode in="blur1"/><feMergeNode in="blur2"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>`;

  let g = defs;

  // 0. Ambient Holographic Data Dust / Grid Accents
  g += `<g class="ambient-backdrop" opacity="0.45">`;
  const stars = [
    [-2.2, -1.8, 0.4], [-1.5, 1.7, 0.6], [2.1, -1.2, 0.5], [1.8, 1.4, 0.7],
    [-0.8, -2.1, 0.3], [0.9, -1.9, 0.8], [-2.1, 0.8, 0.5], [2.3, 0.3, 0.4]
  ];
  stars.forEach(([sx, sy, sz], idx) => {
    const sp = P(sx, sy, sz);
    g += `<circle cx="${sp[0]}" cy="${sp[1]}" r="1.4" fill="#586e7a" opacity="0.6"><animate attributeName="opacity" values="0.2;0.8;0.2" dur="${3 + (idx % 3)}s" repeatCount="indefinite" begin="${idx * 0.4}s"/></circle>`;
  });
  g += `</g>`;

  // 1. Terraced 3D Industrial Platforms with Bevels and Neon Edges
  layers.forEach((_, lIdx) => {
    const y0 = (lIdx - layerSpan / 2) * 1.15;
    const a = P(-2.05, y0 - 0.48), b = P(2.05, y0 - 0.48), c = P(2.05, y0 + 0.48), d = P(-2.05, y0 + 0.48), t = 0.14;
    const ad = [a[0], a[1] + t * S], bd = [b[0], b[1] + t * S], cd = [c[0], c[1] + t * S], dd = [d[0], d[1] + t * S];
    const fillTop = lIdx % 2 ? 'url(#grad-platform-a)' : 'url(#grad-platform-b)';

    // Ground platform base & bevels
    g += `<g class="iso-platform" data-layer="${lIdx}">`;
    g += poly([d, c, cd, dd], 'var(--iso-plat-front, #0a0a0d)', 'var(--iso-plat-edge, #141419)', 1);
    g += poly([b, c, cd, bd], 'var(--iso-plat-side, #060608)', 'var(--iso-plat-edge, #141419)', 1);
    g += poly([a, b, c, d], fillTop, 'var(--iso-plat-top-edge, #272732)', 1);

    // Neon edge highlight rail on front platform rim
    g += `<line x1="${d[0]}" y1="${d[1]}" x2="${c[0]}" y2="${c[1]}" stroke="var(--iso-plat-rim, #343444)" stroke-width="1.8"/>`;
    g += `<line x1="${c[0]}" y1="${c[1]}" x2="${b[0]}" y2="${b[1]}" stroke="var(--iso-plat-rim-side, #282836)" stroke-width="1.6"/>`;

    // Ambient platform coordinate markers
    const pMarkA = P(-1.95, y0 + 0.42);
    const pMarkB = P(1.95, y0 - 0.42);
    g += `<circle cx="${pMarkA[0]}" cy="${pMarkA[1]}" r="2" fill="#3a3a4c"/>`;
    g += `<circle cx="${pMarkB[0]}" cy="${pMarkB[1]}" r="2" fill="#3a3a4c"/>`;
    g += `</g>`;
  });

  // 2. Optical Fiber Conduits & High-Energy Animated Data Packets
  graph.edges.forEach((edge, i) => {
    const p1 = pos[edge.source], p2 = pos[edge.target];
    if (!p1 || !p2) return;
    const isActive = data.activeEdge === edge.id;
    const isFault = isActive && !!data.fault;
    const isSeen = isActive || (data.observedEdges || []).includes(edge.id);
    const reverse = graph.edges.some(e => e.source === edge.target && e.target === edge.source);
    const off = isFault ? 0.22 : reverse ? (edge.source < edge.target ? 0.16 : -0.16) : 0;
    const pts = [P(p1[0] + off, p1[1], 0.03), P(p1[0] + off, p2[1], 0.03), P(p2[0] + off, p2[1], 0.03)];
    const d = `M${pts[0]} L${pts[1]} L${pts[2]}`;

    // Conduit track underlay
    g += `<path d="${d}" fill="none" stroke="var(--iso-track-under, #101015)" stroke-width="5" stroke-linecap="round"/>`;
    g += `<path d="${d}" fill="none" stroke="${isFault ? '#4a1e14' : isSeen ? '#2a3a34' : '#1e1e28'}" stroke-width="2.6" stroke-linecap="round"/>`;

    // Core fiber optical line
    const col = isFault ? '#ff6a3d' : isActive ? '#ff8a5f' : isSeen ? '#50dfb0' : '#30303e';
    g += `<path d="${d}" fill="none" stroke="${col}" stroke-width="${isActive ? 2.4 : 1.6}" ${isFault ? 'stroke-dasharray="8 6" class="fault-wire-glitch"' : ''} opacity="${isSeen ? 0.95 : 0.65}" ${isActive ? 'filter="url(#f-glow)"' : ''}/>`;

    if (isFault) {
      // Fault Injection Shock Zone: Split-waypoint & Interrupted Packet
      const m = P(p1[0] + off, (p1[1] + p2[1]) / 2, 0.03);
      const half = `M${pts[0]} L${m}`;

      // Staggered packet attempts that fail at the fault boundary
      g += `<g class="fault-packet-burst">
        <circle r="4.2" fill="#ff6a3d" filter="url(#f-intense)">
          <animateMotion dur="1.3s" repeatCount="indefinite" path="${half}"/>
        </circle>
        <circle r="2.2" fill="#ffffff">
          <animateMotion dur="1.3s" repeatCount="indefinite" path="${half}"/>
        </circle>
      </g>`;

      // High-Voltage Fault Sever Node with hazard pulse
      g += `<g transform="translate(${m[0]}, ${m[1]})">
        <g class="hazard-node">
          <circle r="22" fill="url(#grad-glow-active)"/>
          <circle r="13" fill="#200d07" stroke="#ff6a3d" stroke-width="2" filter="url(#f-glow)"/>
          <path d="M-5 -5 L5 5 M5 -5 L-5 5" stroke="#ff8a5f" stroke-width="2.2" stroke-linecap="round"/>
          <circle r="17" fill="none" stroke="#ff6a3d" stroke-width="1.2" stroke-dasharray="4 4" opacity="0.8">
            <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="4s" repeatCount="indefinite"/>
          </circle>
        </g>
      </g>`;
    } else if (isSeen) {
      // Flowing Energy Packet Train (Head + 2 Staggered Trail Spheres)
      const speed = isActive ? 1.6 : 2.4 + (i % 3) * 0.4;
      g += `<g class="packet-train">
        <circle r="${isActive ? 4.2 : 3.2}" fill="${isActive ? '#ffffff' : '#6fd4ab'}" filter="${isActive ? 'url(#f-intense)' : 'url(#f-glow)'}">
          <animateMotion dur="${speed}s" repeatCount="indefinite" path="${d}"/>
        </circle>
        <circle r="${isActive ? 2.6 : 2.0}" fill="${isActive ? '#ff8a5f' : '#34b38a'}" opacity="0.75">
          <animateMotion dur="${speed}s" repeatCount="indefinite" path="${d}" begin="0.08s"/>
        </circle>
        <circle r="1.4" fill="${isActive ? '#ff6a3d' : '#1e664e'}" opacity="0.45">
          <animateMotion dur="${speed}s" repeatCount="indefinite" path="${d}" begin="0.16s"/>
        </circle>
      </g>`;
    }
  });

  // 3. 3D Role-Specific Hardware Modules (Sorted back-to-front for proper isometric depth occlusion)
  const order = [...layout.nodes].sort((a, b) => (pos[a.id][0] + pos[a.id][1]) - (pos[b.id][0] + pos[b.id][1]));
  order.forEach(nd => {
    const [x, y] = pos[nd.id];
    const count = data.counts?.[nd.id] ?? 0;
    const commits = data.commits?.[nd.id] ?? 0;
    const isActive = data.activeNode === nd.id;
    const isFault = isActive && !!data.fault;
    const isDim = !data.preview && count === 0 && !isActive;
    const kind = nd.role === 'database' ? 'cyl' : nd.role === 'approval' ? 'disc' : nd.role === 'agent' ? 'screen' : 'box';
    const w = 0.29, h = kind === 'disc' ? 0.09 : kind === 'cyl' ? 0.46 : 0.36;

    // Palette per state
    const top = isFault ? '#3d2014' : isActive ? '#38251c' : isDim ? 'var(--iso-node-dim-top, #222227)' : 'var(--iso-node-default-top, #2b2b34)';
    const left = isFault ? '#2c150c' : isActive ? '#281811' : isDim ? 'var(--iso-node-dim-left, #17171b)' : 'var(--iso-node-default-left, #1e1e24)';
    const right = isFault ? '#200e07' : isActive ? '#1c100a' : isDim ? 'var(--iso-node-dim-right, #111114)' : 'var(--iso-node-default-right, #17171c)';
    const strokeCol = isFault ? '#ff6a3d' : isActive ? '#ff8a5f' : isDim ? 'var(--iso-node-dim-stroke, #2a2a32)' : 'var(--iso-node-default-stroke, #3e3e4a)';

    // Ambient Shockwave & Holographic Base Glow
    if (isFault || isActive) {
      const c = P(x, y, 0);
      const rx = (0.94 * S).toFixed(1), ry = (0.54 * S).toFixed(1);
      g += `<ellipse class="shock s1" cx="${c[0]}" cy="${c[1]}" rx="${rx}" ry="${ry}" fill="none" stroke="${isFault ? '#ff6a3d' : '#ff8a5f'}" stroke-width="1.8"/>`;
      g += `<ellipse class="shock s2" cx="${c[0]}" cy="${c[1]}" rx="${rx}" ry="${ry}" fill="none" stroke="${isFault ? '#ff3e14' : '#ff6a3d'}" stroke-width="1.2"/>`;
      if (isFault) {
        g += `<ellipse class="shock s3" cx="${c[0]}" cy="${c[1]}" rx="${rx}" ry="${ry}" fill="none" stroke="#ff8a5f" stroke-width="0.9"/>`;
      }
    }

    g += `<g data-node-hit="${esc(nd.id)}" class="iso-node-group ${isActive ? 'is-active' : ''} ${isFault ? 'is-fault' : ''}" style="cursor:pointer">`;

    if (kind === 'cyl') {
      // ── DATABASE: Multi-Tier Pressure Silo with Dynamic Data Ring & Commit Fluid Level ──
      const c0 = P(x, y, 0), c1 = P(x, y, h), rx = +(w * 1.25 * S).toFixed(1), ry = +(w * 0.72 * S).toFixed(1);

      // Shadow under cylinder
      g += `<ellipse cx="${c0[0]}" cy="${c0[1]}" rx="${rx + 4}" ry="${ry + 3}" fill="#0a0a0d" opacity="0.6"/>`;

      // Silo body wall
      g += `<path d="M${c0[0] - rx},${c1[1]} L${c0[0] - rx},${c0[1]} A${rx},${ry} 0 0 0 ${c0[0] + rx},${c0[1]} L${c0[0] + rx},${c1[1]} Z" fill="${left}" stroke="${strokeCol}" stroke-width="1.2"/>`;

      // Horizontal magnetic ribs
      const rib1 = (c0[1] * 0.65 + c1[1] * 0.35).toFixed(1);
      const rib2 = (c0[1] * 0.35 + c1[1] * 0.65).toFixed(1);
      g += `<path d="M${c0[0] - rx},${rib1} A${rx},${ry} 0 0 0 ${c0[0] + rx},${rib1}" fill="none" stroke="${strokeCol}" stroke-width="1.4"/>`;
      g += `<path d="M${c0[0] - rx},${rib2} A${rx},${ry} 0 0 0 ${c0[0] + rx},${rib2}" fill="none" stroke="${strokeCol}" stroke-width="1.4"/>`;

      // Top lid
      g += `<ellipse cx="${c1[0]}" cy="${c1[1]}" rx="${rx}" ry="${ry}" fill="var(--iso-db-lid, #27333d)" stroke="${commits > 1 ? '#ff6a88' : '#5b92ba'}" stroke-width="1.5"/>`;

      // Glowing liquid commit volume
      const fillRadius = commits > 1 ? rx * 0.82 : commits === 1 ? rx * 0.58 : rx * 0.34;
      const fillRy = commits > 1 ? ry * 0.82 : commits === 1 ? ry * 0.58 : ry * 0.34;
      const liquidCol = commits > 1 ? '#ff6a88' : '#64b5f6';
      g += `<ellipse cx="${c1[0]}" cy="${c1[1]}" rx="${fillRadius.toFixed(1)}" ry="${fillRy.toFixed(1)}" fill="${liquidCol}" opacity="0.5" filter="url(#f-glow)"><animate attributeName="opacity" values="0.38;0.65;0.38" dur="2.4s" repeatCount="indefinite"/></ellipse>`;

      // Commits counter LED tag directly on the cylinder rim
      if (commits > 0) {
        g += `<circle cx="${c1[0]}" cy="${c1[1]}" r="3" fill="${commits > 1 ? '#ff3e14' : '#29b6f6'}"/>`;
      }
    } else {
      // ── MODULAR 3D BLOCK (Pedestal + Housing) ──
      const A = P(x - w, y - w, h), B = P(x + w, y - w, h), C = P(x + w, y + w, h), D = P(x - w, y + w, h);
      const Bd = P(x + w, y - w, 0), Cd = P(x + w, y + w, 0), Dd = P(x - w, y + w, 0);

      // Block shadow
      const ShA = P(x - w - 0.05, y - w, 0), ShB = P(x + w + 0.05, y - w, 0), ShC = P(x + w + 0.05, y + w + 0.05, 0), ShD = P(x - w - 0.05, y + w + 0.05, 0);
      g += poly([ShA, ShB, ShC, ShD], '#08080b', 'none', 0, 'opacity="0.55"');

      // 3D Box Faces
      g += poly([D, C, Cd, Dd], left, strokeCol, 1.2);
      g += poly([B, C, Cd, Bd], right, strokeCol, 1.2);
      g += poly([A, B, C, D], top, strokeCol, 1.4);

      if (kind === 'screen') {
        // ── AGENT HUB: Angled Cybernetic Workstation Terminal with Hologram Halo ──
        const s1 = P(x - w * 0.6, y - w * 0.12, h);
        const s2 = P(x + w * 0.12, y - w * 0.12, h);
        const s3 = P(x + w * 0.12, y - w * 0.12, h + 0.42);
        const s4 = P(x - w * 0.6, y - w * 0.12, h + 0.42);

        // Terminal bezel & monitor
        g += poly([s1, s2, s3, s4], 'var(--iso-terminal-bg, #0e1014)', isDim ? 'var(--iso-node-dim-stroke, #282832)' : 'var(--iso-terminal-stroke, #4e5464)', 1.4);

        if (!isDim) {
          // Glass reflection highlight
          const r1 = P(x - w * 0.55, y - w * 0.12, h + 0.38), r2 = P(x - w * 0.05, y - w * 0.12, h + 0.38);
          g += `<line x1="${r1[0]}" y1="${r1[1]}" x2="${r2[0]}" y2="${r2[1]}" stroke="#ffffff" stroke-width="0.8" opacity="0.4"/>`;

          // Animated Matrix Code Scanlines
          const l1 = P(x - w * 0.5, y - w * 0.12, h + 0.30), l2 = P(x + w * 0.04, y - w * 0.12, h + 0.30);
          const l3 = P(x - w * 0.5, y - w * 0.12, h + 0.20), l4 = P(x - w * 0.15, y - w * 0.12, h + 0.20);
          const l5 = P(x - w * 0.5, y - w * 0.12, h + 0.10), l6 = P(x - w * 0.02, y - w * 0.12, h + 0.10);

          g += `<g class="agent-code-lines" filter="url(#f-glow)">
            <path d="M${l1}L${l2}" stroke="#6fd4ab" stroke-width="1.8" class="blink"/>
            <path d="M${l3}L${l4}" stroke="#34b38a" stroke-width="1.6"/>
            <path d="M${l5}L${l6}" stroke="#227a5d" stroke-width="1.6"/>
          </g>`;

          // Floating Overhead Holographic Orbit Halo
          const haloPos = P(x, y, h + 0.58);
          g += `<ellipse cx="${haloPos[0]}" cy="${haloPos[1]}" rx="${(w * 0.92 * S).toFixed(1)}" ry="${(w * 0.52 * S).toFixed(1)}" fill="none" stroke="#50dfb0" stroke-width="1.2" stroke-dasharray="10 6" class="halo-orbit" opacity="0.85"/>`;
        }
      }

      if (kind === 'disc') {
        // ── APPROVAL GATE: Dual Rotating Concentric Security Rings ──
        const cDisc = P(x, y, h + 0.03);
        const rxD = +(w * 0.85 * S).toFixed(1), ryD = +(w * 0.48 * S).toFixed(1);
        g += `<ellipse cx="${cDisc[0]}" cy="${cDisc[1]}" rx="${rxD}" ry="${ryD}" fill="var(--iso-disc-bg, #16221c)" stroke="#34b38a" stroke-width="1.6"/>`;
        g += `<ellipse cx="${cDisc[0]}" cy="${cDisc[1]}" rx="${(rxD * 0.65).toFixed(1)}" ry="${(ryD * 0.65).toFixed(1)}" fill="none" stroke="#6fd4ab" stroke-width="1.4" stroke-dasharray="8 4" class="halo-orbit-rev"/>`;
        g += `<circle cx="${cDisc[0]}" cy="${cDisc[1]}" r="3.2" fill="#50dfb0" filter="url(#f-glow)"/>`;
      }

      if (isFault) {
        // Fracture glitch slash on top face
        const A2 = P(x - w * 0.65, y - w * 0.65, h), C2 = P(x + w * 0.65, y + w * 0.65, h);
        g += `<line x1="${A2[0]}" y1="${A2[1]}" x2="${C2[0]}" y2="${C2[1]}" stroke="#ff6a3d" stroke-width="2" class="fault-wire-glitch"/>`;
      }
    }

    g += `</g>`;
  });

  container.dataset.topologyVersion = graph.version;
  container.dataset.nodeCount = String(graph.nodes.length);
  container.dataset.edgeCount = String(graph.edges.length);

  // 4. Interactive Floating High-Tech Scene Labels
  let labelsHtml = '';
  order.forEach(nd => {
    const [x, y] = pos[nd.id];
    const kind = nd.role === 'database' ? 'cyl' : nd.role === 'approval' ? 'disc' : nd.role === 'agent' ? 'screen' : 'box';
    const h = kind === 'disc' ? 0.09 : kind === 'cyl' ? 0.46 : 0.36;
    const L = P(x, y, h + (kind === 'screen' ? 0.68 : 0.48));
    const count = data.counts?.[nd.id] ?? 0;
    const commits = data.commits?.[nd.id] ?? 0;
    const isActive = data.activeNode === nd.id;
    const isFault = isActive && !!data.fault;
    const isDim = !data.preview && count === 0 && !isActive;
    const subText = commits ? `${roleNames[nd.role]} · 저장 ${commits}건` : `${roleNames[nd.role]} · 사건 ${count}`;

    labelsHtml += `<button type="button" class="scene-label ${isActive ? 'selected' : ''} ${isFault ? 'fault-label' : ''} ${count > 0 ? 'observed' : ''} ${isDim ? 'dim-label' : ''}" data-node-id="${esc(nd.id)}" aria-label="${esc(nd.label)} · ${esc(roleNames[nd.role])} · 근거 보기" style="left:${(L[0] / W * 100).toFixed(1)}%;top:${(L[1] / H * 100).toFixed(1)}%"><strong>${esc(nd.label)}</strong><span>${esc(subText)}</span></button>`;
  });

  container.innerHTML = `<svg class="iso-stage-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${g}</svg>${labelsHtml}`;
  container.querySelectorAll('[data-node-id],[data-node-hit]').forEach(el => {
    el.onclick = e => {
      e.stopPropagation();
      const id = el.dataset.nodeId || el.dataset.nodeHit;
      if (id) onSelect?.(id);
    };
  });
}

export function mountScene(container, graph, data, onSelect) {
  if (!container) return;
  try {
    renderIsoScene(container, graph, data, onSelect);
  } catch (error) {
    console.warn('3D unavailable', error);
    container.innerHTML = `<div class="scene-unavailable"><strong>3D 화면을 표시할 수 없습니다.</strong><p>구조 정보와 그래픽 가속을 확인하거나 타임라인을 이용하세요.</p>${data.preview ? '<button data-preview-mode="timeline">구조 목록으로 보기 →</button>' : '<button data-mode="timeline">타임라인으로 보기 →</button>'}</div>`;
  }
}
export function pauseScene() {}
