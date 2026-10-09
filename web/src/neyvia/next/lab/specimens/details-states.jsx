import { useState } from "react";
import { CheckCheck, MessageSquare, SearchX } from "lucide-react";

import { Button } from "../../nxPrimitives.jsx";
import { EmptyState, PRESS, Strike, useCalmLoading } from "../../details/nxDetails.jsx";
import "./details.css";

// Details: states (plan 17 A2). Empty states that point forward, a loading state that
// only shows when the wait is long enough to notice, and tasks that get crossed out.
export const title = "Details: empty, loading and done";

function CalmDemo() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState("Nothing loaded yet.");
  const show = useCalmLoading(loading);
  const load = ms => {
    setLoading(true);
    setTimeout(() => { setLoading(false); setResult(`Loaded in ${ms / 1000} s.`); }, ms);
  };
  return (
    <div className="nx-dl-calm">
      <div className="nx-lab-row">
        <Button size="sm" className={PRESS} disabled={loading} onClick={() => load(150)}>Load quickly</Button>
        <Button size="sm" className={PRESS} disabled={loading} onClick={() => load(1800)}>Load slowly</Button>
      </div>
      <div className="nx-dl-calm-box" aria-busy={loading}>
        {show ? <span className="nx-dl-skeleton" aria-label="Loading" role="status" /> : <p hidden={loading}>{result}</p>}
      </div>
    </div>
  );
}

const TASKS = ["Read the notes", "Write the summary", "Check the links"];

export default function DetailsStates() {
  const [done, setDone] = useState([true, false, false]);
  const [query, setQuery] = useState("invoice");
  return (
    <div className="nx-lab-sheet">
      <div className="nx-dl-grid">
        <EmptyState icon={MessageSquare} title="No messages yet" hint="Write below and the chat starts here." />
        {query ? (
          <EmptyState tone="filtered" icon={SearchX} title={`No chats match “${query}”`} hint="Try fewer words, or show every chat."
            action={{ label: "Clear the search", onClick: () => setQuery("") }} />
        ) : <p className="nx-dl-note">Showing every chat.</p>}
        <EmptyState tone="done" icon={CheckCheck} title="All caught up" hint="Nothing needs you right now." />
      </div>
      <CalmDemo />
      <ul className="nx-dl-tasks">
        {TASKS.map((text, index) => (
          <li key={text}>
            <label>
              <input type="checkbox" checked={done[index]} onChange={() => setDone(list => list.map((value, at) => (at === index ? !value : value)))} />
              <Strike on={done[index]}>{text}</Strike>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
