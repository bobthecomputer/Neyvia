// Bootstrap, the one static system-prompt section, fresh context blocks, and the per-prompt state diff.
import { type Io, MOD_PATH, type Loose, etagOf, isEnabled, query, request, runId, text } from './client'
import { type Bootstrap, identify, mod, parseBootstrap } from './session'
import { registerTools } from './tools'

const SECTION_ID = 'neyvia:primer'
const SECTION_MAX = 6000
const DIFF_MAX = 1200
const FIRST_BOOTSTRAP_MS = 8000 // the hook budget is 10 s

const cacheKey = (): string => `neyvia:boot:${mod.session}`

// The store lives across sessions and Claude Code caps it at 4 MiB: every per-session key (a ~90 KB bootstrap,
// the inbox cursor, the claim) belongs to one session only, so older sessions' keys are dropped before writing.
const SESSION_PREFIXES = ['neyvia:boot:', 'neyvia:inbox:', 'neyvia:claim:']
async function keepOnlyThisSession(io: Io): Promise<void> {
  try {
    for (const key of await io.keys()) {
      if (SESSION_PREFIXES.some(prefix => key.startsWith(prefix)) && !key.endsWith(`:${mod.session}`)) await io.remove(key)
    }
  } catch { /* pruning is best effort */ }
}

// Fetch the bootstrap with its ETag. A 304 keeps the cached copy; a slow or absent Neyvia falls back to the
// cached copy (so the prompt keeps its bytes and the cache stays warm) or to nothing (pass-through).
export async function loadBootstrap(io: Io, event: string): Promise<Bootstrap | null> {
  await identify(io)
  if (!(await isEnabled(io))) return null
  mod.run = await runId(io)
  if (!mod.boot) {
    const stored = (await io.get(cacheKey())) as Bootstrap | undefined
    if (stored && typeof stored === 'object' && stored.etag) mod.boot = stored
  }
  const answer = await request(io, 'GET', `${MOD_PATH}/bootstrap${query({ session: mod.session, run: mod.run, cwd: mod.cwd, version: mod.version })}`, {
    headers: mod.boot?.etag ? { 'If-None-Match': mod.boot.etag } : {}, event,
    // Nothing cached yet: the first bootstrap of a session may take a few seconds on a busy PC, so wait longer once.
    ...(mod.boot ? {} : { timeoutMs: FIRST_BOOTSTRAP_MS }),
  })
  mod.stale = !answer || ![200, 304].includes(answer.status) || (answer.status === 200 && !answer.json)
  if (answer && answer.status === 200 && answer.json) {
    mod.boot = parseBootstrap(answer.json, etagOf(answer))
    await keepOnlyThisSession(io)
    // The cache is a nicety: a full or refusing store must never cost the session its tools.
    try { await io.set(cacheKey(), mod.boot as unknown as Loose) } catch { /* keep going without the cached copy */ }
  }
  return mod.boot
}

// The section text is frozen at first use: identical bytes on every request, so the prompt cache holds.
export function sectionText(): string {
  if (mod.frozenSection === null) mod.frozenSection = text(mod.boot?.section, SECTION_MAX)
  return mod.frozenSection
}

function describeDiff(diff: unknown): string {
  // prompt.context already delivers the current live snapshot once per turn.
  const parts = diff && typeof diff === 'object' ? (diff as Loose).parts : undefined
  if (parts && typeof parts === 'object') {
    return Object.entries(parts).filter(([key]) => key !== 'live').map(([, value]) => String(value)).join('\n').slice(0, DIFF_MAX)
  }
  const said = diff && typeof diff === 'object' ? (diff as Loose).text : undefined
  const raw = typeof diff === 'string' ? diff : typeof said === 'string' ? said : JSON.stringify(diff)
  return raw.length > DIFF_MAX ? raw.slice(0, DIFF_MAX - 1) + '…' : raw
}

// The model-only note for a prompt: what changed in Neyvia since the server last told this session (work board, mission, checklist, attention).
export async function stateDiff(io: Io): Promise<string | null> {
  if (!mod.session || !(await isEnabled(io))) return null
  const answer = await request(io, 'GET', `${MOD_PATH}/state${query({ session: mod.session, run: mod.run, since: mod.stateHash })}`, { event: 'prompt.submit' })
  if (!answer || answer.status !== 200 || !answer.json) return null
  if (typeof answer.json.hash === 'string') mod.stateHash = answer.json.hash
  const diff = answer.json.diff
  return diff === null || diff === undefined || diff === '' ? null : describeDiff(diff) || null
}

// The one session-scoped section (identical bytes on every request).
export function withSection<T extends { sections: readonly { id: string; text: string; scope: 'shared' | 'session' }[] }>(composed: T): T {
  const body = mod.boot ? sectionText() : ''
  if (!body) return composed
  return { ...composed, sections: [...composed.sections.filter(row => row.id !== SECTION_ID), { id: SECTION_ID, text: body, scope: 'session' as const }] }
}

// Per-turn context, read fresh: includes the server-cached Right now in Neyvia snapshot.
// A compaction or --resume rebuilds it from the same bootstrap; live data never enters the frozen section.
export async function withContext<T extends { blocks: readonly { name: string; text: string }[] }>(io: Io, answered: T): Promise<T> {
  const boot = await loadBootstrap(io, 'prompt.context')
  if (boot) await registerTools(io, boot)
  // A cached bootstrap keeps the static prompt warm, but cannot describe what is happening now while offline.
  const discovery = mod.registered.size
    ? 'Neyvia discovery tools are ready in this turn: call mcp__neyvia__tools_search, then tools_describe/tools_call. Other Neyvia tools load with ToolSearch query="+neyvia <action>" or "select:mcp__neyvia__cl". An empty MCP server list does not mean the mod tools are absent.'
    : 'Neyvia tool registration has not completed. Tools come from the mod bootstrap, not the empty plugin MCP server. Retry ToolSearch query="+neyvia" before claiming tools are unavailable; if still absent, report that Neyvia is not connected.'
  const body = boot || mod.session ? discovery + (mod.stale ? '' : '\n' + text(boot?.context, 2600)) : ''
  const blocks = answered.blocks.filter(row => row.name !== 'neyvia')
  return { ...answered, blocks: body ? [...blocks, { name: 'neyvia', text: body }] : blocks }
}
