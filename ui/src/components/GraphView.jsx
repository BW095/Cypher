import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, baseName, entityColor, relationshipColor } from '../api'
import { IconGraph, IconRefresh } from '../icons'
import ForceGraph from './ForceGraph'

function Legend({ types, colorFn = entityColor }) {
  if (!types.length) return null
  return (
    <div className="graph-legend">
      {types.map((t) => (
        <span className="legend-item" key={t}>
          <span className="legend-dot" style={{ background: colorFn(t) }} />
          {t.replace(/_/g, ' ')}
        </span>
      ))}
    </div>
  )
}

export default function GraphView() {
  const [stats, setStats] = useState({
    total_entities: 0,
    total_relationships: 0,
    total_documents: 0,
    entity_types: {},
  })
  const [fullGraph, setFullGraph] = useState({ nodes: [], edges: [] })
  const [loadingGraph, setLoadingGraph] = useState(false)
  const [query, setQuery] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const refreshStats = useCallback(async () => {
    try {
      const data = await api.graphStats()
      setStats(data)
    } catch (err) {
      console.warn('Could not fetch graph stats', err)
    }
  }, [])

  const refreshGraph = useCallback(async () => {
    setLoadingGraph(true)
    try {
      setFullGraph(await api.graphFull())
    } catch (err) {
      console.warn('Could not fetch full graph', err)
    } finally {
      setLoadingGraph(false)
    }
  }, [])

  // Initial load
  useEffect(() => {
    refreshStats()
    refreshGraph()
  }, [refreshStats, refreshGraph])

  const search = async (term) => {
    const q = (term ?? query).trim()
    if (!q || busy) return
    setQuery(q)
    setBusy(true)
    setError(null)
    try {
      const data = await api.graphQuery(q)
      setResult(data)
    } catch (err) {
      setError(err.message)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      search()
    }
  }

  // Entity types present in the full graph, for the legend.
  const legendTypes = useMemo(() => {
    const present = new Set(fullGraph.nodes.map((n) => n.type))
    return [...present].sort()
  }, [fullGraph])

  // Relationship types present in the full graph, for the edge legend.
  const relLegendTypes = useMemo(() => {
    const present = new Set(fullGraph.edges.map((e) => e.type).filter(Boolean))
    return [...present].sort()
  }, [fullGraph])

  const resultSubgraph = useMemo(
    () => (result ? { nodes: result.nodes, edges: result.edges } : null),
    [result]
  )

  return (
    <div className="knowledge">
      <div className="knowledge-inner">
        <div className="page-head">
          <h1>Graph Explorer</h1>
          <p>
            Explore the connections Cypher has discovered between entities in your documents.
            Click any node to focus on it, or search for an equipment ID, location, or term.
          </p>
        </div>

        {/* High-level stats */}
        <div className="stats">
          <div className="stat ok">
            <div className="stat-value">{stats.total_entities}</div>
            <div className="stat-label">Entities</div>
          </div>
          <div className="stat ok">
            <div className="stat-value">{stats.total_relationships}</div>
            <div className="stat-label">Relationships</div>
          </div>
          <div className="stat">
            <div className="stat-value">{stats.total_documents}</div>
            <div className="stat-label">Source Docs</div>
          </div>
          <div className="stat">
            <div className="stat-value">{Object.keys(stats.entity_types).length}</div>
            <div className="stat-label">Entity Types</div>
          </div>
        </div>

        {/* Whole-graph map */}
        <div className="panel">
          <div className="panel-head">
            <IconGraph size={15} />
            <h2>Knowledge Map</h2>
            <div className="spacer" />
            <button className="icon-btn" title="Reload graph" onClick={refreshGraph}>
              <IconRefresh size={15} />
            </button>
          </div>

          <Legend types={legendTypes} />
          {relLegendTypes.length > 0 && (
            <Legend types={relLegendTypes} colorFn={relationshipColor} />
          )}

          {loadingGraph ? (
            <div className="empty-row">Loading graph…</div>
          ) : fullGraph.nodes.length === 0 ? (
            <div className="empty-row">
              No entities in the graph yet. Ingest documents to build the knowledge map.
            </div>
          ) : (
            <ForceGraph data={fullGraph} height={480} onNodeClick={(n) => search(n.name)} />
          )}
        </div>

        {/* Search Panel */}
        <div className="panel">
          <div className="panel-head">
            <IconGraph size={15} />
            <h2>Entity Search</h2>
          </div>

          <div className="add-folder">
            <input
              value={query}
              placeholder={'e.g. Pump P-101, Boiler...'}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
              spellCheck={false}
            />
            <button
              className="btn-primary"
              onClick={() => search()}
              disabled={busy || !query.trim()}
            >
              {busy ? 'Searching...' : 'Search Graph'}
            </button>
          </div>

          {error && <div className="form-error">{error}</div>}

          {/* Results Area */}
          {result && (
            <div className="graph-results">
              {result.nodes.length === 0 ? (
                <div className="empty-row">
                  No entities found matching "{query}".
                </div>
              ) : (
                <>
                  {/* Focused subgraph visualization */}
                  <ForceGraph
                    data={resultSubgraph}
                    height={360}
                    onNodeClick={(n) => search(n.name)}
                  />

                  <div className="graph-tables">
                    <div className="graph-col">
                      <h3>Related Entities ({result.nodes.length})</h3>
                      <div className="graph-list">
                        {result.nodes.map(n => (
                          <div className="graph-item" key={n.id}>
                            <span
                              className="type-dot"
                              style={{ background: entityColor(n.type) }}
                              title={n.type}
                            />
                            <span className={`badge ${n.type === 'Unknown' ? 'dim' : 'ok'}`}>{n.type}</span>
                            <span className="entity-name">{n.name}</span>
                            {n.description && <span className="entity-desc">— {n.description}</span>}
                          </div>
                        ))}
                      </div>
                    </div>

                    {result.edges.length > 0 && (
                      <div className="graph-col">
                        <h3>Relationships ({result.edges.length})</h3>
                        <div className="graph-list">
                          {result.edges.map((e, idx) => {
                            const src = result.nodes.find(n => n.id === e.source)?.name || e.source
                            const tgt = result.nodes.find(n => n.id === e.target)?.name || e.target
                            return (
                              <div className="graph-item edge" key={idx}>
                                <div className="edge-node">{src}</div>
                                <div className="edge-connection">
                                  <div
                                    className="edge-line"
                                    style={{ background: relationshipColor(e.type) }}
                                  ></div>
                                  <span
                                    className="edge-label"
                                    style={{ color: relationshipColor(e.type) }}
                                  >
                                    {e.type}
                                  </span>
                                </div>
                                <div className="edge-node">{tgt}</div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}

                    {result.source_documents.length > 0 && (
                      <div className="graph-col">
                        <h3>Mentioned In ({result.source_documents.length})</h3>
                        <div className="graph-list">
                          {result.source_documents.map((doc, idx) => (
                            <a
                              className="graph-item doc-link"
                              key={idx}
                              href={api.documentUrl(doc)}
                              target="_blank"
                              rel="noreferrer"
                            >
                              <span className="entity-name">{baseName(doc)}</span>
                            </a>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
