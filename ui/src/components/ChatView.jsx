import { useEffect, useRef, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import { api, baseName } from '../api'
import {
  LogoMark, IconSend, IconStop, IconChevron, IconFile,
  IconExternal, IconQuote, IconUpload, IconCheckCircle, IconAlertCircle, IconX,
} from '../icons'

const SUGGESTIONS = [
  'Summarize the latest maintenance reports',
  'Which equipment has recorded failures?',
  'What safety regulations apply to our boilers?',
  'List all inspection procedures',
]

const CONF_CLASS = { High: 'ok', Medium: 'warn', Low: 'err' }

// ─── Supported extensions (mirrors backend Dispatcher) ────────────────────
const SUPPORTED_EXTS = new Set([
  'pdf','png','jpg','jpeg','tiff','bmp',
  'mp4','mkv','avi','mov',
  'mp3','wav','m4a','flac',
  'xlsx','xls','csv',
  'docx','doc','pptx','ppt','odt','html','txt',
  'eml','msg','zip',
])

function extOf(name) { return (name.split('.').pop() || '').toLowerCase() }
function isSupported(f) { return SUPPORTED_EXTS.has(extOf(f.name)) }

// ─── Sub-components ────────────────────────────────────────────────────────

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
      <span /><span /><span />
    </div>
  )
}

function Message({ msg }) {
  const roleClass = msg.error ? 'assistant error' : msg.role
  const isAssistant = msg.role === 'assistant' && !msg.error
  const waiting = isAssistant && msg.streaming && !msg.content
  return (
    <div className={`msg ${roleClass}`}>
      <div className="msg-meta">
        <span className="msg-author">{msg.role === 'user' ? 'You' : 'Cypher'}</span>
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

// ─── Upload status pill ────────────────────────────────────────────────────

function UploadPill({ item, onRemove }) {
  const done       = item.status === 'completed' || item.status === 'zip_extracted'
  const fail       = item.status === 'failed'    || item.status === 'rejected'
  const processing = item.status === 'processing'
  const busy       = item.status === 'uploading'

  // Status tag text
  const tag = busy || processing ? null
    : done  ? (item.status === 'zip_extracted' ? `${item.queued ?? ''} extracted` : 'done ✓')
    : (item.reason || item.error || item.status)

  // Extra class for processing state (amber pulse)
  const stateClass = busy || processing ? 'busy' : done ? 'done' : 'fail'

  return (
    <div
      className={`upload-pill ${stateClass}`}
      title={item.reason || item.error || item.file}
    >
      {busy || processing ? (
        <span className="upload-spinner" />
      ) : done ? (
        <IconCheckCircle size={13} />
      ) : (
        <IconAlertCircle size={13} />
      )}
      <span className="upload-pill-name">{item.file}</span>
      {tag && <span className="upload-pill-tag">{tag}</span>}
      {!busy && !processing && (
        <button className="upload-pill-remove" onClick={() => onRemove(item.file)} title="Dismiss">
          <IconX size={11} />
        </button>
      )}
    </div>
  )
}

// ─── Drop zone overlay ─────────────────────────────────────────────────────

function DropOverlay() {
  return (
    <div className="drop-overlay">
      <IconUpload size={38} />
      <span>Drop files to upload & ingest</span>
    </div>
  )
}

// ─── Main ChatView ─────────────────────────────────────────────────────────

export default function ChatView({ sessionId, onSessionCreated }) {
  const [messages, setMessages]       = useState([])
  const [input, setInput]             = useState('')
  const [busy, setBusy]               = useState(false)
  const [dragOver, setDragOver]       = useState(false)
  const [uploadItems, setUploadItems] = useState([])   // {file, status, reason?}
  const [uploading, setUploading]     = useState(false)

  const threadRef   = useRef(null)
  const textareaRef = useRef(null)
  const abortRef    = useRef(null)
  const skipLoadRef = useRef(null)
  const fileInputRef = useRef(null)
  const dragCounter = useRef(0)   // track nested drag-enter/leave

  // ── Session history load ─────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    if (!sessionId) { setMessages([]); return }
    if (sessionId === skipLoadRef.current) { skipLoadRef.current = null; return }
    api.sessionHistory(sessionId)
      .then((data) => {
        if (!cancelled)
          setMessages(data.messages.map((m) => ({ role: m.role, content: m.content, sources: m.sources })))
      })
      .catch(() => { if (!cancelled) setMessages([]) })
    return () => { cancelled = true }
  }, [sessionId])

  // ── Poll ingestion status for queued pills ──────────────────────────────
  useEffect(() => {
    // Check if any pill is still 'queued' or 'processing' — only then poll.
    const pending = uploadItems.filter(
      (i) => i.status === 'queued' || i.status === 'processing'
    )
    if (pending.length === 0) return

    // Build a Set of filenames we're waiting on
    const waitingFor = new Set(pending.map((i) => i.file))

    const intervalId = setInterval(async () => {
      try {
        const data = await api.documents()
        const docs = data.documents ?? []
        // Build a map: basename(file_path) → status
        const statusMap = {}
        for (const d of docs) {
          const name = d.file_path.split(/[\\/]/).pop()
          statusMap[name] = d.status
        }

        setUploadItems((prev) => {
          let changed = false
          const next = prev.map((item) => {
            if (!waitingFor.has(item.file)) return item
            const srvStatus = statusMap[item.file]
            if (!srvStatus) return item
            if (srvStatus === 'completed' || srvStatus === 'failed') {
              changed = true
              return { ...item, status: srvStatus }
            }
            if (srvStatus === 'processing' && item.status !== 'processing') {
              changed = true
              return { ...item, status: 'processing' }
            }
            return item
          })
          return changed ? next : prev
        })
      } catch {
        // silently ignore polling errors
      }
    }, 2000)   // poll every 2 s

    return () => clearInterval(intervalId)
  }, [uploadItems])

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

  // ── Chat send ────────────────────────────────────────────────────────────
  const send = async (text) => {
    const question = (text ?? input).trim()
    if (!question || busy) return

    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: question },
      { role: 'assistant', content: '', streaming: true },
    ])
    setBusy(true)

    const patchLast = (patch) =>
      setMessages((prev) => {
        const next = [...prev]
        const last = next[next.length - 1]
        if (last && last.role === 'assistant')
          next[next.length - 1] = typeof patch === 'function' ? patch(last) : { ...last, ...patch }
        return next
      })

    const controller = new AbortController()
    abortRef.current = controller

    try {
      await api.askStream(question, sessionId, {
        signal: controller.signal,
        onSession: (sid) => {
          if (!sessionId && sid) { skipLoadRef.current = sid; onSessionCreated(sid) }
        },
        onToken: (text) => patchLast((last) => ({ ...last, content: last.content + text })),
        onDone: (ev) => patchLast({ content: ev.answer, sources: ev.sources, confidence: ev.confidence, streaming: false }),
      })
    } catch (err) {
      if (err.name === 'AbortError') {
        patchLast((last) => ({
          ...last, streaming: false,
          content: last.content ? `${last.content}\n\n_(stopped)_` : '_(stopped before any output)_',
        }))
      } else {
        patchLast({ error: true, streaming: false, content: `Request failed: ${err.message}` })
      }
    } finally {
      abortRef.current = null
      setBusy(false)
    }
  }

  const stop = () => abortRef.current?.abort()

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  // ── File upload logic ────────────────────────────────────────────────────
  const uploadFiles = useCallback(async (files) => {
    const fileArr = Array.from(files)
    const supported = fileArr.filter(isSupported)
    const rejected  = fileArr.filter((f) => !isSupported(f))

    // Add pending pills immediately
    const pending = supported.map((f) => ({ file: f.name, status: 'uploading' }))
    const rejectedItems = rejected.map((f) => ({
      file: f.name, status: 'rejected', error: `Unsupported type (.${extOf(f.name)})`,
    }))
    setUploadItems((prev) => [...prev, ...pending, ...rejectedItems])

    if (!supported.length) return

    setUploading(true)
    try {
      const result = await api.uploadFiles(supported)
      // Server returned results — map by original filename
      setUploadItems((prev) => {
        const resultMap = {}
        for (const r of result.results ?? []) resultMap[r.file] = r
        return prev.map((item) => {
          if (item.status !== 'uploading') return item
          const srv = resultMap[item.file]
          // If server has a result for this file, use it; otherwise mark queued
          return srv ? { ...item, ...srv } : { ...item, status: 'queued' }
        })
      })
    } catch (err) {
      // HTTP-level failure (503, network error, etc.) — mark all pending as failed
      const detail = err.message || 'Upload failed'
      setUploadItems((prev) =>
        prev.map((item) =>
          item.status === 'uploading'
            ? { ...item, status: 'failed', reason: detail }
            : item
        )
      )
    } finally {
      setUploading(false)
    }
  }, [])

  // ── Drag-and-drop handlers ───────────────────────────────────────────────
  const onDragEnter = (e) => {
    e.preventDefault()
    dragCounter.current++
    if (e.dataTransfer.types.includes('Files')) setDragOver(true)
  }
  const onDragLeave = (e) => {
    e.preventDefault()
    dragCounter.current--
    if (dragCounter.current === 0) setDragOver(false)
  }
  const onDragOver = (e) => { e.preventDefault() }
  const onDrop = (e) => {
    e.preventDefault()
    dragCounter.current = 0
    setDragOver(false)
    const files = e.dataTransfer.files
    if (files.length) uploadFiles(files)
  }

  const onFileInputChange = (e) => {
    if (e.target.files?.length) uploadFiles(e.target.files)
    e.target.value = ''   // reset so same file can be re-uploaded
  }

  const removeUploadPill = (fileName) =>
    setUploadItems((prev) => prev.filter((i) => i.file !== fileName))

  const empty = messages.length === 0 && !busy

  return (
    <div
      className="chat"
      onDragEnter={onDragEnter}
      onDragLeave={onDragLeave}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      {dragOver && <DropOverlay />}

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
          {/* Hero upload zone */}
          <button
            className="hero-upload-btn"
            onClick={() => fileInputRef.current?.click()}
            title="Upload documents to ingest"
          >
            <IconUpload size={16} />
            Upload documents
          </button>
        </div>
      ) : (
        <div className="thread" ref={threadRef}>
          <div className="thread-inner">
            {messages.map((m, i) => <Message key={i} msg={m} />)}
          </div>
        </div>
      )}

      {/* Upload result pills */}
      {uploadItems.length > 0 && (
        <div className="upload-pills-row">
          {uploadItems.map((item) => (
            <UploadPill key={item.file} item={item} onRemove={removeUploadPill} />
          ))}
          {!uploading && (
            <button
              className="upload-pills-clear"
              onClick={() => setUploadItems([])}
              title="Clear all"
            >
              Clear
            </button>
          )}
        </div>
      )}

      <div className="composer-wrap">
        <div className="composer">
          {/* Upload button inside composer */}
          <button
            className="upload-btn"
            onClick={() => fileInputRef.current?.click()}
            title="Upload files to ingest"
            disabled={uploading}
          >
            {uploading
              ? <span className="upload-spinner" />
              : <IconUpload size={16} />
            }
          </button>

          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            placeholder="Ask about your documents, or drag & drop files to upload..."
            onChange={(e) => { setInput(e.target.value); autosize() }}
            onKeyDown={onKeyDown}
            disabled={busy}
          />

          {busy ? (
            <button className="send-btn stop-btn" onClick={stop} title="Stop generating">
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
          Enter to send · Shift+Enter for new line · Drag &amp; drop files to upload and ingest
        </div>
      </div>

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={[...SUPPORTED_EXTS].map((e) => `.${e}`).join(',')}
        style={{ display: 'none' }}
        onChange={onFileInputChange}
      />
    </div>
  )
}
