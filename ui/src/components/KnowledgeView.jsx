import { useCallback, useEffect, useRef, useState } from 'react'
import { api, baseName, timeAgo } from '../api'
import { IconFolder, IconPlus, IconRefresh, IconTrash, IconFile } from '../icons'

const STATUS_BADGE = {
  completed: 'ok',
  processing: 'warn',
  pending: 'warn',
  failed: 'err',
  skipped: 'dim',
  unsupported: 'dim',
}

function StatusBadge({ status }) {
  return <span className={`badge ${STATUS_BADGE[status] || 'dim'}`}>{status}</span>
}

export default function KnowledgeView() {
  const [folders, setFolders] = useState([])
  const [documents, setDocuments] = useState([])
  const [summary, setSummary] = useState({})
  const [folderInput, setFolderInput] = useState('')
  const [adding, setAdding] = useState(false)
  const [notice, setNotice] = useState(null) // {kind: 'ok'|'error', text}
  const [refreshing, setRefreshing] = useState(false)
  const noticeTimer = useRef(null)

  const flash = (kind, text) => {
    clearTimeout(noticeTimer.current)
    setNotice({ kind, text })
    noticeTimer.current = setTimeout(() => setNotice(null), 6000)
  }

  const refresh = useCallback(async (spin = false) => {
    if (spin) setRefreshing(true)
    try {
      const [d, s] = await Promise.all([
        api.documents(),
        api.status(),
      ])
      
      setFolders(s.tracked_folders || [])
      setDocuments(d.documents || [])
      setSummary({
        total: s.total_documents,
        completed: s.completed,
        processing: s.processing,
        failed: s.failed
      })
    } catch {
      // Backend offline — leave current data in place
    } finally {
      if (spin) setRefreshing(false)
    }
  }, [])

  // Initial load + poll while anything is still processing
  useEffect(() => {
    const initial = setTimeout(refresh, 0)
    const timer = setInterval(refresh, 5000)
    return () => {
      clearTimeout(initial)
      clearInterval(timer)
      clearTimeout(noticeTimer.current)
    }
  }, [refresh])

  const addFolder = async () => {
    const path = folderInput.trim()
    if (!path || adding) return
    setAdding(true)
    try {
      await api.addFolder(path)
      setFolderInput('')
      flash('ok', 'Folder is now tracked. Existing files are being ingested in the background.')
      refresh()
    } catch (err) {
      flash('error', err.message)
    } finally {
      setAdding(false)
    }
  }

  const removeFolder = async (path) => {
    if (!window.confirm(
      `Remove "${path}" from tracking and delete all knowledge ingested from it?`
    )) return
    try {
      const res = await api.removeFolder(path)
      flash('ok', `Removed folder and ${res.documents_removed ?? 0} document(s).`)
      refresh()
    } catch (err) {
      flash('error', err.message)
    }
  }

  const processing = summary.processing || 0

  return (
    <div className="knowledge">
      <div className="knowledge-inner">
        <div className="page-head">
          <h1>Knowledge Base</h1>
          <p>
            Track directories and Cypher will ingest every document inside them —
            text, tables, images, audio and video — into its searchable brain.
          </p>
        </div>

        {/* Tracked directories */}
        <div className="panel">
          <div className="panel-head">
            <IconFolder size={15} />
            <h2>Tracked Directories</h2>
          </div>

          <div className="add-folder">
            <input
              value={folderInput}
              placeholder={'Absolute path, e.g. C:\\Users\\name\\Documents\\Reports'}
              onChange={(e) => setFolderInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addFolder()}
              spellCheck={false}
            />
            <button
              className="btn-primary"
              onClick={addFolder}
              disabled={adding || !folderInput.trim()}
            >
              <IconPlus size={15} />
              {adding ? 'Adding...' : 'Track folder'}
            </button>
          </div>

          {notice && (
            <div className={notice.kind === 'ok' ? 'form-ok' : 'form-error'}>
              {notice.text}
            </div>
          )}

          <div className="folder-list">
            {folders.length === 0 ? (
              <div className="empty-row">
                No directories tracked yet. Add one above to start building the
                knowledge base.
              </div>
            ) : (
              folders.map((f) => (
                <div className="folder-row" key={f.path}>
                  <IconFolder size={15} />
                  <span className="folder-path" title={f.path}>
                    {f.path}
                  </span>
                  <span className={`badge ${f.is_active ? 'ok' : 'err'}`}>
                    {f.is_active ? 'watching' : 'stopped'}
                  </span>
                  <button
                    className="icon-btn"
                    title="Stop tracking"
                    onClick={() => removeFolder(f.path)}
                  >
                    <IconTrash size={15} />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Ingestion stats */}
        <div className="stats">
          <div className="stat ok">
            <div className="stat-value">{summary.completed || 0}</div>
            <div className="stat-label">Indexed</div>
          </div>
          <div className="stat warn">
            <div className="stat-value">{processing}</div>
            <div className="stat-label">Processing</div>
          </div>
          <div className="stat err">
            <div className="stat-value">{summary.failed || 0}</div>
            <div className="stat-label">Failed</div>
          </div>
          <div className="stat">
            <div className="stat-value">{summary.total || 0}</div>
            <div className="stat-label">Total files</div>
          </div>
        </div>

        {/* Documents */}
        <div className="panel">
          <div className="panel-head">
            <IconFile size={15} />
            <h2>Documents</h2>
            <div className="spacer" />
            <button
              className={`icon-btn ${refreshing ? 'spin' : ''}`}
              title="Refresh"
              onClick={() => refresh(true)}
            >
              <IconRefresh size={15} />
            </button>
          </div>

          {documents.length === 0 ? (
            <div className="empty-row">
              Nothing ingested yet. Documents appear here as soon as a tracked
              directory contains supported files.
            </div>
          ) : (
            <table className="doc-table">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.file_path}>
                    <td>
                      <div className="doc-name">{baseName(doc.file_path)}</div>
                      <div className="doc-path">{doc.file_path}</div>
                    </td>
                    <td className="doc-type">{doc.file_type || '—'}</td>
                    <td>
                      <StatusBadge status={doc.status} />
                    </td>
                    <td className="doc-chunks">{timeAgo(doc.ingested_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
