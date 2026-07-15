import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import Sidebar from './components/Sidebar'
import ChatView from './components/ChatView'
import KnowledgeView from './components/KnowledgeView'
import GraphView from './components/GraphView'

export default function App() {
  const [view, setView] = useState('chat') // 'chat' | 'knowledge' | 'graph'
  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [health, setHealth] = useState(null)

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
  }

  const handleSelectSession = (id) => {
    setActiveSessionId(id)
    setView('chat')
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
      <Sidebar
        view={view}
        onChangeView={setView}
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
      </main>
    </div>
  )
}
