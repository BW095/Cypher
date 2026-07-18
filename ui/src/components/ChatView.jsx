import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { api, baseName } from '../api'
import { LogoMark, IconSend, IconStop, IconChevron, IconFile, IconExternal, IconQuote } from '../icons'

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

function TypingDots() {
  return (
    <div className="typing">
      <span />
      <span />
      <span />
    </div>
  )
}

function Message({ msg }) {
  const roleClass = msg.error ? 'assistant error' : msg.role
  const isAssistant = msg.role === 'assistant' && !msg.error
  // A streaming assistant bubble with no text yet shows the typing indicator.
  const waiting = isAssistant && msg.streaming && !msg.content
  return (
    <div className={`msg ${roleClass}`}>
      <div className="msg-meta">
        <span className="msg-author">{msg.role === 'user' ? 'You' : 'Cypher'}</span>
        {isAssistant && !msg.streaming && <ConfidenceBadge confidence={msg.confidence} />}
      </div>
      <div className="msg-body">
        {waiting ? (
          <TypingDots />
        ) : isAssistant ? (
          <>
            <ReactMarkdown>{msg.content}</ReactMarkdown>
            {msg.streaming && <span className="stream-cursor" />}
          </>
        ) : (
          msg.content
        )}
      </div>
      {isAssistant && !msg.streaming && <Sources sources={msg.sources} />}
    </div>
  )
}

export default function ChatView({ sessionId, onSessionCreated }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const threadRef = useRef(null)
  const textareaRef = useRef(null)
  const abortRef = useRef(null)  // AbortController for the in-flight stream

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
    // Append the user turn plus an empty, streaming assistant bubble.
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: question },
      { role: 'assistant', content: '', streaming: true },
    ])
    setBusy(true)

    // Helper: update the last message (the streaming assistant bubble) in place.
    const patchLast = (patch) =>
      setMessages((prev) => {
        const next = [...prev]
        const last = next[next.length - 1]
        if (last && last.role === 'assistant') {
          next[next.length - 1] =
            typeof patch === 'function' ? patch(last) : { ...last, ...patch }
        }
        return next
      })

    const controller = new AbortController()
    abortRef.current = controller

    try {
      await api.askStream(question, sessionId, {
        signal: controller.signal,
        onSession: (sid) => {
          if (!sessionId && sid) onSessionCreated(sid)
        },
        onToken: (text) =>
          patchLast((last) => ({ ...last, content: last.content + text })),
        onDone: (ev) =>
          patchLast({
            content: ev.answer,
            sources: ev.sources,
            confidence: ev.confidence,
            streaming: false,
          }),
      })
    } catch (err) {
      if (err.name === 'AbortError') {
        // User pressed Stop — keep whatever streamed so far, mark a note.
        patchLast((last) => ({
          ...last,
          streaming: false,
          content: last.content
            ? `${last.content}\n\n_(stopped)_`
            : '_(stopped before any output)_',
        }))
      } else {
        patchLast({
          error: true,
          streaming: false,
          content: `Request failed: ${err.message}`,
        })
      }
    } finally {
      abortRef.current = null
      setBusy(false)
    }
  }

  const stop = () => abortRef.current?.abort()

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
          {busy ? (
            <button
              className="send-btn stop-btn"
              onClick={stop}
              title="Stop generating"
            >
              <IconStop size={16} />
            </button>
          ) : (
            <button
              className="send-btn"
              onClick={() => send()}
              disabled={!input.trim()}
              title="Send"
            >
              <IconSend size={17} />
            </button>
          )}
        </div>
        <div className="composer-hint">
          Enter to send · Shift+Enter for a new line · Answers cite tracked documents
        </div>
      </div>
    </div>
  )
}
