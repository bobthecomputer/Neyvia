// The stop gate: before Claude Code ends a turn, ask Neyvia whether the contracts for this work still pass.
// A block returns WITHOUT calling next, so Neyvia's own settings Stop hook never sees the stop and the process
// stays open for the fix. Neyvia counts the blocks per session (two at most, then it passes and marks the work
// unproven), so a failing contract can never trap the session. A slow or absent Neyvia passes the stop.
import { type Io, MOD_PATH, asArray, request, runId, text } from './client'
import { mod } from './session'

// The host budget for a hook dispatch is 10 s; Neyvia answers within 20 s at most, the mod waits for 9 s.
const STOP_WAIT_MS = 9000

// A block to hand back instead of calling next, or null to let the stop go on.
export async function stopBlock(io: Io, e: { last_assistant_message?: string; stop_hook_active?: boolean }): Promise<string | null> {
  if (!mod.boot?.gate.enabled) return null
  const answer = await request(io, 'POST', `${MOD_PATH}/stop`, {
    body: { session: mod.session, run: await runId(io), lastMessage: text(e.last_assistant_message, 4000), stopHookActive: e.stop_hook_active === true },
    timeoutMs: STOP_WAIT_MS, event: 'classic.Stop',
  })
  const body = answer?.json
  if (!body) return null
  mod.receipt = (body.receipt ?? null) as typeof mod.receipt
  mod.blocksSoFar = Number(body.blocksSoFar) || 0
  if (!body.block) return null
  // block is Neyvia's own reason text (or true); failing names the contracts and hints when it is not text.
  if (typeof body.block === 'string') return text(body.block, 1800)
  const lines = asArray(body.failing).map(row => `${text(row.contract, 120)}: ${text(row.hint, 400)}`)
  return text(`Neyvia contracts still failing (${lines.length || 1}). ${lines.join(' | ')}`.trim(), 1800)
}
