// Agent roles from Neyvia (scout, builder, verifier), each with the model and effort Neyvia chose. Spawning is
// only refused when Neyvia says the plan is above its ceiling; there is no per-step model routing, because
// Neyvia already launches each turn with --model/--effort and a switch mid-turn would drop the cache.
import type { Io } from './client'
import { type Bootstrap, mod } from './session'

export async function registerRoles(io: Io, boot: Bootstrap): Promise<void> {
  for (const role of boot.roles) {
    try {
      await io.registerAgent({
        name: role.name, description: role.description, prompt: role.prompt,
        ...(role.model ? { model: role.model } : {}), ...(role.effort ? { effort: role.effort } : {}),
        ...(role.tools ? { tools: role.tools } : {}),
      })
    } catch (error) {
      await io.log(`neyvia: could not register role ${role.name}: ${String(error).slice(0, 120)}`)
    }
  }
}

// Why a new agent should not start now, or null.
export function spawnRefusal(): string | null {
  const budget = mod.boot?.budget
  return budget?.blockSpawn ? budget.reason || 'Neyvia says the plan is above its ceiling, so no new agents now.' : null
}
