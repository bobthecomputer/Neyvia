# neyviaFrontendContracts

Provides FrontendContractError, equalContractValue, frontendContractBefore, FRONTEND_CONTRACTS for Neyvia's UI state and behavior.

- **Public API:** `FRONTEND_CONTRACTS`, `FrontendContractError`, `checkedFrontendAction`, `equalContractValue`, `frontendContractBefore`.
- **Manual:** [agents.cl](../../manuals/cl/agents.cl), [mission-plan.cl](../../manuals/cl/mission-plan.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [settings.cl](../../manuals/cl/settings.cl), [workspace.cl](../../manuals/cl/workspace.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `attention.activity`, `attention.description`, `attention.filter`, `attention.inbox`, `attention.projects`, `attention.recent`, `attention.sections`, `attention.showcase`, `attention.subagents`, `attention.thread`, `batch.prompts`, `batch.runtime-options`, `chat.cancellation-result`, `chat.cancelled`, `chat.runtime-source`, `chat.stopped-body`, `chat.stopped-visibility`, `ecosystem.benchmark`, `ecosystem.capture`, `ecosystem.conclude`, `ecosystem.submit`, `fabric.account`, `fabric.approval`, `fabric.insert`, `fabric.normalize`, `fabric.tone`, `factory.capability`, `factory.catalog`, `factory.commands`, `factory.create`, `factory.eligible`, `factory.handoff`, `factory.hash`, `factory.import`, `factory.job`, `factory.progress`, `factory.tone`, `mesh.boolean`, `mesh.bytes`, `mesh.count`, `mesh.duration`, `mesh.hash`, `mesh.snapshot`, `mesh.value`, `mission.artifacts`, `mission.delta`, `mission.live`, `office.classify`, `office.describe`, `office.execute`, `office.payload`, `permission.get`, `permission.grant`, `permission.normalize`, `permission.read`, `permission.runtime`, `permission.scope`, `permission.tools`, `permission.transfer`, `permission.write`, `preferences.motion`, `preferences.normalize`, `roles.default`, `roles.meta`, `roles.normalize`, `workflow.availability`, `workflow.explain`, `workflow.list`.
- **Dependencies:** [surface.neyviaChatContracts](../surface.neyviaChatContracts/README.md).
- **Owner:** Neyvia / neyviaFrontendContracts.
- **Files:** [web/src/neyvia/neyviaFrontendContracts.js](../../web/src/neyvia/neyviaFrontendContracts.js).
