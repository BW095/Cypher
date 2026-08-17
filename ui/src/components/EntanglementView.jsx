/**
 * EntanglementView — Document Dependency Graph
 *
 * Visualises document-to-document [:REFERENCES] relationships and lets
 * the user run a risk simulation: pick a document, mark it as revoked /
 * expired / cancelled, and see all downstream at-risk documents highlighted.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, baseName } from '../api'
import { IconEntangle, IconRefresh, IconAlertCircle, IconCheckCircle } from '../icons'

// ─── Category colours ──────────────────────────────────────────────────────
const CAT_COLORS = {
  invoice:     '#e8a33d',
  contract:    '#60a5fa',
  certificate: '#4ade80',
  form:        '#a78bfa',
  general:     '#94a3b8',
}
const catColor  = (c) => CAT_COLORS[c] || CAT_COLORS.general

// ─── Status badge styles ───────────────────────────────────────────────────
const STATUS_CLS = {
  active:    'ok',
  revoked:   'err',
  expired:   'err',
  cancelled: 'err',
  suspended: 'warn',
}

// ─── Mini force-directed layout (no lib needed for doc-level graph) ────────
function useLayout(nodes, edges) {
  const [positions, setPositions] = useState({})

  useEffect(() => {
    if (!nodes.length) { setPositions({}); return }

    // Initialise random positions
    const pos = {}
    nodes.forEach((n, i) => {
      const angle = (i / nodes.length) * 2 * Math.PI
      const r = 200
      pos[n.id] = { x: 400 + r * Math.cos(angle), y: 280 + r * Math.sin(angle) }
    })

    // Simple spring simulation (50 ticks)
    const adj = {}
    edges.forEach(e => {
      adj[e.source] = adj[e.source] || []
      adj[e.target] = adj[e.target] || []
      adj[e.source].push(e.target)
      adj[e.target].push(e.source)
    })

    for (let t = 0; t < 60; t++) {
      const force = {}
      nodes.forEach(n => { force[n.id] = { x: 0, y: 0 } })

      // Repulsion
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i].id, b = nodes[j].id
          const dx = pos[a].x - pos[b].x
          const dy = pos[a].y - pos[b].y
          const dist = Math.sqrt(dx * dx + dy * dy) || 1
          const rep = 8000 / (dist * dist)
          force[a].x += (dx / dist) * rep
          force[a].y += (dy / dist) * rep
          force[b].x -= (dx / dist) * rep
          force[b].y -= (dy / dist) * rep
        }
      }

      // Attraction along edges
      edges.forEach(e => {
        const dx = pos[e.source].x - pos[e.target].x
        const dy = pos[e.source].y - pos[e.target].y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const attr = dist * 0.05
        force[e.source].x -= (dx / dist) * attr
        force[e.source].y -= (dy / dist) * attr
        force[e.target].x += (dx / dist) * attr
        force[e.target].y += (dy / dist) * attr
      })

      // Apply
      nodes.forEach(n => {
        pos[n.id].x = Math.max(60, Math.min(740, pos[n.id].x + force[n.id].x * 0.3))
        pos[n.id].y = Math.max(40, Math.min(520, pos[n.id].y + force[n.id].y * 0.3))
      })
    }
    setPositions({ ...pos })
  }, [nodes, edges])

  return positions
}

// ─── SVG graph canvas ──────────────────────────────────────────────────────
function DocGraph({ nodes, edges, atRisk, selected, onSelect }) {
  const positions = useLayout(nodes, edges)
  const atRiskSet = useMemo(() => new Set(atRisk.map(r => r.path)), [atRisk])

  if (!nodes.length) return null

  return (
    <svg
      viewBox="0 0 800 560"
      className="entangle-svg"
      style={{ width: '100%', maxHeight: 520, display: 'block' }}
    >
      <defs>
        <marker id="arr" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
          <polygon points="0 0,8 3,0 6" fill="var(--border-strong)" />
        </marker>
        <marker id="arr-risk" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
          <polygon points="0 0,8 3,0 6" fill="var(--err)" />
        </marker>
      </defs>

      {/* Edges */}
      {edges.map((e, i) => {
        const sp = positions[e.source], tp = positions[e.target]
        if (!sp || !tp) return null
        const isRisk = atRiskSet.has(e.source) || atRiskSet.has(e.target)
        const mid = { x: (sp.x + tp.x) / 2, y: (sp.y + tp.y) / 2 }
        return (
          <g key={i}>
            <line
              x1={sp.x} y1={sp.y} x2={tp.x} y2={tp.y}
              stroke={isRisk ? 'var(--err)' : 'var(--border-strong)'}
              strokeWidth={isRisk ? 2 : 1.5}
              markerEnd={isRisk ? 'url(#arr-risk)' : 'url(#arr)'}
              strokeDasharray={isRisk ? '5,3' : undefined}
              opacity={0.7}
            />
            {e.ref_id && (
              <text
                x={mid.x} y={mid.y - 5}
                textAnchor="middle"
                fill={isRisk ? 'var(--err)' : 'var(--text-faint)'}
                fontSize={9}
                fontFamily="var(--font-mono)"
              >{e.ref_id}</text>
            )}
          </g>
        )
      })}

      {/* Nodes */}
      {nodes.map(n => {
        const p = positions[n.id]
        if (!p) return null
        const isSelected = n.id === selected
        const isRisk = atRiskSet.has(n.id)
        const isSource = selected === n.id && atRisk.length > 0
        const fill = isSource
          ? '#f87171'
          : isRisk
          ? 'rgba(248,113,113,0.25)'
          : catColor(n.category)
        const ring = isSelected ? 'var(--accent)' : isRisk ? 'var(--err)' : 'transparent'
        return (
          <g key={n.id} style={{ cursor: 'pointer' }} onClick={() => onSelect(n)}>
            <circle
              cx={p.x} cy={p.y} r={20}
              fill={fill}
              stroke={ring}
              strokeWidth={isSelected || isRisk ? 2.5 : 0}
              opacity={0.9}
            />
            {isRisk && !isSource && (
              <text x={p.x + 13} y={p.y - 13} fontSize={14} fill="var(--err)">⚠</text>
            )}
            <text
              x={p.x} y={p.y + 4}
              textAnchor="middle"
              fill="#fff"
              fontSize={8}
              fontFamily="var(--font-sans)"
              style={{ pointerEvents: 'none', userSelect: 'none' }}
            >
              {n.name.length > 14 ? n.name.slice(0, 13) + '…' : n.name}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

// ─── Main view ─────────────────────────────────────────────────────────────
const EVENT_OPTIONS = ['revoked', 'expired', 'cancelled', 'suspended']

export default function EntanglementView() {
  const [graph, setGraph]       = useState({ nodes: [], edges: [] })
  const [loading, setLoading]   = useState(false)
  const [selected, setSelected] = useState(null)   // selected Document node
  const [event, setEvent]       = useState('revoked')
  const [atRisk, setAtRisk]     = useState([])
  const [riskBusy, setRiskBusy] = useState(false)
  const [riskErr, setRiskErr]   = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.entanglementGraph()
      setGraph(data)
      setSelected(null)
      setAtRisk([])
    } catch (e) {
      console.warn('Entanglement graph load failed', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const runRisk = async () => {
    if (!selected) return
    setRiskBusy(true)
    setRiskErr(null)
    try {
      const result = await api.riskChain(selected.id, event, true)
      setAtRisk(result.at_risk || [])
      // Refresh graph to show updated status colour
      const updated = await api.entanglementGraph()
      setGraph(updated)
    } catch (e) {
      setRiskErr(e.message)
    } finally {
      setRiskBusy(false)
    }
  }

  const restore = async () => {
    if (!selected) return
    try {
      await api.updateDocStatus(selected.id, 'active')
      setAtRisk([])
      const updated = await api.entanglementGraph()
      setGraph(updated)
    } catch (e) {
      console.warn('Restore failed', e)
    }
  }

  const { nodes, edges } = graph

  return (
    <div className="knowledge">
      <div className="knowledge-inner">
        <div className="page-head">
          <h1>Document Entanglement Graph</h1>
          <p>
            Map how documents legally depend on each other.
            When a document is revoked or expires, Cypher instantly surfaces all downstream documents at risk.
          </p>
        </div>

        {/* Stats bar */}
        <div className="stats">
          <div className="stat ok">
            <div className="stat-value">{nodes.length}</div>
            <div className="stat-label">Documents</div>
          </div>
          <div className="stat ok">
            <div className="stat-value">{edges.length}</div>
            <div className="stat-label">Dependencies</div>
          </div>
          <div className="stat">
            <div className="stat-value" style={{ color: atRisk.length ? 'var(--err)' : undefined }}>
              {atRisk.length}
            </div>
            <div className="stat-label">At Risk</div>
          </div>
          <div className="stat">
            <div className="stat-value">
              {nodes.filter(n => n.status !== 'active').length}
            </div>
            <div className="stat-label">Revoked / Expired</div>
          </div>
        </div>

        {/* Graph panel */}
        <div className="panel">
          <div className="panel-head">
            <IconEntangle size={15} />
            <h2>Dependency Map</h2>
            <div className="spacer" />
            <button className="icon-btn" title="Reload" onClick={load}>
              <IconRefresh size={15} />
            </button>
          </div>

          {/* Category legend */}
          <div className="graph-legend" style={{ marginBottom: 8 }}>
            {Object.entries(CAT_COLORS).map(([cat, clr]) => (
              <span className="legend-item" key={cat}>
                <span className="legend-dot" style={{ background: clr }} />
                {cat}
              </span>
            ))}
          </div>

          {loading ? (
            <div className="empty-row">Loading dependency graph…</div>
          ) : nodes.length === 0 ? (
            <div className="empty-row">
              No document links detected yet. Ingest documents that reference each other (invoices referencing POs, contracts referencing framework agreements) to build the entanglement graph.
            </div>
          ) : (
            <DocGraph
              nodes={nodes}
              edges={edges}
              atRisk={atRisk}
              selected={selected?.id}
              onSelect={(n) => { setSelected(n); setAtRisk([]) }}
            />
          )}
        </div>

        {/* Risk simulation panel */}
        <div className="panel">
          <div className="panel-head">
            <IconAlertCircle size={15} />
            <h2>Risk Simulation</h2>
          </div>

          <div className="entangle-sim">
            {/* Document picker */}
            <div className="entangle-sim-row">
              <label className="entangle-label">Document</label>
              <select
                className="entangle-select"
                value={selected?.id || ''}
                onChange={e => {
                  const n = nodes.find(n => n.id === e.target.value)
                  setSelected(n || null)
                  setAtRisk([])
                }}
              >
                <option value="">— click a node above or pick here —</option>
                {nodes.map(n => (
                  <option key={n.id} value={n.id}>{n.name}</option>
                ))}
              </select>
            </div>

            {/* Event type */}
            <div className="entangle-sim-row">
              <label className="entangle-label">Event</label>
              <div className="entangle-event-btns">
                {EVENT_OPTIONS.map(ev => (
                  <button
                    key={ev}
                    className={`entangle-event-btn ${event === ev ? 'active' : ''}`}
                    onClick={() => setEvent(ev)}
                  >
                    {ev}
                  </button>
                ))}
              </div>
            </div>

            {/* Actions */}
            <div className="entangle-sim-row">
              <button
                className="btn-primary"
                onClick={runRisk}
                disabled={riskBusy || !selected}
              >
                {riskBusy ? 'Analysing…' : 'Run Risk Analysis'}
              </button>
              {selected && atRisk.length > 0 && (
                <button className="btn-secondary" onClick={restore}>
                  Restore to Active
                </button>
              )}
            </div>

            {riskErr && <div className="form-error">{riskErr}</div>}
          </div>

          {/* Results */}
          {atRisk.length > 0 && (
            <div className="entangle-results">
              <div className="entangle-results-head">
                <IconAlertCircle size={14} />
                <strong>{atRisk.length} document{atRisk.length > 1 ? 's' : ''} at risk</strong>
                {selected && <span className="entangle-source">because <em>{selected.name}</em> is {event}</span>}
              </div>
              <div className="entangle-risk-list">
                {atRisk.map((r, i) => (
                  <div key={i} className="entangle-risk-row">
                    <span
                      className="legend-dot"
                      style={{ background: catColor(r.category), flexShrink: 0 }}
                    />
                    <span className="entangle-risk-name">{r.name}</span>
                    <span className={`badge ${STATUS_CLS[r.status] || 'dim'}`}>{r.category}</span>
                    <span className={`conf-badge ${STATUS_CLS[r.status] || 'dim'}`}
                      style={{ fontSize: 10, padding: '1px 7px' }}>
                      {r.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {selected && atRisk.length === 0 && !riskBusy && (
            <div className="entangle-no-risk">
              <IconCheckCircle size={16} />
              No downstream dependencies found for <strong>{selected.name}</strong>.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
