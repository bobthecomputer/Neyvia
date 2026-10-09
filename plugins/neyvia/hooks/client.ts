// Shared plumbing for the Neyvia mod: where the local Neyvia app is, how to sign in, and one fetch that never
// hangs a turn. Every call races a 2 s timer (the host's fetch has no timeout); a slow or absent Neyvia means the
// mod passes through and says so on the status line. Nothing here reads or sends a Claude credential.
import type { AgentSpec, HttpInit, HttpResponse, PluginOptions, ToolSpec } from 'claude-code'

// Claude Code's validator follows `$` only inside the file that receives it, so register.ts holds every `$.noun.verb`
// call and hands the other modules this small set of closures instead.
export type Io = {
  backend(): Promise<string | undefined>
  legacyBackend(): Promise<string | undefined>
  runId(): Promise<string | undefined>
  env(name: string): Promise<string | undefined>
  readText(path: string): Promise<string>
  fetch(url: string, init?: HttpInit): Promise<HttpResponse>
  sleep(ms: number, signal?: AbortSignal): Promise<void>
  status(line: string): Promise<unknown>
  log(line: string): Promise<unknown>
  toast(line: string): Promise<unknown>
  get(key: string): Promise<unknown>
  set(key: string, value: unknown): Promise<unknown>
  keys(): Promise<string[]>
  remove(key: string): Promise<unknown>
  sessionId(): Promise<string>
  stat(path: string): Promise<{ realPath?: string }>
  registerTool(spec: ToolSpec): Promise<unknown>
  registerAgent(spec: AgentSpec): Promise<unknown>
}
export type Loose = Record<string, unknown>

export const FAST_MS = 2000
// Signing in happens once per process; Neyvia's local sign-in measured 2-25 s on a loaded PC, so it gets a longer wait.
export const SIGNIN_MS = 10000
const LOOPBACK = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?$/

export const net = {
  settings: {} as PluginOptions,
  base: null as string | null,
  cookie: '',
  token: null as string | null,
  fileBase: '',
  state: 'unknown' as 'unknown' | 'connected' | 'slow' | 'offline',
}

export const MOD_PATH = '/api/ui/claude-code/mod'

export function configure(options: PluginOptions): void {
  net.settings = options
  net.base = null
  net.cookie = ''
  net.token = null
  net.fileBase = ''
}

export function mark(io: Io, state: 'connected' | 'slow' | 'offline', why = ''): void {
  if (net.state === state) return
  net.state = state
  const line = state === 'connected' ? 'Neyvia connected' : state === 'slow' ? 'Neyvia slow' : 'Neyvia offline'
  Promise.resolve(io.status(line)).catch(() => undefined)
  if (state !== 'connected') Promise.resolve(io.log(`neyvia: ${line}${why ? ` (${why.slice(0, 160)})` : ''}`)).catch(() => undefined)
}

// The scoped mod token: NEYVIA_MOD_TOKEN on a Neyvia-launched turn, else the token file Neyvia keeps for the person's own
// sessions (NEYVIA_MOD_TOKEN_FILE, default ~/.neyvia/claude-mod.json, which also names the backend). It is accepted only on
// the mod routes. With none, the mod falls back to the local sign-in cookie.
async function credential(io: Io): Promise<string> {
  if (net.token !== null) return net.token
  net.token = ''
  try {
    const fromEnv = await io.env('NEYVIA_MOD_TOKEN')
    if (fromEnv) { net.token = fromEnv; return net.token }
    const home = (await io.env('USERPROFILE')) || (await io.env('HOME')) || ''
    const file = (await io.env('NEYVIA_MOD_TOKEN_FILE')) || (home ? `${home}/.neyvia/claude-mod.json` : '')
    if (!file) return ''
    const row = JSON.parse(await io.readText(file)) as Loose
    net.token = typeof row.token === 'string' ? row.token : ''
    net.fileBase = typeof row.backend === 'string' ? row.backend : ''
  } catch { /* no token file: fall back to sign-in */ }
  return net.token
}

async function backendUrl(io: Io): Promise<string | null> {
  if (net.base !== null) return net.base || null
  await credential(io)
  const fromNeyvia = (await io.backend()) || (await io.legacyBackend())
  const url = String(fromNeyvia || net.fileBase || net.settings.backendUrl || '').replace(/\/$/, '')
  net.base = LOOPBACK.test(url) ? url : ''
  return net.base || null
}

export async function isEnabled(io: Io): Promise<boolean> {
  return net.settings.report !== false && (await backendUrl(io)) !== null
}

// The run this process serves: Neyvia sets NEYVIA_RUN_ID per turn; a person's own Claude Code has none.
export async function runId(io: Io): Promise<string> {
  return (await io.runId()) || 'adhoc'
}

// Resolves with the work's value, or null when the timer wins (the work is then abandoned).
async function within<T>(io: Io, work: Promise<T>, ms: number): Promise<T | null> {
  const timer = new AbortController()
  const clock = io.sleep(ms, timer.signal).then((): null => null, () => new Promise<never>(() => undefined))
  try {
    return await Promise.race([work, clock])
  } finally {
    timer.abort()
  }
}

export type Answer = { status: number; json: Loose | null; headers: Record<string, string> }

function header(headers: Record<string, string>, name: string): string {
  for (const [key, value] of Object.entries(headers || {})) if (key.toLowerCase() === name) return value
  return ''
}

// One request to Neyvia. null = nothing usable (offline, slow, refused); the caller passes through.
export async function request(io: Io, method: 'GET' | 'POST', path: string, options: {
  body?: Loose; headers?: Record<string, string>; timeoutMs?: number | null; event?: string
} = {}): Promise<Answer | null> {
  const url = await backendUrl(io)
  if (!url || net.settings.report === false) return null
  const timeoutMs = options.timeoutMs === undefined ? FAST_MS : options.timeoutMs
  try {
    for (const attempt of [0, 1]) {
      const token = await credential(io)
      if (!token && !net.cookie) {
        const signIn = await within(io, io.fetch(`${url}/api/auth/local-session`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
        }), SIGNIN_MS)
        if (signIn === null) { mark(io, 'slow', 'sign-in'); return null }
        net.cookie = header(signIn.headers, 'set-cookie').split(';')[0] || ''
        if (!net.cookie) throw new Error(`sign-in answered ${signIn.status}`)
      }
      const headers: Record<string, string> = { ...(token ? { 'X-Neyvia-Mod-Token': token } : { Cookie: net.cookie }), ...(options.headers || {}) }
      if (options.body) headers['Content-Type'] = 'application/json'
      if (options.event) headers['X-Neyvia-Mod'] = options.event
      const pending = io.fetch(`${url}${path}`, {
        method, headers, ...(options.body ? { body: JSON.stringify(options.body) } : {}),
      })
      const answer = timeoutMs === null ? await pending : await within(io, pending, timeoutMs)
      if (answer === null) { mark(io, 'slow', path); return null }
      if (answer.status === 401 && attempt === 0 && !token) { net.cookie = ''; continue }
      mark(io, 'connected')
      let json: Loose | null = null
      try { json = answer.text ? (JSON.parse(answer.text) as Loose) : null } catch { json = null }
      return { status: answer.status, json, headers: answer.headers || {} }
    }
  } catch (error) {
    mark(io, 'offline', String(error))
  }
  return null
}

export const etagOf = (answer: Answer): string => header(answer.headers, 'etag') || String(answer.json?.etag || '')

export function query(values: Record<string, string | number | undefined>): string {
  const parts = Object.entries(values).filter(([, value]) => value !== undefined && value !== '')
  return parts.length ? '?' + parts.map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`).join('&') : ''
}

export const text = (value: unknown, max: number): string => String(value ?? '').slice(0, max)
export const asArray = (value: unknown): Loose[] => (Array.isArray(value) ? (value.filter(row => row && typeof row === 'object') as Loose[]) : [])
