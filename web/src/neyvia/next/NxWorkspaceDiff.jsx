import { memo, useMemo, useState } from "react";
import { ArrowLeft, ChevronDown, ChevronUp, FileText, TriangleAlert, WifiOff } from "lucide-react";

import { CopyCommand, Counts, FilePath, StateNote, StatusBadge } from "./NxWorkspaceBits.jsx";
import { Button, Icon, IconButton } from "./nxPrimitives.jsx";
import { useFileDiff } from "./nxWorkspaceHooks.js";
import { parsePatch } from "./nxWorkspaceModel.js";

const ROW_LIMIT = 3000;
const SIGNS = { add: "+", del: "−", ctx: "", note: "" };

export function flatten(parsed) {
  const rows = [];
  const many = parsed.files.length > 1;
  parsed.files.forEach((file, fileIndex) => {
    if (many) rows.push({ kind: "file", key: `f${fileIndex}`, text: file.newPath || `File ${fileIndex + 1}` });
    file.hunks.forEach((hunk, hunkIndex) => {
      rows.push({ kind: "hunk", key: `f${fileIndex}h${hunkIndex}`, text: hunk.header });
      hunk.lines.forEach((line, lineIndex) => rows.push({ kind: "line", key: `f${fileIndex}h${hunkIndex}l${lineIndex}`, line }));
    });
  });
  return rows;
}

export const DiffRows = memo(function DiffRows({ rows }) {
  return rows.map(row => {
    if (row.kind === "line") {
      const { line } = row;
      return (
        <div key={row.key} className={`nx-dl is-${line.t}`}>
          <span className="nx-dl-nums" aria-hidden="true"><i>{line.o ?? ""}</i><i>{line.n ?? ""}</i><b>{SIGNS[line.t]}</b></span>
          <span className="nx-dl-code">{line.text}</span>
        </div>
      );
    }
    return (
      <div key={row.key} className={`nx-dl is-${row.kind}`}>
        <span className="nx-dl-nums" aria-hidden="true" />
        <span className="nx-dl-code" title={row.text}>{row.text}</span>
      </div>
    );
  });
});

function DiffSkeleton() {
  return (
    <div className="nx-ws-skel-lines" aria-hidden="true">
      {[62, 88, 74, 40, 92, 56, 80, 68, 34, 84].map((width, index) => <span key={index} style={{ width: `${width}%` }} />)}
    </div>
  );
}

/** One file's unified diff inside the panel, with a way back and previous/next file. */
export function NxWorkspaceDiff({ sessionId, change, index, total, version, onBack, onStep }) {
  const { status, diff, error, retry } = useFileDiff(sessionId, change.path, version);
  const parsed = useMemo(() => (diff ? parsePatch(diff.patch) : null), [diff]);
  const rows = useMemo(() => (parsed ? flatten(parsed) : []), [parsed]);
  const [expanded, setExpanded] = useState("");
  const limit = expanded === change.path ? Infinity : ROW_LIMIT;
  const notes = parsed ? parsed.files.flatMap(file => file.notes) : [];
  const binary = Boolean(parsed?.files.some(file => file.binary));
  const additions = Number.isFinite(change.additions) ? change.additions : parsed?.additions;
  const deletions = Number.isFinite(change.deletions) ? change.deletions : parsed?.deletions;

  return (
    <section className="nx-ws-diffview" aria-label={`Diff of ${change.path}`}>
      <div className="nx-ws-diffbar">
        <Button size="sm" icon={ArrowLeft} onClick={onBack} autoFocus>Back to changes</Button>
        <span className="nx-ws-spacer" />
        {total > 1 ? (
          <>
            <span className="nx-ws-pos" aria-live="polite">{index + 1} of {total}</span>
            <IconButton size="sm" icon={ChevronUp} label="Previous file" disabled={index <= 0} onClick={() => onStep(-1)} />
            <IconButton size="sm" icon={ChevronDown} label="Next file" disabled={index >= total - 1} onClick={() => onStep(1)} />
          </>
        ) : null}
      </div>
      <div className="nx-ws-diffhead">
        <StatusBadge change={change} />
        <FilePath path={change.path} />
        <Counts additions={additions} deletions={deletions} />
      </div>
      {notes.length ? <p className="nx-ws-diffnotes">{notes.join(" · ")}</p> : null}

      {status === "loading" ? <DiffSkeleton /> : null}
      {status === "error" ? (
        <StateNote icon={error.kind === "offline" ? WifiOff : TriangleAlert} tone="red"
          title={error.kind === "offline" ? "Can't reach your PC" : "The diff could not be read"}
          action={<Button size="sm" variant="outline" onClick={retry}>Try again</Button>}>
          {error.message}
        </StateNote>
      ) : null}
      {status === "ready" && !rows.length ? (
        <StateNote icon={FileText} title={binary ? "Binary file" : "No text changes to show"}>
          {binary ? "Git can't show a binary file as lines. Open it on your PC to see what changed."
            : notes.length ? "Git reports only file-level changes here, such as a mode change." : "The file changed in a way git can't show as lines."}
        </StateNote>
      ) : null}
      {status === "ready" && rows.length ? (
        <div key={change.path} className="nx-diff nx-scroll" role="region" aria-label={`Changes in ${change.path}`} tabIndex={0}>
          <div className="nx-diff-body">
            <DiffRows rows={rows.length > limit ? rows.slice(0, limit) : rows} />
            {rows.length > limit ? (
              <button type="button" className="nx-diff-more" onClick={() => setExpanded(change.path)}>Show the remaining {rows.length - limit} lines</button>
            ) : null}
          </div>
        </div>
      ) : null}
      {status === "ready" && diff?.truncated ? (
        <p className="nx-ws-banner is-warn" role="status">
          <Icon as={TriangleAlert} size={14} />
          <span>This diff is large, so only the first part is shown. See the whole file on your PC:<br /><CopyCommand text={`git diff -- ${/\s/.test(change.path) ? `"${change.path}"` : change.path}`} /></span>
        </p>
      ) : null}
    </section>
  );
}
