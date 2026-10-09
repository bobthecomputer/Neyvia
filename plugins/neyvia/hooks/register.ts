// Neyvia mod 0.2.0: Neyvia's side of a Claude Code session. Neyvia keeps the plan-limits loop inside Claude Code
// itself; this module gives that loop Neyvia's tools, rules, contracts and awareness, and reports back.
// Everything talks to the local Neyvia app only (loopback), races a 2 s timer, and passes through when Neyvia is
// slow or absent. It never reads or sends a Claude credential and never approves anything.
//
// Claude Code's validator follows `$` only inside the file it is handed to, and refuses two unmatched hooks on one
// event. So this file holds every `on(...)` and every `$.noun.verb` call, as one hook per event, and the other
// modules are plain logic over the small `Io` set of closures that `makeIo` builds here.
import type { EngineInterface, Register } from 'claude-code'
import { type Io, type Loose, configure } from './client'
import { loadBootstrap, stateDiff, withContext, withSection } from './context'
import { stopBlock } from './gate'
import { inboxNote, afterTurn } from './inbox'
import { afterTool, report, onEnd, onMeasure, onTurnComplete, onTurnStart } from './report'
import { registerRoles, spawnRefusal } from './roles'
import { askIfHeld, guardTool } from './rules'
import { identify, mod } from './session'
import { bridgeFailed, registerTools, serveTool } from './tools'

function makeIo($: EngineInterface): Io {
  return {
    backend: () => $.env.get('NEYVIA_BACKEND'),
    legacyBackend: () => $.env.get('NEYVIA_UI_BACKEND_URL'),
    runId: () => $.env.get('NEYVIA_RUN_ID'),
    // $.env.get takes a literal name (the validator reads which variables a mod touches), so each one is spelled out.
    env: name => name === 'NEYVIA_MOD_TOKEN' ? $.env.get('NEYVIA_MOD_TOKEN')
      : name === 'NEYVIA_MOD_TOKEN_FILE' ? $.env.get('NEYVIA_MOD_TOKEN_FILE')
      : name === 'USERPROFILE' ? $.env.get('USERPROFILE')
      : $.env.get('HOME'),
    readText: async path => String(await $.fs.read(path)),
    fetch: (url, init) => $.http.fetch(url, init),
    sleep: (ms, signal) => $.clock.sleep(ms, signal ? { signal } : undefined),
    status: line => Promise.resolve($.ui.status(line)),
    log: line => Promise.resolve($.ui.log(line, { to: 'debug' })),
    toast: line => Promise.resolve($.ui.toast(line)),
    get: key => $.store.get(key),
    set: (key, value) => $.store.set(key, value as never),
    keys: async () => (await $.store.keys()) as string[],
    remove: key => $.store.delete(key),
    sessionId: async () => String(await $.session.id()),
    stat: async path => ((await $.fs.stat(path, { resolve: true })) as unknown as { realPath?: string }),
    registerTool: spec => $.tool.register(spec),
    registerAgent: spec => $.agent.register(spec),
  }
}

export const register: Register = (on, options) => {
  configure(options)

  on('session.start', async ($, e, next) => {
    const started = await next(e)
    const io = makeIo($)
    mod.cwd = e.cwd
    try {
      mod.version = (await $.session.version()).version
    } catch { /* the version is a nicety */ }
    await identify(io)
    const boot = await loadBootstrap(io, 'session.start')
    if (boot) {
      await registerTools(io, boot)
      await report(io, 'session', { cwd: e.cwd, version: mod.version, runId: mod.run })
      await registerRoles(io, boot)
    }
    return started
  }).catch(($, e, next) => next(e))

  on('prompt.compose', async ($, e, next) => withSection(await next(e))).catch(($, e, next) => next(e))

  on('prompt.context', async ($, e, next) => withContext(makeIo($), await next(e))).catch(($, e, next) => next(e))

  on('turn.start', async ($, e, next) => {
    await onTurnStart(makeIo($), e)
    return next(e)
  }).catch(($, e, next) => next(e))

  on('prompt.submit', async ($, e, next) => {
    const io = makeIo($)
    const notes: string[] = []
    const diff = await stateDiff(io)
    if (diff) notes.push(`Neyvia update: ${diff}`)
    const mail = await inboxNote(io)
    if (mail) notes.push(mail)
    return next(notes.length ? { ...e, context: [...(e.context ?? []), ...notes] } : e)
  }).catch(($, e, next) => next(e))

  // Neyvia's own tools: answered here, never reaching the engine.
  on('tool.call', { tool: /^mcp__neyvia__/ }, async ($, e, next) => {
    const served = await serveTool(makeIo($), e as unknown as Loose)
    return served ?? next(e)
  }).catch(($, e, next) => (next.called ? next(e) : bridgeFailed()))

  // Every other tool: refuse first, run, then observe. A guard that throws lets the call through (fail open).
  on('tool.call', async ($, e, next) => {
    const io = makeIo($)
    const refusal = await guardTool(io, e as unknown as Loose).catch(() => null)
    if (refusal) return { deny: refusal }
    const ran = await next(e)
    await afterTool(io, e as unknown as Loose, ran as unknown as Loose).catch(() => undefined)
    return ran
  }).catch(($, e, next) => next(e))

  on('tool.check', async ($, e, next) => askIfHeld(makeIo($), e, await next(e))).catch(($, e, next) => next(e))

  // The stop gate. A block is returned WITHOUT next, so Neyvia's settings Stop hook never sees the stop.
  on('classic.Stop', async ($, e, next) => {
    const block = await stopBlock(makeIo($), e)
    return block ? { block } : next(e)
  }).catch(($, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {
    if (!e.agentId) {
      const io = makeIo($)
      await onTurnComplete(io, e as unknown as Loose)
      await afterTurn(io)
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  on('agent.spawn', async ($, e, next) => {
    const why = spawnRefusal()
    return why ? { deny: why } : next(e)
  }).catch(($, e, next) => next(e))

  on('session.measure', async ($, e, next) => {
    await onMeasure(makeIo($), e as unknown as Loose)
    return next(e)
  }).catch(($, e, next) => next(e))

  on('session.end', async ($, e, next) => {
    await onEnd(makeIo($), e.reason)
    return next(e)
  }).catch(($, e, next) => next(e))
}
