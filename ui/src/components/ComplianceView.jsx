import { useCallback, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { api } from '../api'

export default function ComplianceView() {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async (analyze = false) => {
    setBusy(true)
    setError(null)
    try {
      const res = await api.complianceGaps(analyze)
      setData(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    load(false)
  }, [load])

  if (!data && busy) {
    return (
      <div className="knowledge">
        <div className="knowledge-inner">
          <div className="page-head">
            <h1>Compliance Intelligence</h1>
            <p>Scanning regulations and mapping evidence...</p>
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="knowledge">
        <div className="knowledge-inner">
          <div className="form-error">Error loading compliance data: {error}</div>
        </div>
      </div>
    )
  }

  if (!data) return null

  const summary = data.summary || {}
  const regs = data.regulations || []

  return (
    <div className="knowledge">
      <div className="knowledge-inner">
        <div className="page-head">
          <h1>Compliance Intelligence</h1>
          <p>
            Auto-mapping regulatory requirements against current procedures, equipment states,
            and inspection records to detect compliance gaps.
          </p>
        </div>

        <div className="compliance-summary">
          <div className="comp-stat total">
            <div className="val">{summary.total || 0}</div>
            <div className="lbl">Total Regulations</div>
          </div>
          <div className="comp-stat covered">
            <div className="val">{summary.covered || 0}</div>
            <div className="lbl">Fully Covered</div>
          </div>
          <div className="comp-stat partial">
            <div className="val">{summary.partial || 0}</div>
            <div className="lbl">Partial Coverage</div>
          </div>
          <div className="comp-stat gap">
            <div className="val">{summary.gaps || 0}</div>
            <div className="lbl">Candidate Gaps</div>
          </div>
        </div>

        <div className="panel" style={{ padding: '18px', marginBottom: '24px', display: 'flex', gap: '16px', alignItems: 'center' }}>
          <div>
            <strong>LLM Audit Analysis</strong>
            <p style={{ margin: '4px 0 0', fontSize: '13px', color: 'var(--text-dim)' }}>
              Run a deep LLM pass over the findings to generate an auditor-style narrative report and concrete recommendations.
            </p>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: '10px' }}>
            <button
              className="btn-secondary"
              onClick={() => window.open('/api/compliance/evidence?analyze=false', '_blank')}
              title="Open a printable audit evidence package (Print to PDF)"
            >
              Export Evidence Pack
            </button>
            <button
              className="btn-primary"
              onClick={() => load(true)}
              disabled={busy}
            >
              {busy ? 'Analyzing...' : 'Run Audit Narrative'}
            </button>
          </div>
        </div>

        {data.narrative && (
          <div className="audit-box">
            <h3>Audit Report</h3>
            <div className="audit-content">
              <ReactMarkdown>{data.narrative}</ReactMarkdown>
            </div>
          </div>
        )}

        <div>
          <h2 style={{ fontSize: '15px', fontWeight: 650, margin: '0 0 16px 0', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-dim)' }}>
            Regulatory Mapping
          </h2>
          {regs.length === 0 && (
            <div className="empty-row" style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
              No regulations found in the knowledge graph.
            </div>
          )}
          {regs.map((r, i) => (
            <div key={i} className={`reg-card ${r.status}`}>
              <div className="reg-head">
                <h3 className="reg-name">{r.name}</h3>
                <span className={`badge ${r.status}`}>{r.status}</span>
              </div>
              {r.description && <p className="reg-desc">{r.description}</p>}
              
              <div className="reg-meta" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div>
                  <strong style={{ color: 'var(--text)' }}>Procedures:</strong> {r.linked_procedures?.length > 0 ? r.linked_procedures.join(', ') : <span style={{ color: 'var(--text-faint)' }}>None linked</span>}
                </div>
                <div>
                  <strong style={{ color: 'var(--text)' }}>Equipment:</strong> {r.linked_equipment?.length > 0 ? r.linked_equipment.join(', ') : <span style={{ color: 'var(--text-faint)' }}>None linked</span>}
                </div>
                <div>
                  <strong style={{ color: 'var(--text)' }}>Evidence Docs:</strong> {r.evidence_documents?.length > 0 ? r.evidence_documents.join(', ') : <span style={{ color: 'var(--text-faint)' }}>None linked</span>}
                </div>
              </div>

              {r.gap_reason && (
                <div className={`reg-gap-reason ${r.status}`}>
                  {r.gap_reason}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
