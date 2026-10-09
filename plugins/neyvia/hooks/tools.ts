// Neyvia's tools as native tools of this Claude Code session. The list comes from the bootstrap; a call is one
// POST to Neyvia, which keeps every approval it already asks for. Tools sit behind ToolSearch so the tool list
// stays small and identical from turn to turn.
import { type Io, type Loose, MOD_PATH, request, runId, text } from './client'
import { type Bootstrap, mod } from './session'

const PREFIX = 'mcp__neyvia__'
const MAX_RESULT = 60_000

export async function registerTools(io: Io, boot: Bootstrap): Promise<void> {
  const sorted = [...boot.tools].sort((x, y) => Number(x.deferred) - Number(y.deferred) || x.name.localeCompare(y.name))
  // Keep discovery in the first prompt; the broad catalog stays behind ToolSearch.
  // A later bootstrap retries only missing registrations, including failed ones.
  await Promise.all(sorted.map(async tool => {
    if (mod.registered.has(`${PREFIX}${tool.name}`)) return
    try {
      const done = await io.registerTool({
        name: tool.name, description: tool.description, inputSchema: tool.inputSchema, isDeferred: tool.deferred,
      })
      mod.registered.set(String((done as unknown as Loose | undefined)?.tool || `${PREFIX}${tool.name}`), tool.neyviaName)
    } catch (error) {
      await io.log(`neyvia: could not register ${tool.name}: ${String(error).slice(0, 120)}`)
    }
  }))
}

// An MCP tool's output is a plain string (the engine checks a hook's answer against that shape); a failure is a deny.
const reply = (message: string, isError: boolean): { result: string; deny?: undefined } | { deny: string; result?: undefined } => (isError ? { deny: message } : { result: message })

// A call of one of Neyvia's tools: null when the call is not ours.
export async function serveTool(io: Io, e: Loose): Promise<ReturnType<typeof reply> | null> {
  const neyviaName = mod.registered.get(String(e.tool))
  if (!neyviaName) return null
  const { tool: _tool, tool_use_id: _id, agentId: _agent, ...args } = e
  const answer = await request(io, 'POST', `${MOD_PATH}/tool`, {
    body: { session: mod.session, run: await runId(io), tool: neyviaName, args }, timeoutMs: null, event: 'tool.call',
  })
  // No answer can mean Neyvia is down or only slow (the engine stops waiting first): a slow action may still land, so say so.
  if (!answer) return reply('Neyvia did not answer in time. The action may still have run: check its state (a read, or the procedure observer) before trying again.', true)
  const body = answer.json || {}
  if (body.ok === false || answer.status >= 400) return reply(text(body.error || `Neyvia answered ${answer.status}`, 2000), true)
  const result = body.result
  return reply(text(typeof result === 'string' ? result : JSON.stringify(result ?? {}), MAX_RESULT), false)
}

export const bridgeFailed = () => reply('The Neyvia tool bridge failed. Try again.', true)
