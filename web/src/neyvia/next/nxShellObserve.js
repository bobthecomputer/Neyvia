// Observe the mounted shell after React commits, including async app loads.
// Event delivery identifies the requested subject; actual DOM is the witness.
import { useEffect } from 'react';
import { useOs } from './nxOsStore.js';
import { reportAppState } from './nxBus.js';
import { frameVisibility } from './nxFrameVisibility.js';
import { shellOutcomes } from './nxOutcomeObservation.js';

const deliveries = [];
const ACTIONS = new Set(['view.theme', 'view.arrange', 'view.scene', 'view.float', 'view.place', 'notes.open', 'onboarding.open', 'notify', 'pane.show', 'app.open', 'stage.close', 'mobile.preview']);
const runtimeId = `shell-${crypto.randomUUID()}`;
export function shellDelivered(message) {
  if (!ACTIONS.has(message.action)) return;
  deliveries.push({ id: String(message.id), action: message.action, payload: message.payload });
  if (deliveries.length > 24) deliveries.shift();
}
const visible = element => {
  if (!element) return false;
  const rect = element.getBoundingClientRect(), css = getComputedStyle(element);
  return rect.width > 0 && rect.height > 0 && css.display !== 'none' && css.visibility !== 'hidden';
};
// An agent's readiness probe must be answered by this actual mounted runtime.
export const shellReady = expected => expected === runtimeId && visible(document.querySelector('.nx-root'));
const digest = async text => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)))]
  .map(byte => byte.toString(16).padStart(2, '0')).join('');

export function useShellObservation(rootRef) {
  const state = useOs(value => value);
  useEffect(() => {
    let cancelled = false;
    const report = async () => {
      const root = rootRef.current;
      if (!root || !visible(root)) return;
      const editor = root.querySelector('.nx-notes-text');
      const projected = {
        runtimeId, deliveries: [...deliveries], stage: state.stage, windows: state.windows, layout: state.layout,
        density: state.density, theme: state.theme, scenes: state.scenes,
        bubbles: state.bubbles.map(row => row.id), bubbleOpen: state.bubbleOpen,
        onboarding: state.onboarding,
        dom: { mounted: true, visible: true, theme: root.getAttribute('data-nx-theme'), outcomes: shellOutcomes(root),
          stage: { mounted: visible(root.querySelector('.nx-stage-body')) && !root.querySelector('.nx-stage-loading, .nx-pane-honest'), app: state.stage?.app || null },
          windows: [...root.querySelectorAll('[data-window]')].map(element => ({ id: element.dataset.window, placement: element.dataset.placement, visible: visible(element), width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height })),
          surfaceBubbles: [...root.querySelectorAll('[data-bubble-for]')].filter(visible).map(element => element.dataset.bubbleFor),
          regions: [...root.querySelectorAll('[data-region], .nx-main')].filter(visible).map(element => ({
            id:element.dataset.region || 'main', side:element.dataset.side, x:element.getBoundingClientRect().x })),
          notes: { mounted:visible(editor), appMounted:visible(root.querySelector('.nx-notes')), textHash:editor ? await digest(editor.value) : null },
          phone: { mounted:visible(root.querySelector('.nx-ms-phone')), frames:[...root.querySelectorAll('.nx-ms-phone iframe')].filter(visible).map(element => ({
            src:element.src, width:element.getBoundingClientRect().width, height:element.getBoundingClientRect().height,
            visibility:frameVisibility(element),
            runtime: { path:element.closest('.nx-ms-phone-box')?.dataset.previewPath || '',
              instance:element.closest('.nx-ms-phone-box')?.dataset.previewInstance || '',
              text:element.closest('.nx-ms-phone-box')?.dataset.previewText || '' },
          })) },
          setup: { mounted:visible(document.querySelector('.nx-onb')), step:document.querySelector('.nx-onb-rail-step.is-on')?.innerText || '' },
          storage: { warningVisible:visible(document.querySelector('.neyvia-storage-warning')), text:document.querySelector('.neyvia-storage-warning')?.innerText || '' },
          bubbles: [...root.querySelectorAll('.nx-bubble-float')].filter(visible).map(element=>element.dataset.sessionId).filter(Boolean),
          notices: [...root.querySelectorAll('.nx-toast')].filter(visible).map(element=>({id:element.dataset.noticeId,text:element.querySelector('.nx-toast-text span')?.innerText || ''})),
        },
      };
      if (!cancelled) reportAppState('shell', projected);
    };
    const timer = setTimeout(report, 30), heartbeat = setInterval(report, 700);
    return () => { cancelled = true; clearTimeout(timer); clearInterval(heartbeat); };
  }, [state, rootRef]);
}
