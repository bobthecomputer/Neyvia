import { useState } from "react";
import { Save, X } from "lucide-react";

import { Button, Icon } from "../../nxPrimitives.jsx";
import { ConfirmInPlace, CopyButton, PRESS } from "../../details/nxDetails.jsx";
import "./details.css";

// Details: actions (plan 17 A2). Press feedback on buttons, copy that shows it worked,
// and a delete that asks right where the button was.
export const title = "Details: actions";

function SceneChip({ name, onDelete, defaultOpen = false }) {
  return (
    <ConfirmInPlace question={`Delete ${name}?`} confirmLabel="Delete" doneText={`${name} deleted`} onConfirm={onDelete} defaultOpen={defaultOpen}>
      {open => (
        <span className="nx-dl-chip">
          <span>{name}</span>
          <button type="button" className="nx-dl-chip-x" aria-label={`Delete ${name}`} onClick={open}><Icon as={X} size={11} /></button>
        </span>
      )}
    </ConfirmInPlace>
  );
}

export default function DetailsActions() {
  const [scenes, setScenes] = useState(["Reading", "Two chats", "Focus"]);
  return (
    <div className="nx-lab-sheet">
      <div className="nx-lab-row">
        <Button variant="primary" icon={Save} className={PRESS}>Save</Button>
        <Button variant="outline" className={PRESS}>Open</Button>
        <CopyButton text="C:\Users\user\Projects\Neyvia" label="Copy path" />
        <CopyButton text="npm run frontend:build" label="Copy" showLabel />
      </div>
      <div className="nx-lab-row">
        {scenes.map((name, index) => (
          <SceneChip key={name} name={name} defaultOpen={index === scenes.length - 1}
            onDelete={() => setScenes(list => list.filter(item => item !== name))} />
        ))}
        {scenes.length < 3 ? <Button size="sm" className={PRESS} onClick={() => setScenes(["Reading", "Two chats", "Focus"])}>Bring them back</Button> : null}
      </div>
    </div>
  );
}
