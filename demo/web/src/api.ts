// Thin client for the Engine API. Every page reads through these calls.
export type Json = any // eslint-disable-line @typescript-eslint/no-explicit-any

export class ApiError extends Error {
  status: number
  body: Json
  constructor(status: number, body: Json) {
    super(typeof body?.detail === 'string' ? body.detail : `HTTP ${status}`)
    this.status = status
    this.body = body
  }
}

async function call(method: string, path: string, body?: Json, headers: Record<string, string> = {}) {
  const r = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await r.text()
  const data = text ? JSON.parse(text) : null
  if (!r.ok) throw new ApiError(r.status, data)
  return data
}

export const api = {
  get: (path: string, headers?: Record<string, string>) => call('GET', path, undefined, headers),
  post: (path: string, body: Json, headers?: Record<string, string>) => call('POST', path, body, headers),
}

export function newKey(): string {
  return crypto.randomUUID().replace(/-/g, '')
}
