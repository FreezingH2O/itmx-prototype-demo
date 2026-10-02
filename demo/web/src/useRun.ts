import { useCallback, useEffect, useRef, useState } from 'react'
import { api, apiUrl, type Json } from './api'

// One run shared by every tab: the run id lives in localStorage, and each tab follows
// the server's SSE stream so all views show the same case, time and state version.
const KEY = 'nitmx.run_id'
const REFRESH_MS = 400
const POLL_MS = 1000 // fallback while playing if the stream goes quiet (proxy buffering, dropped connection)
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
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // The run this tab follows. Responses for any other run (a refresh still in flight when the user
  // switched scenario) are dropped, so an old run can never overwrite the new one.
  const currentRef = useRef<string | null>(null)
  const lastMsgRef = useRef(0)

  const accept = useCallback((r: Json) => {
    if (r.run_id !== currentRef.current) return
    setRun(r)
    setVersion(r.version)
  }, [])

  const refresh = useCallback(async (id: string) => {
    const r = await api.get(`/v1/runs/${id}`)
    accept(r)
    return r
  }, [accept])

  const attach = useCallback((id: string) => {
    currentRef.current = id
    esRef.current?.close()
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null }
    const es = new EventSource(apiUrl(`/v1/runs/${id}/stream`))
    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)
    // At high replay speed the server changes many times a second; refresh at most every REFRESH_MS.
    let last = 0
    const pull = () => { timerRef.current = null; last = Date.now(); refresh(id).catch(() => {}) }
    es.onmessage = (m) => {
      lastMsgRef.current = Date.now()
      const msg = JSON.parse(m.data)
      if (msg.version === undefined || timerRef.current || id !== currentRef.current) return
      const wait = REFRESH_MS - (Date.now() - last)
      if (wait <= 0) pull()
      else timerRef.current = setTimeout(pull, wait)
    }
    esRef.current = es
  }, [refresh])

  const start = useCallback(async (scenario: string, mode: 'live' | 'recorded', speed = 30) => {
    setError(null)
    try {
      const r = await api.post('/v1/runs', { scenario, mode, speed })
      writeStored(r.run_id)
      attach(r.run_id)
      accept(r)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [attach, accept])

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY && e.newValue) { attach(e.newValue); refresh(e.newValue).catch(() => {}) }
    }
    window.addEventListener('storage', onStorage)
    const boot = async () => {
      const id = readStored()
      if (id) {
        try { currentRef.current = id; await refresh(id); attach(id); return } catch { /* stale id: server restarted */ }
      }
      await start('merchant_300', 'live')
    }
    if (!booted) booted = boot()
    else booted.then(() => { const id = readStored(); if (id) { attach(id); refresh(id).catch(() => {}) } })
    return () => { window.removeEventListener('storage', onStorage); esRef.current?.close() }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Fallback: while the clock plays, poll if the stream has been silent, so the view never freezes.
  const playing = !!run?.clock.playing
  const runId = run?.run_id as string | undefined
  useEffect(() => {
    if (!playing || !runId) return
    const t = setInterval(() => {
      if (Date.now() - lastMsgRef.current > POLL_MS * 2) refresh(runId).catch(() => {})
    }, POLL_MS)
    return () => clearInterval(t)
  }, [playing, runId, refresh])

  const clock = useCallback(async (action: string, extra: Json = {}) => {
    if (!run) return
    try {
      const r = await api.post(`/v1/runs/${run.run_id}/clock`, { action, ...extra })
      accept(r)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [run, accept])

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

// Fetch several paths together whenever the run version changes (the list may differ per run).
export function useViews<T = Json>(paths: string[], version: number): Record<string, T | null> {
  const [data, setData] = useState<Record<string, T | null>>({})
  const key = paths.join('|')
  useEffect(() => {
    let alive = true
    Promise.all(paths.map((p) => api.get(p).catch(() => undefined)))
      .then((rows) => {
        if (!alive) return
        // A failed fetch keeps the last good copy, like useView.
        setData((prev) => Object.fromEntries(paths.map((p, i) => [p, rows[i] === undefined ? prev[p] ?? null : rows[i]])))
      })
    return () => { alive = false }
  }, [key, version]) // eslint-disable-line react-hooks/exhaustive-deps
  return data
}
