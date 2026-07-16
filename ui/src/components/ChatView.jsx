import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { api, baseName } from '../api'
import { LogoMark, IconSend, IconChevron, IconFile } from '../icons'

const SUGGESTIONS = [
  'Summarize the latest maintenance reports',
  'Which equipment has recorded failures?',
  'What safety regulations apply to our boilers?',
  'List all inspection procedures',
]

function Sources({ sources }) {
  const [open, setOpen] = useState(false)
  if (!sources || sources.length === 0) return null

  const citedCount = sources.filter(s => s.cited).length
  const label = citedCount > 0 ? `${citedCount} cited source${citedCount > 1 ? 's' : ''} (${sources.length} retrieved)` : `${sources.length} source${sources.length > 1 ? 's' : ''} retrieved`

  return (
    <div className="sources">
      <button className="sources-toggle" onClick={() => setOpen(!open)}>
        <IconFile size={14} />
        {label}
        <span className={`chev ${open ? 'open' : ''}`}>
          <IconChevron size={14} />
        </span>
      </button>
      {open && (
        <div className="sources-list">
          {sources.map((s, idx) => (
            <div className={`source-item ${s.cited ? 'cited' : ''}`} key={idx}>
              <span className="source-num">[{idx + 1}]</span>
              <div className="source-info">
                <div className="source-name">
                  {baseName(s.file_path)}
                  {s.cited && <span className="badge ok" style={{marginLeft: '8px'}}>Cited</span>}
                </div>
                <div className="source-path">{s.file_path}</div>
                {s.chunk_text && <div className="source-preview">{s.chunk_text}</div>}
              </div>
              {typeof s.relevance_score === 'number' && (
                <span className="source-score">{s.relevance_score.toFixed(3)}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Message({ msg }) {
  const roleClass = msg.error ? 'assistant error' : msg.role
  return (
    <div className={`msg ${roleClass}`}>
      <div className="msg-meta">
        <span className="msg-author">{msg.role === 'user' ? 'You' : 'Cypher'}</span>
      </div>
      <div className="msg-body">
        {msg.role === 'assistant' && !msg.error ? (
          <ReactMarkdown>{msg.content}</ReactMarkdown>
        ) : (
          msg.content
        )}
      </div>
      {msg.role === 'assistant' && <Sources sources={msg.sources} />}
    </div>
  )
}

export default function ChatView({ sessionId, onSessionCreated }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const threadRef = useRef(null)
  const textareaRef = useRef(null)

  // Load history when switching sessions
  useEffect(() => {
    let cancelled = false
    if (!sessionId) {
      setMessages([])
      return
    }
    api
      .sessionHistory(sessionId)
      .then((data) => {
        if (!cancelled) {
          setMessages(
            data.messages.map((m) => ({ role: m.role, content: m.content }))
          )
        }
      })
      .catch(() => {
        if (!cancelled) setMessages([])
      })
    return () => {
      cancelled = true
    }
  }, [sessionId])

  // Keep the thread pinned to the bottom
  useEffect(() => {
    const el = threadRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, busy])

  const autosize = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`
  }

  const send = async (text) => {
    const question = (text ?? input).trim()
    if (!question || busy) return

    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    setMessages((prev) => [...prev, { role: 'user', content: question }])
    setBusy(true)

    try {
      const res = await api.ask(question, sessionId)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: res.answer, sources: res.sources },
      ])
      if (!sessionId && res.session_id) onSessionCreated(res.session_id)
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', error: true, content: `Request failed: ${err.message}` },
      ])
    } finally {
      setBusy(false)
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const empty = messages.length === 0 && !busy

  return (
    <div className="chat">
      {empty ? (
        <div className="hero">
          <LogoMark size={54} />
          <h1 className="hero-title">
            Ask your <span className="accent">company brain</span>
          </h1>
          <p className="hero-sub">
            Cypher has read your tracked documents, connected the facts, and is
            ready to answer with citations.
          </p>
          <div className="hero-suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="suggestion" onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="thread" ref={threadRef}>
          <div className="thread-inner">
            {messages.map((m, i) => (
              <Message key={i} msg={m} />
            ))}
            {busy && (
              <div className="msg assistant">
                <div className="msg-meta">
                  <span className="msg-author">Cypher</span>
                </div>
                <div className="typing">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="composer-wrap">
        <div className="composer">
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            placeholder="Ask about your documents, equipment, procedures..."
            onChange={(e) => {
              setInput(e.target.value)
              autosize()
            }}
            onKeyDown={onKeyDown}
            disabled={busy}
          />
          <button
            className="send-btn"
            onClick={() => send()}
            disabled={busy || !input.trim()}
            title="Send"
          >
            <IconSend size={17} />
          </button>
        </div>
        <div className="composer-hint">
          Enter to send · Shift+Enter for a new line · Answers cite tracked documents
        </div>
      </div>
    </div>
  )
}
