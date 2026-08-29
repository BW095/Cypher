import { useEffect, useState } from 'react'
import { timeAgo } from '../api'
import { folderSync, LocalFolderSync } from '../services/localFolderSync'
import {
  LogoMark,
  IconChat,
  IconDatabase,
  IconPlus,
  IconX,
  IconGraph,
  IconShield,
  IconEntangle,
} from '../icons'

function StatusChip({ label, ok }) {
  return (
    <span className="status-chip">
      <span className={`dot ${ok ? 'ok' : 'err'}`} />
      {label}
    </span>
  )
}

/* ── Folder Sync Widget ─────────────────────────────────────────────── */

function FolderSyncWidget() {
  const [state, setState] = useState({})
  const supported = LocalFolderSync.isSupported()

  useEffect(() => {
    const unsub = folderSync.subscribe(setState)
    // Try to reconnect a previously saved handle on mount
    folderSync.tryReconnect()
    return unsub
  }, [])

  if (!supported) {
    return (
      <div className="folder-sync-widget">
        <div className="folder-sync-unsupported">
          Folder sync requires Chrome or Edge
        </div>
      </div>
    )
  }

  const handleConnect = async () => {
    if (state.connected) {
      await folderSync.disconnect()
    } else if (state.folderName && !state.connected) {
      // Saved handle exists but permission needs re-granting
      const ok = await folderSync.requestPermission()
      if (!ok) await folderSync.connect()
    } else {
      await folderSync.connect()
    }
  }

  return (
    <div className="folder-sync-widget">
      <div className="folder-sync-label">Local Folder</div>

      {state.connected ? (
        <>
          <div className="folder-sync-connected">
            <span className="folder-sync-icon">📁</span>
            <span className="folder-sync-name" title={state.folderName}>
              {state.folderName}
            </span>
            <button
              className="folder-sync-disconnect"
              onClick={() => folderSync.disconnect()}
              title="Disconnect folder"
            >
              <IconX size={12} />
            </button>
          </div>

          <div className="folder-sync-status">
            {state.syncing ? (
              <span className="folder-sync-syncing">
                <span className="upload-spinner" />
                Syncing…
              </span>
            ) : (
              <span className="folder-sync-synced">
                {state.totalFiles} file{state.totalFiles !== 1 ? 's' : ''} tracked
                {state.lastSync && (
                  <span className="folder-sync-time">
                    · {timeAgo(state.lastSync.toISOString())}
                  </span>
                )}
              </span>
            )}
          </div>

          <button
            className="folder-sync-resync"
            onClick={() => folderSync.syncNow()}
            disabled={state.syncing}
          >
            Sync now
          </button>
        </>
      ) : (
        <>
          {state.folderName && (
            <div className="folder-sync-reconnect-hint">
              Previously connected to <strong>{state.folderName}</strong>
            </div>
          )}
          <button className="folder-sync-connect" onClick={handleConnect}>
            <span className="folder-sync-icon">📁</span>
            {state.folderName ? 'Reconnect Folder' : 'Connect Local Folder'}
          </button>
        </>
      )}

      {state.error && (
        <div className="folder-sync-error">{state.error}</div>
      )}
    </div>
  )
}

/* ── Sidebar ────────────────────────────────────────────────────────── */

export default function Sidebar({
  isOpen,
  onClose,
  view,
  onChangeView,
  sessions,
  activeSessionId,
  onNewChat,
  onSelectSession,
  onDeleteSession,
  health,
}) {
  const services = health?.services

  return (
    <>
      {isOpen && <div className="sidebar-backdrop" onClick={onClose} />}
      <aside className={`sidebar ${isOpen ? 'open' : ''}`}>
        <div className="brand">
          <LogoMark />
          <div>
            <div className="brand-name">CYPHER</div>
            <span className="brand-sub">Industrial AI Brain</span>
          </div>
        </div>

        <nav className="nav">
          <button
            className={`nav-item ${view === 'chat' ? 'active' : ''}`}
            onClick={() => onChangeView('chat')}
          >
            <IconChat />
            Chat
          </button>
          <button
            className={`nav-item ${view === 'knowledge' ? 'active' : ''}`}
            onClick={() => onChangeView('knowledge')}
          >
            <IconDatabase />
            Knowledge Base
          </button>
          <button
            className={`nav-item ${view === 'graph' ? 'active' : ''}`}
            onClick={() => onChangeView('graph')}
          >
            <IconGraph />
            Graph Explorer
          </button>
          <button
            className={`nav-item ${view === 'compliance' ? 'active' : ''}`}
            onClick={() => onChangeView('compliance')}
          >
            <IconShield />
            Compliance
          </button>
          <button
            className={`nav-item ${view === 'entanglement' ? 'active' : ''}`}
            onClick={() => onChangeView('entanglement')}
          >
            <IconEntangle />
            Entanglement
          </button>
        </nav>

        {/* ── Local Folder Sync ──────────────────────────────────── */}
        <FolderSyncWidget />

        <div className="sessions">
          <button className="new-chat" onClick={onNewChat}>
            <IconPlus size={16} />
            New chat
          </button>

          <div className="sessions-label">Recent</div>
          {sessions.length === 0 && (
            <div className="sessions-empty">No conversations yet.</div>
          )}
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`session-item ${s.id === activeSessionId ? 'active' : ''}`}
              role="button"
              tabIndex={0}
              onClick={() => onSelectSession(s.id)}
              onKeyDown={(e) => e.key === 'Enter' && onSelectSession(s.id)}
            >
              <span className="session-title">{s.title || 'Untitled'}</span>
              <span className="session-time">{timeAgo(s.last_message_at)}</span>
              <button
                className="session-delete"
                title="Delete conversation"
                onClick={(e) => {
                  e.stopPropagation()
                  onDeleteSession(s.id)
                }}
              >
                <IconX size={14} />
              </button>
            </div>
          ))}
        </div>

        <div className="status-footer">
          <div className="status-footer-label">System</div>
          {services ? (
            <div className="status-row">
              <StatusChip label="Vector DB" ok={services.qdrant === 'ok'} />
              <StatusChip label="Graph DB" ok={services.neo4j === 'ok'} />
              <StatusChip label="LLM" ok={services.llm?.startsWith('bedrock')} />
            </div>
          ) : (
            <div className="status-row">
              <StatusChip label="Backend offline" ok={false} />
            </div>
          )}
        </div>
      </aside>
    </>
  )
}
