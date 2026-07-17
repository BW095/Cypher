import { timeAgo } from '../api'
import {
  LogoMark,
  IconChat,
  IconDatabase,
  IconPlus,
  IconX,
  IconGraph,
  IconShield,
} from '../icons'

function StatusChip({ label, ok }) {
  return (
    <span className="status-chip">
      <span className={`dot ${ok ? 'ok' : 'err'}`} />
      {label}
    </span>
  )
}

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
      </nav>

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
            <StatusChip label="LLM" ok={services.llm === 'configured'} />
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
