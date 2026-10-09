// Messages for a session that Neyvia does not run (a person's own Claude Code). A Neyvia-run session gets its
// messages through steer() or its next --resume turn, so this stays silent there. No timers and no long poll:
// the inbox is read when a prompt is submitted and when a turn completes.
import { type Io, type Loose, MOD_PATH, asArray, query, request, text } from './client'
import { isAdhoc, mod } from './session'

const pending: string[] = []

async function pull(io: Io, event: string): Promise<void> {
  if (!isAdhoc() || !mod.session || !mod.boot) return
  const key = `neyvia:inbox:${mod.session}`
  const since = ((await io.get(key)) as string | undefined) || ''
  const answer = await request(io, 'GET', `${MOD_PATH}/inbox${query({ session: mod.session, since })}`, { event })
  if (!answer || answer.status !== 200 || !answer.json) return
  for (const row of asArray(answer.json.events)) {
    if (row.kind === 'message' && row.text) pending.push(`Message from ${text(row.from || 'another agent', 80)} via Neyvia: ${text(row.text, 800)}`)
    else if (row.kind === 'claims' && mod.boot) {
      mod.boot.claims = asArray(row.claims).map((claim: Loose) => ({ path: text(claim.path, 1000), holder: text(claim.holder, 200) })).filter(claim => claim.path)
    }
  }
  if (typeof answer.json.next === 'string') await io.set(key, answer.json.next)
}

// Messages waiting for this session, as one model-only note (or null).
export async function inboxNote(io: Io): Promise<string | null> {
  await pull(io, 'prompt.submit')
  return pending.length ? pending.splice(0, pending.length).join(String.fromCharCode(10)).slice(0, 1500) : null
}

export async function afterTurn(io: Io): Promise<void> {
  await pull(io, 'turn.complete')
  if (pending.length) await io.toast(`Neyvia: ${pending.length} new message${pending.length === 1 ? '' : 's'} for this session`)
}
