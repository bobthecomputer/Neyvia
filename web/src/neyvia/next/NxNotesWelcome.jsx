import { CalendarDays, FileText, Lightbulb, Mic, Users } from "lucide-react";

import { Icon, ago } from "./nxPrimitives.jsx";

// What Notes shows when no note is open: a page of the notebook with an example note on it (so the
// app says what it is for), the starters that make a first note in one click, and, once notes
// exist, the most recent ones to pick up again. The example is labelled; nothing is saved until
// a starter is pressed.

const today = () => new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });

/** The starters: a title and a body each, plain Markdown. */
export const NOTE_STARTERS = [
  { id: "blank", label: "Blank note", icon: FileText, body: () => "" },
  { id: "meeting", label: "Meeting", icon: Users, body: () => `# Meeting · ${today()}\n\n## Who\n- \n\n## Decided\n- \n\n## Next\n- [ ] \n\n#meeting\n` },
  { id: "idea", label: "An idea", icon: Lightbulb, body: () => "# \n\nWhat if…\n\nWhy it matters:\n\n#idea\n" },
  { id: "today", label: "Today", icon: CalendarDays, body: () => `# ${today()}\n\n- \n\n#daily\n` },
];

function ExampleSheet() {
  return (
    <div className="nx-notes-sheet-wrap">
    <span className="nx-notes-sheet-under" aria-hidden="true" />
    <figure className="nx-notes-sheet" aria-label="An example note">
      <span className="nx-notes-sheet-tag">Example</span>
      <h3>Saturday market</h3>
      <ul>
        <li>Tomatoes and basil from the corner stall</li>
        <li>Ask about the seed swap in May</li>
        <li className="is-done">Bring the big basket</li>
      </ul>
      <p>Call Ana about Sunday's walk, she knows the coast path. <span>#plans</span> <span>#weekend</span></p>
    </figure>
    </div>
  );
}

export function NotesWelcome({ notes = [], onStart, onOpen, folder, busy = false }) {
  const recent = [...notes].sort((a, b) => String(b.changed || "").localeCompare(String(a.changed || ""))).slice(0, 3);
  return (
    <div className="nx-notes-welcome nx-scroll">
      <div className="nx-notes-welcome-inner">
        <ExampleSheet />
        <div className="nx-notes-welcome-copy">
          <h2>{recent.length ? "Pick up where you left off" : "Write it down"}</h2>
          <p>Notes are Markdown files in your notes folder. Start with a title, add <code>#tags</code> anywhere, or hold the mic and talk.</p>
          <div className="nx-notes-starters" role="group" aria-label="Start a note">
            {NOTE_STARTERS.map(starter => (
              <button key={starter.id} type="button" disabled={busy} onClick={() => onStart(starter.body())}>
                <Icon as={starter.icon} size={15} /><span>{starter.label}</span>
              </button>
            ))}
          </div>
          {recent.length ? (
            <ul className="nx-notes-recent" aria-label="Recent notes">
              {recent.map(row => (
                <li key={row.path}>
                  <button type="button" onClick={() => onOpen(row.path)}>
                    <strong>{row.title}</strong>
                    <span>{row.snippet || row.excerpt || "Empty note"}</span>
                    <small>{ago(row.changed)}</small>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="nx-notes-welcome-hint"><Icon as={Mic} size={13} /> Models can write here too: ask a chat to “add this to my notes”.</p>
          )}
          {/* The folder lives in the list's footer ("Notes folder · Change"), not as a raw path here. */}
        </div>
      </div>
    </div>
  );
}
