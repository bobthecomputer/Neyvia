// What this session tells Neyvia, in batches: the turn (state and token counts), the checklist, the files edited,
// claims on the work board, plan limits, and the end. It only observes; it never changes a prompt or a tool call.
import { type Io, type Loose, MOD_PATH, isEnabled, request, runId, text } from './client'
import { identify, mod } from './session'

type Item = { text: string; status: 'pending' | 'in_progress' | 'completed' }

const EDIT_TOOLS = new Set(['Edit', 'Write', 'MultiEdit', 'NotebookEdit'])
const CHECKLIST_TOOLS = new Set(['TodoWrite', 'TaskCreate', 'TaskUpdate'])
const STATUSES = new Set(['pending', 'in_progress', 'completed'])
const CHECKLIST_EVERY_MS = 3000
const LIMITS_EVERY_MS = 15000

const turn = {
  intent: '',
  edited: new Set<string>(),
  tasks: new Map<string, Item>(),
  checklist: null as Item[] | null,
  checklistSentAt: 0,
  checklistPending: false,
  checklistSent: '',
  limitsKey: '',
  limitsSentAt: 0,
  limits: null as Loose | null,
  announced: false,
}

export async function report(io: Io, kind: 'session' | 'turn' | 'limits' | 'edits' | 'checklist' | 'end', body: Loose = {}): Promise<boolean> {
  if (!(await isEnabled(io))) return false
  await identify(io)
  const answer = await request(io, 'POST', `${MOD_PATH}/report`, { body: { session: mod.session, run: await runId(io), kind, ...body }, event: `report.${kind}` })
  return answer !== null && answer.status < 400
}

function checklistFrom(tool: string, input: Loose, result: unknown): Item[] | null {
  if ((tool === 'plan_update' || tool.endsWith('__plan_update')) && Array.isArray(input.plan)) {
    return (input.plan as Loose[]).filter(row => STATUSES.has(String(row.status)))
      .map(row => ({ text: String(row.step || ''), status: row.status as Item['status'] }))
  }
  if (tool === 'TodoWrite' && Array.isArray(input.todos)) {
    return (input.todos as Loose[]).filter(row => STATUSES.has(String(row.status)))
      .map(row => ({ text: String(row.content || row.activeForm || ''), status: row.status as Item['status'] }))
  }
  if (tool === 'TaskCreate') {
    const made = JSON.stringify(result ?? '').match(/#(\d+)/)
    const id = made?.[1] || String(turn.tasks.size + 1)
    turn.tasks.set(id, { text: String(input.subject || input.description || ''), status: 'pending' })
    return [...turn.tasks.values()]
  }
  if (tool === 'TaskUpdate' && input.taskId !== undefined) {
    const id = String(input.taskId)
    const row = turn.tasks.get(id) || { text: String(input.subject || `Task ${id}`), status: 'pending' as Item['status'] }
    if (input.status === 'deleted') turn.tasks.delete(id)
    else turn.tasks.set(id, { text: String(input.subject || row.text), status: STATUSES.has(String(input.status)) ? input.status as Item['status'] : row.status })
    return [...turn.tasks.values()]
  }
  return null
}

async function sendChecklist(io: Io): Promise<void> {
  if (!turn.checklist || !turn.checklistPending) return
  turn.checklistPending = false
  const sent = JSON.stringify(turn.checklist)
  if (sent === turn.checklistSent) return
  turn.checklistSent = sent
  turn.checklistSentAt = Date.now()
  await report(io, 'checklist', { items: turn.checklist })
}

// Claim the files this turn edited on the work board, one call per turn; release the previous claim.
async function claimEdited(io: Io): Promise<void> {
  if (!turn.edited.size) return
  const key = `neyvia:claim:${mod.session}`
  const previous = (await io.get(key)) as string | undefined
  const answer = await request(io, 'POST', `${MOD_PATH}/tool`, {
    body: {
      session: mod.session, run: await runId(io), tool: 'neyvia.work.claim',
      args: { files: [...turn.edited].slice(-100), intent: turn.intent || 'Editing in Claude Code', agent: 'Claude Code', chat: mod.session, app: 'claude-code' },
    },
    event: 'report.claims',
  })
  const result = (answer?.json?.result ?? null) as Loose | null
  const made = ((result?.claim ?? result) as Loose | null)?.id
  if (typeof made !== 'string') return
  if (previous && previous !== made) {
    await request(io, 'POST', `${MOD_PATH}/tool`, { body: { session: mod.session, run: await runId(io), tool: 'neyvia.work.release', args: { id: previous } }, event: 'report.claims' })
  }
  await io.set(key, made)
}

function limitsPayload(e: Loose): { key: string; body: Loose } {
  const limits = (Array.isArray(e.rateLimits) ? e.rateLimits : []) as Loose[]
  const context = (e.context ?? {}) as Loose
  const key = JSON.stringify([limits.map(row => [row.kind, Math.round(Number(row.percentUsed) || 0)]), Math.round(Number(context.percent) || 0)])
  return { key, body: { rateLimits: limits, context: { tokens: context.tokens, window: context.window, percent: context.percent }, cost: e.cost ?? null } }
}

async function sendLimits(io: Io, force: boolean): Promise<void> {
  if (!turn.limits) return
  const { key, body } = limitsPayload(turn.limits)
  if (key === turn.limitsKey) return
  if (!force && Date.now() - turn.limitsSentAt < LIMITS_EVERY_MS) return
  turn.limitsKey = key
  turn.limitsSentAt = Date.now()
  await report(io, 'limits', body)
}

export async function onTurnStart(io: Io, e: { text: string }): Promise<void> {
  const line = e.text.split('\n').find(part => part.trim()) || ''
  if (line) turn.intent = line.trim().slice(0, 200)
  turn.edited.clear()
  const first = !turn.announced
  turn.announced = true
  await report(io, 'turn', { state: 'working', ...(first ? { cwd: mod.cwd, version: mod.version } : {}) })
}

// After a tool ran: pick up the checklist and the edited files. Never changes the result.
export async function afterTool(io: Io, e: Loose, ran: Loose): Promise<void> {
  const tool = String(e.tool)
  if (ran.deny !== undefined || ran.isError === true) return
  if (CHECKLIST_TOOLS.has(tool) || tool === 'plan_update' || tool.endsWith('__plan_update')) {
    const items = checklistFrom(tool, e, ran.result)
    if (items) {
      turn.checklist = items
      turn.checklistPending = true
      if (Date.now() - turn.checklistSentAt >= CHECKLIST_EVERY_MS) await sendChecklist(io)
    }
  } else if (EDIT_TOOLS.has(tool)) {
    const file = String(e.file_path || e.notebook_path || '')
    if (file) turn.edited.add(file)
  }
}

export async function onTurnComplete(io: Io, e: Loose): Promise<void> {
  const counts: Record<string, number> = {}
  for (const [key, value] of Object.entries((e.usage ?? {}) as Loose)) if (typeof value === 'number') counts[key] = value
  await report(io, 'turn', {
    state: e.reason === 'answer' ? 'idle' : e.reason, usage: counts, durationMs: e.durationMs,
    receipt: mod.receipt, blocksSoFar: mod.blocksSoFar, answer: text(e.answer, 400),
  })
  mod.receipt = null
  await sendChecklist(io)
  if (turn.edited.size) {
    await report(io, 'edits', { paths: [...turn.edited].slice(-50) })
    await claimEdited(io)
  }
  await sendLimits(io, true)
}

// Plan limits: observe only, at most every 15 s while they move, and once more when the turn ends.
export async function onMeasure(io: Io, e: Loose): Promise<void> {
  turn.limits = e
  await sendLimits(io, false)
}

export async function onEnd(io: Io, reason: string): Promise<void> {
  await report(io, 'end', { reason })
}
