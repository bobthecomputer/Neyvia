import { NxConnections } from "./NxConnections.jsx";

// The connections step.
//
// SLOT FOR TRACK CONN: `ConnectionsSlot` is where the one connections screen goes (every harness
// and provider with a clear state and a one-click connect that ends in a real round trip).
// Embedded: <NxConnections compact onConnected={...} /> from track CONN. The step's frame and title stay here.

/** The slot: CONN's one connections screen, compact. It fetches its own state. */
export function ConnectionsSlot() {
  return (
    <div className="nx-onb-slot" data-slot="connections">
      <NxConnections compact onConnected={() => {}} />
    </div>
  );
}

export function ConnectionsStep() {
  return (
    <div className="nx-onb-step is-wide">
      <div className="nx-onb-step-head">
        <h2 id="nx-onb-title">Connect your agents</h2>
        <p>Neyvia works with the agent apps you already use. Your own sign-ins stay yours, and Test runs one real prompt and tool call.</p>
      </div>
      <ConnectionsSlot />
    </div>
  );
}
