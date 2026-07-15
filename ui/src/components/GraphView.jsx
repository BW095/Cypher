import { useCallback, useEffect, useState } from 'react'
import { api, baseName } from '../api'
import { IconGraph, IconRefresh } from '../icons'

export default function GraphView() {
  const [stats, setStats] = useState({
    total_entities: 0,
    total_relationships: 0,
    total_documents: 0,
    entity_types: {},
  })
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

  // Initial load
  useEffect(() => {
    refreshStats()
  }, [refreshStats])

  const search = async () => {
    if (!query.trim() || busy) return
    
    setBusy(true)
    setError(null)
    try {
      const data = await api.graphQuery(query.trim())
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

  return (
    <div className="knowledge">
      <div className="knowledge-inner">
        <div className="page-head">
          <h1>Graph Explorer</h1>
          <p>
            Explore the connections Cypher has discovered between entities in your documents.
            Search for an equipment ID, location, or technical term.
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

        {/* Search Panel */}
        <div className="panel">
          <div className="panel-head">
            <IconGraph size={15} />
            <h2>Entity Search</h2>
            <div className="spacer" />
            <button
              className="icon-btn"
              title="Refresh Stats"
              onClick={refreshStats}
            >
              <IconRefresh size={15} />
            </button>
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
              onClick={search}
              disabled={busy || !query.trim()}
            >
              {busy ? 'Searching...' : 'Search Graph'}
            </button>
          </div>

          {error && (
            <div className="form-error">
              {error}
            </div>
          )}

          {/* Results Area */}
          {result && (
            <div className="graph-results">
              {result.nodes.length === 0 ? (
                <div className="empty-row">
                  No entities found matching "{query}".
                </div>
              ) : (
                <div className="graph-tables">
                  <div className="graph-col">
                    <h3>Related Entities ({result.nodes.length})</h3>
                    <div className="graph-list">
                      {result.nodes.map(n => (
                        <div className="graph-item" key={n.id}>
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
                              <span className="entity-name">{src}</span>
                              <span className="badge dim">{e.type}</span>
                              <span className="entity-name">{tgt}</span>
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
                          <div className="graph-item" key={idx}>
                            <span className="entity-name">{baseName(doc)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
