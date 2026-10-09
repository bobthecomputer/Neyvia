import { useState } from "react";
import { Plus, RefreshCw, Settings } from "lucide-react";

import { NxGrowingTree } from "../../NxGrowingTree.jsx";
import { Button, IconButton, Kbd, Segmented, Spinner, StatusDot } from "../../nxPrimitives.jsx";

// The shared primitives in every state the shell uses, as a reference sheet.
export const title = "Primitives";

export default function Primitives() {
  const [view, setView] = useState("all");
  return (
    <div className="nx-lab-sheet">
      <div className="nx-lab-row">
        <Button variant="primary" icon={Plus}>New chat</Button>
        <Button variant="outline">Open</Button>
        <Button>Cancel</Button>
        <Button variant="warn">Use plan limits</Button>
        <Button variant="primary" disabled>Unavailable</Button>
        <Button variant="primary" loading>Saving</Button>
        <IconButton icon={RefreshCw} label="Refresh" />
        <IconButton icon={Settings} label="Settings" active />
        <Kbd>Ctrl K</Kbd>
      </div>
      <div className="nx-lab-row">
        <span className="nx-lab-state"><StatusDot tone="live" pulse /> Running</span>
        <span className="nx-lab-state"><StatusDot tone="gold" /> Needs you</span>
        <span className="nx-lab-state"><StatusDot tone="green" /> Done</span>
        <span className="nx-lab-state"><StatusDot tone="red" /> Failed</span>
        <span className="nx-lab-state"><Spinner /> Loading</span>
        <span className="nx-tag">Beta</span>
        <NxGrowingTree size={24} />
      </div>
      <div className="nx-lab-row">
        <Segmented label="Show" value={view} onChange={setView}
          options={[{ value: "all", label: "All", count: 12 }, { value: "running", label: "Running", count: 2 }, { value: "paused", label: "Paused", disabled: true }, { value: "done", label: "Done" }]} />
        <input className="nx-input" placeholder="Search chats" aria-label="Search chats" />
      </div>
    </div>
  );
}
