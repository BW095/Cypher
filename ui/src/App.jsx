import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import Sidebar from './components/Sidebar'
import ChatView from './components/ChatView'
import KnowledgeView from './components/KnowledgeView'
import GraphView from './components/GraphView'
import ComplianceView from './components/ComplianceView'
import { IconMenu, LogoMark } from './icons'

export default function App() {
  const [view, setView] = useState('chat') // 'chat' | 'knowledge' | 'graph' | 'compliance'
  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [health, setHealth] = useState(null)
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)

  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await api.sessions())
    } catch {
      // Backend not reachable yet — sidebar just stays empty
    }
  }, [])

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.health())
    } catch {
      setHealth(null) // Renders as "offline"
    }
  }, [])

  useEffect(() => {
    const initial = setTimeout(() => {
      refreshSessions()
      refreshHealth()
    }, 0)
    const timer = setInterval(refreshHealth, 15000)
    return () => {
      clearTimeout(initial)
      clearInterval(timer)
    }
  }, [refreshSessions, refreshHealth])

  const handleNewChat = () => {
    setActiveSessionId(null)
    setView('chat')
    setIsSidebarOpen(false)
  }

  const handleSelectSession = (id) => {
    setActiveSessionId(id)
    setView('chat')
    setIsSidebarOpen(false)
  }

  const handleDeleteSession = async (id) => {
    try {
      await api.deleteSession(id)
    } finally {
      if (id === activeSessionId) setActiveSessionId(null)
      refreshSessions()
    }
  }

  return (
    <div className="app">
      <div className="mobile-header">
        <div className="brand" style={{ padding: 0 }}>
          <LogoMark size={20} />
          <div>
            <div className="brand-name" style={{ fontSize: '15px' }}>CYPHER</div>
          </div>
        </div>
        <button className="mobile-menu-btn" onClick={() => setIsSidebarOpen(true)}>
          <IconMenu size={24} />
        </button>
      </div>
      <Sidebar
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        view={view}
        onChangeView={(v) => { setView(v); setIsSidebarOpen(false); }}
        sessions={sessions}
        activeSessionId={activeSessionId}
        onNewChat={handleNewChat}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
        health={health}
      />
      <main className="main">
        {view === 'chat' && (
          <ChatView
            sessionId={activeSessionId}
            onSessionCreated={(id) => {
              setActiveSessionId(id)
              refreshSessions()
            }}
          />
        )}
        {view === 'knowledge' && <KnowledgeView />}
        {view === 'graph' && <GraphView />}
        {view === 'compliance' && <ComplianceView />}
      </main>
    </div>
  )
}
