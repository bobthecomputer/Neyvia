// Local rules from the bootstrap: paths Neyvia keeps off limits, and files another agent is working in.
// Decisions never call the network. Paths are compared on the resolved real path (links and .. resolved)
// where the file exists, and on the spelling otherwise; a Bash/PowerShell command is checked as text.
import type { Io, Loose } from './client'
import { isAdhoc, mod } from './session'

const WRITE_TOOLS = new Set(['Edit', 'Write', 'MultiEdit', 'NotebookEdit'])
const SHELL_TOOLS = new Set(['Bash', 'PowerShell'])

export const norm = (path: string): string => path.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()

// A rule is a folder or file (prefix on a path boundary) or a pattern with * and ?.
export function ruleHits(rule: string, path: string): boolean {
  const r = norm(rule)
  const p = norm(path)
  if (!r || !p) return false
  if (/[*?]/.test(r)) {
    const body = r.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*\*/g, '\u0000').replace(/\*/g, '[^/]*').replace(/\u0000/g, '.*').replace(/\?/g, '[^/]')
    return new RegExp('^' + body + '$').test(p)
  }
  return p === r || p.startsWith(r + '/')
}

function pathsOf(input: Loose): string[] {
  const out: string[] = []
  for (const key of ['file_path', 'notebook_path', 'path']) if (typeof input[key] === 'string' && input[key]) out.push(input[key] as string)
  return out
}

async function spellings(io: Io, path: string): Promise<string[]> {
  const found = new Set([path])
  try {
    const stat = (await io.stat(path)) as unknown as Loose
    if (typeof stat.realPath === 'string') found.add(stat.realPath)
  } catch {
    // The file may not exist yet (a Write): resolve its folder instead.
    const cut = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
    if (cut > 0) {
      try {
        const stat = (await io.stat(path.slice(0, cut))) as unknown as Loose
        if (typeof stat.realPath === 'string') found.add(stat.realPath.replace(/[\\/]+$/, '') + path.slice(cut))
      } catch { /* leave the spelling alone */ }
    }
  }
  return [...found]
}

export async function judgePaths(io: Io, tool: string, input: Loose): Promise<string | null> {
  const rules = mod.boot?.denyPaths ?? []
  if (!rules.length) return null
  if (SHELL_TOOLS.has(tool)) {
    const command = norm(String(input.command || ''))
    const hit = rules.find(rule => norm(rule) && command.includes(norm(rule)))
    if (hit) return `Neyvia keeps ${hit} off limits here.`
  }
  for (const path of pathsOf(input)) {
    for (const spelling of await spellings(io, path)) {
      const hit = rules.find(rule => ruleHits(rule, spelling))
      if (hit) return `Neyvia keeps ${hit} off limits here.`
    }
  }
  return null
}

// Another agent holds the file: { holder } or null. Own claims (holder names this session) never block.
export async function heldBy(io: Io, tool: string, input: Loose): Promise<{ path: string; holder: string } | null> {
  const claims = mod.boot?.claims ?? []
  if (!claims.length || !WRITE_TOOLS.has(tool)) return null
  for (const path of pathsOf(input)) {
    for (const spelling of await spellings(io, path)) {
      const claim = claims.find(row => ruleHits(row.path, spelling) && !(mod.session && row.holder.includes(mod.session)))
      if (claim) return { path, holder: claim.holder }
    }
  }
  return null
}

const heldMessage = (held: { path: string; holder: string }): string =>
  `${held.path} is held by ${held.holder}. Use the neyvia activity tool to see what they are doing, or the neyvia message tool to ask.`

// The refusal for a tool call, or null to let it through. Called from the one tool.call hook in register.ts,
// which fails open: a bug in a guard must not stop every tool call (the host logs the failed hook).
export async function guardTool(io: Io, e: Loose): Promise<string | null> {
  const tool = String(e.tool)
  const denied = await judgePaths(io, tool, e)
  if (denied) return denied
  if (!isAdhoc()) {
    const held = await heldBy(io, tool, e)
    if (held) return heldMessage(held)
  }
  return null
}

// In a person's own interactive session a held file is a question, not a wall.
export async function askIfHeld<V extends { decision: string; reason?: string }>(io: Io, e: { tool: string; input?: unknown }, verdict: V): Promise<V> {
  if (!isAdhoc() || verdict.decision === 'deny') return verdict
  const held = await heldBy(io, String(e.tool), (e.input ?? {}) as Loose)
  return held ? { ...verdict, decision: 'ask', reason: heldMessage(held) } : verdict
}
