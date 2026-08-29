/**
 * LocalFolderSync — Browser File System Access API integration.
 *
 * Lets the user pick a local folder from the browser, then continuously
 * syncs its contents with the Cypher backend (like an AI IDE does).
 *
 * Flow:
 *   1. User clicks "Connect Local Folder" → showDirectoryPicker()
 *   2. We scan all files, hash them with SubtleCrypto SHA-256
 *   3. POST /api/ingest/file-hashes to find which files need uploading
 *   4. Upload new/changed files → POST /api/ingest/upload
 *   5. Delete removed files → DELETE /api/ingest/file
 *   6. Poll every POLL_INTERVAL_MS for changes
 *
 * The FileSystemDirectoryHandle is persisted in IndexedDB so the
 * connection survives page refreshes (user must re-grant permission).
 */

const POLL_INTERVAL_MS = 15_000  // 15 seconds
const DB_NAME = 'cypher-folder-sync'
const STORE_NAME = 'handles'
const HANDLE_KEY = 'connectedFolder'

// Extensions we sync (mirrors backend Dispatcher)
const SUPPORTED_EXTS = new Set([
  'pdf', 'png', 'jpg', 'jpeg', 'tiff', 'bmp',
  'mp4', 'mkv', 'avi', 'mov',
  'mp3', 'wav', 'm4a', 'flac',
  'xlsx', 'xls', 'csv',
  'docx', 'doc', 'pptx', 'ppt', 'odt', 'html', 'txt',
  'eml', 'msg',
])

function extOf(name) {
  return (name.split('.').pop() || '').toLowerCase()
}

// ── IndexedDB helpers ─────────────────────────────────────────────────

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1)
    req.onupgradeneeded = () => req.result.createObjectStore(STORE_NAME)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

async function saveHandle(handle) {
  const db = await openDB()
  const tx = db.transaction(STORE_NAME, 'readwrite')
  tx.objectStore(STORE_NAME).put(handle, HANDLE_KEY)
  return new Promise((resolve, reject) => {
    tx.oncomplete = resolve
    tx.onerror = () => reject(tx.error)
  })
}

async function loadHandle() {
  const db = await openDB()
  const tx = db.transaction(STORE_NAME, 'readonly')
  const req = tx.objectStore(STORE_NAME).get(HANDLE_KEY)
  return new Promise((resolve) => {
    req.onsuccess = () => resolve(req.result || null)
    req.onerror = () => resolve(null)
  })
}

async function clearHandle() {
  const db = await openDB()
  const tx = db.transaction(STORE_NAME, 'readwrite')
  tx.objectStore(STORE_NAME).delete(HANDLE_KEY)
}

// ── File hashing via SubtleCrypto ─────────────────────────────────────

async function hashFile(fileHandle) {
  const file = await fileHandle.getFile()
  const buffer = await file.arrayBuffer()
  const hashBuffer = await crypto.subtle.digest('SHA-256', buffer)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('')
}

// ── Recursive directory scan ──────────────────────────────────────────

async function scanDirectory(dirHandle, basePath = '') {
  const files = []
  for await (const [name, handle] of dirHandle) {
    const relPath = basePath ? `${basePath}/${name}` : name
    if (handle.kind === 'file') {
      if (SUPPORTED_EXTS.has(extOf(name))) {
        files.push({ relPath, handle })
      }
    } else if (handle.kind === 'directory') {
      // Skip hidden/system directories
      if (!name.startsWith('.') && name !== 'node_modules' && name !== '__pycache__') {
        const subFiles = await scanDirectory(handle, relPath)
        files.push(...subFiles)
      }
    }
  }
  return files
}

// ── Main sync class ───────────────────────────────────────────────────

export class LocalFolderSync {
  constructor() {
    this.dirHandle = null
    this.folderName = null
    this.pollTimer = null
    this.syncing = false
    this.listeners = new Set()
    this._state = {
      connected: false,
      folderName: null,
      syncing: false,
      lastSync: null,
      totalFiles: 0,
      syncedFiles: 0,
      error: null,
    }
  }

  /** Subscribe to state changes. Returns unsubscribe function. */
  subscribe(fn) {
    this.listeners.add(fn)
    fn(this._state)
    return () => this.listeners.delete(fn)
  }

  _emit(patch) {
    Object.assign(this._state, patch)
    for (const fn of this.listeners) fn({ ...this._state })
  }

  /** Check if the browser supports the File System Access API. */
  static isSupported() {
    return typeof window.showDirectoryPicker === 'function'
  }

  /** Try to reconnect a previously saved handle (after page refresh). */
  async tryReconnect() {
    if (!LocalFolderSync.isSupported()) return false
    const handle = await loadHandle()
    if (!handle) return false

    // Must verify permission — browser requires user gesture on first access
    // after reload, but queryPermission tells us if it's still granted.
    try {
      const perm = await handle.queryPermission({ mode: 'read' })
      if (perm === 'granted') {
        this.dirHandle = handle
        this.folderName = handle.name
        this._emit({ connected: true, folderName: handle.name })
        this.startPolling()
        return true
      }
      // Permission prompt needed — we'll show a "Reconnect" button
      this._emit({ connected: false, folderName: handle.name })
      return false
    } catch {
      return false
    }
  }

  /** Request permission for a previously saved handle. */
  async requestPermission() {
    const handle = await loadHandle()
    if (!handle) return false
    try {
      const perm = await handle.requestPermission({ mode: 'read' })
      if (perm === 'granted') {
        this.dirHandle = handle
        this.folderName = handle.name
        this._emit({ connected: true, folderName: handle.name })
        this.startPolling()
        return true
      }
    } catch { /* user denied */ }
    return false
  }

  /** Open the folder picker and connect. */
  async connect() {
    if (!LocalFolderSync.isSupported()) {
      this._emit({ error: 'Browser does not support File System Access API. Use Chrome or Edge.' })
      return false
    }
    try {
      const handle = await window.showDirectoryPicker({ mode: 'read' })
      this.dirHandle = handle
      this.folderName = handle.name
      await saveHandle(handle)
      this._emit({ connected: true, folderName: handle.name, error: null })
      // Initial sync
      await this.syncNow()
      this.startPolling()
      return true
    } catch (err) {
      if (err.name !== 'AbortError') {
        this._emit({ error: `Failed to connect: ${err.message}` })
      }
      return false
    }
  }

  /** Disconnect and stop syncing. */
  async disconnect() {
    this.stopPolling()
    this.dirHandle = null
    this.folderName = null
    await clearHandle()
    this._emit({
      connected: false, folderName: null, syncing: false,
      totalFiles: 0, syncedFiles: 0, error: null,
    })
  }

  /** Run one sync cycle. */
  async syncNow() {
    if (!this.dirHandle || this.syncing) return
    this.syncing = true
    this._emit({ syncing: true, error: null })

    try {
      // 1. Scan the local folder
      const files = await scanDirectory(this.dirHandle)
      this._emit({ totalFiles: files.length })

      // 2. Hash all files
      const fileHashes = {}
      for (const f of files) {
        try {
          fileHashes[f.relPath] = await hashFile(f.handle)
        } catch (err) {
          console.warn(`[Sync] Could not hash ${f.relPath}:`, err)
        }
      }

      // 3. Ask the server which files need uploading
      const res = await fetch('/api/ingest/file-hashes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files: fileHashes }),
      })
      if (!res.ok) throw new Error(`Server returned ${res.status}`)
      const { needs_upload, server_deleted } = await res.json()

      // 4. Upload new/changed files
      let uploaded = 0
      for (const relPath of needs_upload) {
        const entry = files.find(f => f.relPath === relPath)
        if (!entry) continue
        try {
          const file = await entry.handle.getFile()
          const form = new FormData()
          form.append('file', file)
          form.append('local_path', relPath)
          form.append('content_hash', fileHashes[relPath] || '')
          const uploadRes = await fetch('/api/ingest/upload', {
            method: 'POST',
            body: form,
          })
          if (uploadRes.ok) uploaded++
        } catch (err) {
          console.warn(`[Sync] Upload failed for ${relPath}:`, err)
        }
        this._emit({ syncedFiles: uploaded })
      }

      // 5. Delete files that were removed locally
      for (const relPath of (server_deleted || [])) {
        try {
          await fetch(`/api/ingest/file?local_path=${encodeURIComponent(relPath)}`, {
            method: 'DELETE',
          })
        } catch (err) {
          console.warn(`[Sync] Delete failed for ${relPath}:`, err)
        }
      }

      this._emit({
        syncing: false,
        lastSync: new Date(),
        syncedFiles: files.length - (needs_upload.length - uploaded),
      })
    } catch (err) {
      console.error('[Sync] Error:', err)
      this._emit({ syncing: false, error: err.message })
    } finally {
      this.syncing = false
    }
  }

  startPolling() {
    this.stopPolling()
    this.pollTimer = setInterval(() => this.syncNow(), POLL_INTERVAL_MS)
  }

  stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer)
      this.pollTimer = null
    }
  }
}

// Singleton instance
export const folderSync = new LocalFolderSync()
