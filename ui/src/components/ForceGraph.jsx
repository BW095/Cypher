import { useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { entityColor, relationshipColor } from '../api'

// Hex color -> rgba string at a given alpha, so edges read as tinted-but-subtle.
function withAlpha(hex, alpha) {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || '')
  if (!m) return `rgba(154,163,178,${alpha})`
  const [r, g, b] = [m[1], m[2], m[3]].map((h) => parseInt(h, 16))
  return `rgba(${r},${g},${b},${alpha})`
}

/**
 * Interactive force-directed view of a knowledge subgraph.
 *
 * Nodes are colored by entity type and sized by connection count; edges are
 * drawn with directional arrows and their relationship type. The component
 * self-sizes to its container and re-seeds when `data` changes.
 *
 * react-force-graph mutates the objects it's given (adds x/y, swaps
 * source/target for node refs), so we always hand it fresh clones.
 */
export default function ForceGraph({ data, onNodeClick, height = 460 }) {
  const wrapRef = useRef(null)
  const fgRef = useRef(null)
  const [width, setWidth] = useState(600)
  const [hovered, setHovered] = useState(null)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect?.width
      if (w) setWidth(Math.max(280, Math.floor(w)))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const graphData = useMemo(() => {
    const nodes = (data?.nodes || []).map((n) => ({ ...n }))
    const ids = new Set(nodes.map((n) => n.id))
    // Only keep edges whose endpoints exist, or the graph throws.
    const links = (data?.edges || [])
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .map((e) => ({ ...e }))
    return { nodes, links }
  }, [data])

  // Gentle zoom-to-fit whenever the dataset changes.
  useEffect(() => {
    if (!fgRef.current || graphData.nodes.length === 0) return
    const t = setTimeout(() => {
      try {
        fgRef.current.zoomToFit(400, 40)
      } catch {
        /* graph not ready yet */
      }
    }, 300)
    return () => clearTimeout(t)
  }, [graphData])

  if (!graphData.nodes.length) {
    return <div className="empty-row">No graph data to display.</div>
  }

  const nodeSize = (n) => 3 + Math.min(9, Math.sqrt(n.degree || 1) * 2)

  return (
    <div className="force-graph" ref={wrapRef} style={{ height }}>
      <ForceGraph2D
        ref={fgRef}
        width={width}
        height={height}
        graphData={graphData}
        backgroundColor="rgba(0,0,0,0)"
        cooldownTicks={120}
        nodeRelSize={4}
        nodeVal={(n) => nodeSize(n)}
        nodeColor={(n) => entityColor(n.type)}
        nodeLabel={(n) =>
          `${n.name}  ·  ${n.type}${n.description ? `\n${n.description}` : ''}`
        }
        onNodeHover={(n) => setHovered(n ? n.id : null)}
        onNodeClick={(n) => onNodeClick && onNodeClick(n)}
        linkColor={(l) => withAlpha(relationshipColor(l.type), hovered ? 0.28 : 0.45)}
        linkWidth={1}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkLabel={(l) => l.type}
        nodeCanvasObjectMode={() => 'after'}
        nodeCanvasObject={(node, ctx, globalScale) => {
          // Draw the name next to hubs and hovered nodes; hide labels when
          // zoomed far out to avoid clutter.
          const showLabel =
            hovered === node.id || (node.degree || 0) >= 3 || globalScale > 2.2
          if (!showLabel) return
          const label = node.name || ''
          const fontSize = Math.max(10 / globalScale, 3)
          ctx.font = `${fontSize}px var(--font-sans, sans-serif)`
          ctx.textAlign = 'left'
          ctx.textBaseline = 'middle'
          ctx.fillStyle = 'rgba(231,234,240,0.92)'
          ctx.fillText(label, node.x + nodeSize(node) + 2, node.y)
        }}
      />
    </div>
  )
}
