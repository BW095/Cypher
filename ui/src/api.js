// api.js — Thin client for the Cypher FastAPI backend.
// All calls go through the Vite dev proxy (/api → localhost:8000).

async function handle(res) {
  if (!res.ok) {
    let detail
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      detail = res.statusText
    }
    throw new Error(detail || `Request failed (${res.status})`)
  }
  return res.json()
}

const post = (url, body) =>
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(handle)

const del = (url) => fetch(url, { method: 'DELETE' }).then(handle)

export const api = {
  // Health
  health: () => fetch('/api/health').then(handle),

  // Chat
  ask: (user_message, sessionId) =>
    post('/api/chat', { user_message, session_id: sessionId || null }),
  sessions: () => fetch('/api/chat/sessions').then(handle),
  sessionHistory: (id) =>
    fetch(`/api/chat/sessions/${encodeURIComponent(id)}`).then(handle),
  deleteSession: (id) => del(`/api/chat/sessions/${encodeURIComponent(id)}`),

  // Ingestion & Folders
  status: () => fetch('/api/ingest/status').then(handle),
  folders: () => fetch('/api/ingest/folders').then(handle),
  addFolder: (folderPath) => post('/api/ingest/start', { folder_path: folderPath }),
  removeFolder: (folderPath) => post('/api/ingest/stop', { folder_path: folderPath }),

  // Documents
  documents: () => fetch('/api/documents').then(handle),
  // URL to open/download an original source file (used as an <a href>)
  documentUrl: (filePath, download = false) =>
    `/api/documents/open?path=${encodeURIComponent(filePath)}${download ? '&download=true' : ''}`,

  // Graph
  graphQuery: (entityName, depth = 2) =>
    post('/api/graph/query', { entity_name: entityName, depth }),
  graphStats: () => fetch('/api/graph/stats').then(handle),
  graphFull: (limit = 400) => fetch(`/api/graph/full?limit=${limit}`).then(handle),

  // Compliance
  complianceGaps: (analyze = false) =>
    fetch(`/api/compliance/gaps?analyze=${analyze}`).then(handle),
}

// Stable color per entity type — used across the graph visualization.
export const ENTITY_COLORS = {
  EQUIPMENT: '#e8a33d',
  COMPONENT: '#60a5fa',
  PROCESS_PARAMETER: '#4ade80',
  FAILURE: '#f87171',
  PROCEDURE: '#a78bfa',
  REGULATION: '#f472b6',
  PERSONNEL: '#22d3ee',
  MATERIAL: '#fbbf24',
  LOCATION: '#34d399',
  DATE: '#94a3b8',
  Unknown: '#5c6675',
}

export function entityColor(type) {
  return ENTITY_COLORS[type] || ENTITY_COLORS.Unknown
}

// "2026-07-11 20:15:03.123456" (SQLite) → friendly relative time
export function timeAgo(timestamp) {
  if (!timestamp) return ''
  const date = new Date(String(timestamp).replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return ''

  const seconds = Math.floor((Date.now() - date.getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  return date.toLocaleDateString()
}

// "C:\docs\reports\pump_manual.pdf" → "pump_manual.pdf"
export function baseName(path) {
  if (!path) return ''
  return String(path).split(/[\\/]/).pop()
}
