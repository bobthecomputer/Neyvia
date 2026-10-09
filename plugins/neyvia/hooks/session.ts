// What the mod knows about this Claude Code session. Module state: a hot reload starts it over, which only
// costs one more bootstrap (it is cached in $.store by session id). Anything that must survive the process
// (Neyvia starts a NEW claude per turn and resumes the session) lives on the Neyvia server or in $.store.
import { type Io, type Loose, asArray, text } from './client'

export type ToolRow = { name: string; neyviaName: string; description: string; inputSchema: Loose; deferred: boolean }
export type RoleRow = { name: string; description: string; prompt: string; model?: string; effort?: string; tools?: string[] }
export type Claim = { path: string; holder: string }
export type Bootstrap = {
  version: string
  etag: string
  section: string
  context: string
  tools: ToolRow[]
  denyPaths: string[]
  claims: Claim[]
  gate: { enabled: boolean; contracts: string[] }
  roles: RoleRow[]
  budget: { blockSpawn: boolean; reason: string }
}

export const mod = {
  session: '',
  run: 'adhoc',
  cwd: '',
  version: '',
  boot: null as Bootstrap | null,
  stale: false,
  // The section is frozen on first use so every request of a process (and, while the server text is
  // unchanged, every process of the session) sends identical bytes and keeps the prompt cache.
  frozenSection: null as string | null,
  stateHash: '',
  receipt: null as Loose | null,
  blocksSoFar: 0,
  registered: new Map<string, string>(), // full MCP tool name -> neyvia.* name
}

export const isAdhoc = (): boolean => mod.run === 'adhoc'

export async function identify(io: Io): Promise<void> {
  if (!mod.session) mod.session = String(await io.sessionId())
}

export function parseBootstrap(json: Loose, etag: string): Bootstrap {
  const rules = (json.rules && typeof json.rules === 'object' ? json.rules : {}) as Loose
  const gate = (json.gate && typeof json.gate === 'object' ? json.gate : {}) as Loose
  const budget = (json.budget && typeof json.budget === 'object' ? json.budget : {}) as Loose
  const block = (key: string): string => {
    const value = json[key]
    return text(value && typeof value === 'object' ? (value as Loose).text : '', 6000)
  }
  return {
    version: text(json.version, 40),
    etag,
    section: block('section'),
    context: block('context'),
    tools: asArray(json.tools).map(row => ({
      name: text(row.name, 64), neyviaName: text(row.neyviaName, 200), description: text(row.description, 1000),
      inputSchema: (row.inputSchema && typeof row.inputSchema === 'object' ? row.inputSchema : { type: 'object' }) as Loose,
      deferred: row.deferred !== false,
    })).filter(row => /^[A-Za-z0-9_-]{1,64}$/.test(row.name) && row.neyviaName),
    denyPaths: (Array.isArray(rules.denyPaths) ? rules.denyPaths : []).map(String).filter(Boolean),
    claims: asArray(rules.claims).map(row => ({ path: text(row.path, 1000), holder: text(row.holder, 200) })).filter(row => row.path),
    gate: { enabled: gate.enabled === true, contracts: (Array.isArray(gate.contracts) ? gate.contracts : []).map(String) },
    roles: asArray(json.roles).map(row => ({
      name: text(row.name, 64), description: text(row.description, 1000), prompt: text(row.prompt, 8000),
      ...(row.model ? { model: text(row.model, 100) } : {}), ...(row.effort ? { effort: text(row.effort, 20) } : {}),
      ...(Array.isArray(row.tools) ? { tools: row.tools.map(String) } : {}),
    })).filter(row => /^[A-Za-z0-9_-]{1,64}$/.test(row.name) && row.prompt),
    budget: { blockSpawn: budget.blockSpawn === true, reason: text(budget.reason, 300) },
  }
}
