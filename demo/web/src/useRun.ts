import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Json } from './api'

// One run shared by every tab: the run id lives in localStorage, and each tab follows
// the server's SSE stream so all views show the same case, time and state version.
const KEY = 'nitmx.run_id'
let booted: Promise<void> | null = null // StrictMode runs effects twice in dev; boot once

function readStored(): string | null {
  try { return localStorage.getItem(KEY) } catch { return null }
}
function writeStored(id: string) {
  try { localStorage.setItem(KEY, id) } catch { /* storage blocked */ }
}

export function useRun() {
  const [run, setRun] = useState<Json | null>(null)
  const [version, setVersion] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  const refresh = useCallback(async (id: string) => {
    const r = await api.get(`/v1/runs/${id}`)
    setRun(r)
    setVersion(r.version)
    return r
  }, [])

  const attach = useCallback((id: string) => {
    esRef.current?.close()
    const es = new EventSource(`/v1/runs/${id}/stream`)
    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)
    es.onmessage = (m) => {
      const msg = JSON.parse(m.data)
      if (msg.version !== undefined) refresh(id).catch(() => {})
    }
    esRef.current = es
  }, [refresh])

  const start = useCallback(async (scenario: string, mode: 'live' | 'recorded') => {
    setError(null)
    try {
      const r = await api.post('/v1/runs', { scenario, mode, speed: 30 })
      writeStored(r.run_id)
      setRun(r)
      setVersion(r.version)
      attach(r.run_id)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [attach])

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY && e.newValue) refresh(e.newValue).then(() => attach(e.newValue!)).catch(() => {})
    }
    window.addEventListener('storage', onStorage)
    const boot = async () => {
      const id = readStored()
      if (id) {
        try { await refresh(id); attach(id); return } catch { /* stale id: server restarted */ }
      }
      await start('merchant_300', 'live')
    }
    if (!booted) booted = boot()
    else booted.then(() => { const id = readStored(); if (id) refresh(id).then(() => attach(id)).catch(() => {}) })
    return () => { window.removeEventListener('storage', onStorage); esRef.current?.close() }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const clock = useCallback(async (action: string, extra: Json = {}) => {
    if (!run) return
    try {
      const r = await api.post(`/v1/runs/${run.run_id}/clock`, { action, ...extra })
      setRun(r)
      setVersion(r.version)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [run])

  return { run, version, error, connected, start, clock, setError }
}

// Fetch a path whenever the run version changes.
export function useView<T = Json>(path: string | null, version: number, headers?: Record<string, string>) {
  const [data, setData] = useState<T | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const hdr = JSON.stringify(headers ?? {})
  useEffect(() => {
    if (!path) return
    let alive = true
    api.get(path, JSON.parse(hdr)).then((d) => { if (alive) { setData(d); setErr(null) } })
      .catch((e) => { if (alive) setErr((e as Error).message) })
    return () => { alive = false }
  }, [path, version, hdr])
  return { data, err }
}
