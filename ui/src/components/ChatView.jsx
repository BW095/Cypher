import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { api, baseName } from '../api'
import { LogoMark, IconSend, IconChevron, IconFile, IconExternal, IconQuote } from '../icons'

const SUGGESTIONS = [
  'Summarize the latest maintenance reports',
  'Which equipment has recorded failures?',
  'What safety regulations apply to our boilers?',
  'List all inspection procedures',
]

const CONF_CLASS = { High: 'ok', Medium: 'warn', Low: 'err' }

function ConfidenceBadge({ confidence }) {
  if (!confidence || !confidence.label) return null
  const cls = CONF_CLASS[confidence.label] || 'dim'
  const pct = Math.round((confidence.score || 0) * 100)
  const title = (confidence.reasons || []).join(' · ')
  return (
    <span className={`conf-badge ${cls}`} title={title}>
      <span className="conf-dot" />
      {confidence.label} confidence · {pct}%
    </span>
  )
}

function SourceRow({ s, num }) {
  const name = baseName(s.file_path)
  return (
    <a
      className={`source-item ${s.cited ? 'cited' : ''}`}
      href={api.documentUrl(s.file_path)}
      target="_blank"
      rel="noreferrer"
      title={`Open ${name}`}
    >
      <span className="source-num">{s.cited ? <IconQuote size={13} /> : `[${num}]`}</span>
      <div className="source-info">
        <div className="source-name">
          {name}
          {s.cited && <span className="cited-tag">cited</span>}
        </div>
        <div className="source-path">{s.file_path}</div>
        {s.chunk_text && <div className="source-preview">{s.chunk_text}</div>}
      </div>
      <div className="source-right">
        {typeof s.relevance_score === 'number' && s.relevance_score > 0 && (
          <span className="source-score">{s.relevance_score.toFixed(2)}</span>
        )}
        <IconExternal size={14} />
      </div>
    </a>
  )
}

function Sources({ sources }) {
  const [open, setOpen] = useState(false)
  if (!sources || sources.length === 0) return null

  // Sources the model actually cited come first and drive the summary label.
  const cited = sources.filter((s) => s.cited)
  const others = sources.filter((s) => !s.cited)
  const ordered = [...cited, ...others]
  const label =
    cited.length > 0
      ? `${cited.length} cited · ${sources.length} retrieved`
      : `${sources.length} source${sources.length > 1 ? 's' : ''} retrieved`

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
          {ordered.map((s, idx) => (
            <SourceRow key={idx} s={s} num={idx + 1} />
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
        {msg.role === 'assistant' && !msg.error && (
          <ConfidenceBadge confidence={msg.confidence} />
        )}
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
            data.messages.map((m) => ({
              role: m.role,
              content: m.content,
              sources: m.sources,
            }))
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
        {
          role: 'assistant',
          content: res.answer,
          sources: res.sources,
          confidence: res.confidence,
        },
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
