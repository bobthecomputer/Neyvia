import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown, Bot, Brain, Check, ChevronRight, FileDiff, FilePen, FileText, Globe, ListChecks,
  Maximize2, MessageSquare, Plug, Search, ShieldAlert, SquareTerminal, Star, TriangleAlert, Wrench, X,
} from "lucide-react";

import NeyviaMessageBody from "../NeyviaMessageBody.jsx";
import { NxGrowingTree } from "./NxGrowingTree.jsx";
import { Attachments } from "./NxMedia.jsx";
import { Button, Icon, Spinner, compactTokens, local } from "./nxPrimitives.jsx";
import { answerRun, followThread, isRunActive, isWorkingElsewhere, loadEarlier, markSeen, useNx } from "./nxStore.js";
import { os, useOs } from "./nxOsStore.js";
import { morph } from "./nxMorph.js";
import { DiffRows, flatten } from "./NxWorkspaceDiff.jsx";
import { NxTaskFeedback } from "./NxTaskFeedback.jsx";
import { parsePatch } from "./nxWorkspaceModel.js";
import "./nxWorkspace.css";
import { callNx } from "./nxApi.js";
import { CopyButton as DetailCopyButton, EmptyState, useCalmLoading } from "./details/nxDetails.jsx";
import { detailExpanded, diffText, reasoningNotice, stripAnsi, toolDetails, toolFailed, toolMetadata, visibleTranscriptItems } from "./nxTransparencyModel.js";

const TOOL_ICONS = {
  command: SquareTerminal, edit: FilePen, read: FileText, search: Search, web: Globe, mcp: Plug, agent: Bot, other: Wrench,
};
const TOOL_VERBS = {
  command: ["Ran", "command", "commands"], edit: ["Edited", "file", "files"], read: ["Read", "file", "files"],
  search: ["Ran", "search", "searches"], web: ["Browsed", "page", "pages"], mcp: ["Used", "tool", "tools"],
  agent: ["Ran", "agent", "agents"], other: ["Used", "tool", "tools"],
};

/** A tool card grows into its full pane on the stage (nxMorph): an edit into its diff, a read into the file. */
function openInPane(event, kind, target) {
  const card = event.currentTarget.closest(".nx-tool, .nx-diff-card, .nx-thread-diff");
  morph(() => os.showPane(kind, target), ".nx-main .nx-work-app", { from: card });
}

const PANE_FOR = { edit: ["diff", "Show the change"], read: ["file", "Open the file"] };

/** Consecutive tool calls read as one step, the way Codex and Claude show them. */
function groupItems(items) {
  const blocks = [];
  for (const item of items) {
    const last = blocks.at(-1);
    if (item.kind === "tool" && last?.type === "tools") last.items.push(item);
    else if (item.kind === "tool") blocks.push({ type: "tools", key: item.id, items: [item] });
    else blocks.push({ type: item.kind, key: item.id, item });
  }
  return blocks;
}

function toolSummary(items) {
  const counts = new Map();
  for (const item of items) {
    const category = item.data?.category || "other";
    counts.set(category, (counts.get(category) || 0) + 1);
  }
  return [...counts.entries()].map(([category, count]) => {
    const [verb, one, many] = TOOL_VERBS[category] || TOOL_VERBS.other;
    return `${verb} ${count} ${count === 1 ? one : many}`;
  }).join(" · ");
}

function useExpanded(sessionId, level) {
  const key = `expand.${sessionId}.${level}`;
  const [open, setOpen] = useState(() => new Set(local.get(key, [])));
  useEffect(() => setOpen(new Set(local.get(key, []))), [key]);
  const toggle = useCallback(id => {
    setOpen(current => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      local.set(key, next.size ? [...next].slice(-200) : null);
      return next;
    });
  }, [key]);
  return [open, toggle];
}

// Copy shows a drawn check when it worked and says so when the clipboard refused (details library).
function CopyButton({ text, label = "Copy" }) {
  return <DetailCopyButton text={text} label={label} className="nx-copy" />;
}

/** A stack trace never fills the chat: one plain sentence first, the full text one click away. */
function summariseError(text) {
  const raw = String(text ?? "");
  const trace = /Traceback|File "[^"]+", line \d+|\^{3,}|~{3,}/.test(raw);
  if (!trace && raw.length <= 280) return { line: raw, rest: "" };
  const hits = [...raw.matchAll(/([A-Za-z_.]*(?:Refusal|Error|Exception)): ([^\n]{1,240})/g)];
  const last = hits.at(-1);
  const line = last ? `${last[1].split(".").at(-1)}: ${last[2].trim()}` : "This step stopped with an error.";
  return { line, rest: raw };
}
function ErrorText({ text }) {
  const { line, rest } = summariseError(text);
  if (!rest) return <>{line}</>;
  return (
    <span className="nx-errtext">
      <span>{line}</span>
      <details><summary>Technical details</summary><pre className="nx-pre" tabIndex={0}>{rest}</pre></details>
    </span>
  );
}

const ToolRow = memo(function ToolRow({ item, open, onToggle, sessionId }) {
  const [fullOutput, setFullOutput] = useState(null);
  const [outputError, setOutputError] = useState("");
  useEffect(() => {
    if (!open || item.data?.status === "running" || !item.data?.outputTruncated || fullOutput || !sessionId) return;
    let active = true;
    callNx("connected_session_tool_output_command", { id: sessionId, itemId: item.id })
      .then(result => { if (active) { setFullOutput(result); setOutputError(""); } })
      .catch(error => { if (active) setOutputError(error.message || "Full output could not be loaded."); });
    return () => { active = false; };
  }, [open, item.id, item.data?.status, item.data?.outputTruncated, sessionId, fullOutput]);
  const data = fullOutput ? { ...item.data, output: fullOutput.output, outputTruncated: fullOutput.truncated } : item.data || {};
  const running = data.status === "running";
  const failed = toolFailed(data);
  const fields = toolDetails(data).map(field => field.label === "Output" ? { ...field, text: stripAnsi(field.text) } : field);
  const metadata = toolMetadata(data);
  const pane = !running && typeof data.files?.[0] === "string" && data.files[0] ? PANE_FOR[data.category] : null;
  const hasBody = Boolean(fields.length || data.attachments?.length || metadata || pane || data.inputTruncated || data.outputTruncated);
  return (
    <div className={`nx-tool${failed ? " is-error" : ""}${running ? " is-running" : ""}`}>
      <button type="button" className="nx-tool-head" aria-expanded={hasBody ? open : undefined} disabled={!hasBody}
        onClick={() => hasBody && onToggle(item.id)}>
        <Icon as={TOOL_ICONS[data.category] || Wrench} size={14} className="nx-tool-icon" />
        <span className={`nx-tool-title${data.category === "command" ? " is-mono" : ""}`}>{data.title || data.name || "Tool"}</span>
        <span className="nx-tool-state">
          {running ? <Spinner size={11} /> : failed ? <Icon as={X} size={13} /> : data.exitCode != null && data.exitCode !== 0 ? <span className="nx-exit">exit {data.exitCode}</span> : null}
          {hasBody ? <Icon as={ChevronRight} size={13} className="nx-chev" /> : null}
        </span>
      </button>
      {open && hasBody ? (
        <div className="nx-tool-body">
          {fields.map(field => <div className="nx-tool-detail" key={field.label}>
            <span className="nx-detail-label">{field.label}</span>
            <div className="nx-pre-wrap">
              <pre tabIndex={0} aria-label={`${field.label} from ${data.name || "tool"}`} className={`nx-pre${field.label === "Output" && failed ? " is-error" : " is-input"}`}>{field.text}</pre>
              <CopyButton text={field.text} label={`Copy ${field.label.toLowerCase()}`} />
            </div>
          </div>)}
          {metadata ? <p className="nx-tool-meta">{metadata}</p> : null}
          {outputError ? <p className="nx-notice is-error" role="alert">{outputError}</p> : null}
          {["input", "args", "command", "output", "result"].filter(field => data[field + "Truncated"]).length ? <p className="nx-notice">{["input", "args", "command", "output", "result"].filter(field => data[field + "Truncated"]).join(", ")} shortened by the transport.</p> : null}
          <Attachments items={data.attachments} sessionId={sessionId} />
          {data.cwd ? <p className="nx-tool-cwd">{data.cwd}</p> : null}
          {pane ? (
            <button type="button" className="nx-tool-open" onClick={event => openInPane(event, pane[0], data.files[0])}>
              <Icon as={Maximize2} size={12} />{pane[1]}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
});

function ToolGroup({ items, expanded, onToggle, groupKey, sessionId, level }) {
  const running = items.some(item => item.data?.status === "running");
  const failures = items.filter(item => toolFailed(item.data)).length;
  const single = items.length === 1;
  const open = detailExpanded(groupKey, level, expanded) || single || failures > 0;
  const live = running ? items.findLast(item => item.data?.status === "running") : null;
  return (
    <div className={`nx-toolgroup${open ? " is-open" : ""}`}>
      {!single ? (
        <button type="button" className="nx-toolgroup-head" aria-expanded={open} onClick={() => onToggle(groupKey)}>
          <Icon as={ChevronRight} size={13} className="nx-chev" />
          {running ? <Spinner size={11} /> : null}
          <span>{running && live ? (live.data?.title || "Working") : toolSummary(items)}</span>
          {failures ? <span className="nx-toolgroup-fail">{failures} failed</span> : null}
        </button>
      ) : null}
      {open ? (
        <div className="nx-toolgroup-body">
          {items.map(item => <ToolRow key={item.id} item={item} open={detailExpanded(item.id, level, expanded, toolFailed(item.data))} onToggle={onToggle} sessionId={sessionId} />)}
        </div>
      ) : null}
    </div>
  );
}

function Reasoning({ item, open, onToggle, live, appName }) {
  const data = item.data || {};
  const thinking = Boolean(item.streaming || live);
  // Withheld reasoning remains visible after completion, at every detail level.
  if ((data.hidden || data.notice) && !data.summary) {
    return (
      <div className={`nx-reason is-hidden${thinking ? " is-live" : ""}`} role="status">
        <Icon as={Brain} size={13} /><span>{reasoningNotice(data, appName)}</span>
      </div>
    );
  }
  const text = String(data.summary || "").trim();
  const firstLine = text.split(/\n+/)[0].replace(/^[#*\s]+|\*+$/g, "");
  return (
    <div className={`nx-reason${open ? " is-open" : ""}${thinking ? " is-live" : ""}`}>
      <button type="button" className="nx-reason-head" aria-expanded={open} onClick={() => onToggle(item.id)}>
        <Icon as={Brain} size={13} />
        <span className="nx-reason-label">{data.exposure === "summary" || data.provider === "claude-code" ? thinking ? "Reasoning summary…" : "Reasoning summary" : thinking ? "Thinking…" : "Thinking"}</span>
        {!open ? <span className="nx-reason-peek">{firstLine}</span> : null}
        <Icon as={ChevronRight} size={13} className="nx-chev" />
      </button>
      {open ? <div className="nx-reason-body"><NeyviaMessageBody text={text} streaming={Boolean(item.streaming)} /></div> : null}
      {data.truncated ? <p className="nx-notice">Shared thinking shortened by the transport.</p> : null}
    </div>
  );
}

// An edit approval whose detail carries a unified diff (OpenCode's edit tool) shows the change itself, not its JSON.
function proposedChange(detail) {
  try {
    const value = JSON.parse(detail);
    const diff = typeof value?.diff === "string" ? value.diff : "";
    if (!diff.includes("@@")) return null;
    const parsed = parsePatch(diff);
    return parsed.files.length ? { path: value.filepath || value.filePath || value.path || parsed.files[0].newPath || "", rows: flatten(parsed) } : null;
  } catch { return null; }
}

function ProposedChange({ change }) {
  return (
    <div className="nx-pending-change">
      <p className="nx-tool-cwd">Change to {change.path.split(/[\\/]/).pop()}</p>
      <div className="nx-diff nx-scroll" role="region" aria-label={`Proposed change to ${change.path}`} tabIndex={0}>
        <div className="nx-diff-body"><DiffRows rows={change.rows} /></div>
      </div>
    </div>
  );
}

function PendingCard({ sessionId, request, appName }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [answers, setAnswers] = useState({});
  const respond = async (decision, submitted) => {
    setBusy(true); setError("");
    try { await answerRun(sessionId, { decision, ...(submitted ? { answers: submitted } : {}) }); }
    catch (failure) { setError(failure?.message || "That response didn't reach the app. Try again."); }
    finally { setBusy(false); }
  };
  const questions = request.questions || [];
  const choices = request.choices || ["approve", "deny"];
  // OpenCode's permission requests carry choices but no kind: without questions they are approvals.
  const approval = request.kind === "approval" || (!request.kind && !questions.length);
  const change = useMemo(() => (request.detail ? proposedChange(request.detail) : null), [request.detail]);
  return (
    <section className="nx-pending" aria-label={approval ? "Approval needed" : "Question"}>
      <header>
        <Icon as={approval ? ShieldAlert : ListChecks} size={15} />
        <strong>{request.title || (approval ? `${appName} needs your approval` : `${appName} has a question`)}</strong>
      </header>
      {change ? <ProposedChange change={change} /> : request.detail ? <p className="nx-pending-detail">{request.detail}</p> : null}
      {request.command ? <pre className="nx-pre is-input">{request.command}</pre> : null}
      {request.cwd ? (
        request.category === "folder_trust"
          ? <p className="nx-pending-folder">Folder: {request.cwd}</p>
          : <p className="nx-tool-cwd">in {request.cwd}</p>
      ) : null}
      {questions.map(question => (
        <fieldset key={question.id} className="nx-question">
          <legend>{question.header ? <span className="nx-question-header">{question.header}</span> : null}{question.question}</legend>
          {question.options?.length ? (
            <div className="nx-question-options">
              {question.options.map(option => {
                const value = option.label ?? option.value ?? String(option);
                return (
                  <button key={value} type="button" aria-pressed={answers[question.id] === value}
                    className={`nx-option${answers[question.id] === value ? " is-on" : ""}`}
                    onClick={() => setAnswers(current => ({ ...current, [question.id]: value }))}>
                    <strong>{value}</strong>{option.description ? <span>{option.description}</span> : null}
                  </button>
                );
              })}
            </div>
          ) : null}
          <input className="nx-input" type={question.isSecret ? "password" : "text"} autoComplete="off"
            placeholder={question.options?.length ? "Or type your own answer" : "Your answer"}
            value={question.options?.some(option => (option.label ?? option.value) === answers[question.id]) ? "" : answers[question.id] || ""}
            onChange={event => setAnswers(current => ({ ...current, [question.id]: event.target.value }))} />
        </fieldset>
      ))}
      {error ? <p className="nx-pending-error" role="alert">{error}</p> : null}
      <div className="nx-pending-actions">
        {approval ? (
          <>
            {choices.includes("deny") ? <Button variant="outline" disabled={busy} onClick={() => respond("deny")}>Deny</Button> : null}
            {choices.includes("approve") ? <Button variant="primary" disabled={busy} onClick={() => respond("approve")}>{busy ? "Sending…" : "Approve"}</Button> : null}
          </>
        ) : (
          <Button variant="primary" disabled={busy || questions.some(question => !String(answers[question.id] || "").trim())}
            onClick={() => respond("approve", answers)}>{busy ? "Sending…" : "Send answer"}</Button>
        )}
      </div>
    </section>
  );
}

function Diff({ item, open, onToggle }) {
  const data = item.data || {};
  const files = data.files || [];
  const patch = diffText(data);
  return <section className="nx-thread-diff" aria-label="File changes">
    <button type="button" className="nx-diff-card" aria-expanded={open} onClick={() => onToggle(item.id)}>
      <Icon as={FileDiff} size={14} />
      <span>{files.length} file{files.length === 1 ? "" : "s"} changed</span>
      <span className="nx-diff-stat"><b className="is-add">+{files.reduce((sum, file) => sum + (file.additions || 0), 0)}</b> <b className="is-del">−{files.reduce((sum, file) => sum + (file.deletions || 0), 0)}</b></span>
      <Icon as={ChevronRight} size={13} className="nx-chev" />
    </button>
    {open ? <div className="nx-tool-body">
      {data.scope === "replacement" ? <p className="nx-notice">Changed text from the edit arguments.</p> : data.scope === "new-content" ? <p className="nx-notice">New file content; the previous content wasn’t supplied.</p> : null}
      {files.map((file, index) => <p className="nx-tool-cwd" key={file.path || index}>{typeof file === "string" ? file : file.path || file.name}</p>)}
      {patch ? <div className="nx-pre-wrap"><pre className="nx-pre is-input" tabIndex={0} aria-label="File diff">{patch}</pre><CopyButton text={patch} label="Copy diff" /></div> : <p className="nx-notice">The transport didn’t share a diff for this edit.</p>}
      {data.truncated ? <p className="nx-notice">Diff shortened by the transport.</p> : null}
      <button type="button" className="nx-tool-open" onClick={event => openInPane(event, "diff", "workspace")}><Icon as={Maximize2} size={12} />Open the changes</button>
    </div> : null}
  </section>;
}

function HelperReport({ data }) {
  const [open, setOpen] = useState(false);
  const report = String(data.report || "Report unavailable");
  return <div className={`nx-notice nx-helper-report is-${data.level || "info"}${open ? " is-open" : ""}`}>
    <button type="button" className="nx-helper-report-toggle" aria-expanded={open}
      aria-label={`${open ? "Collapse report" : "Helper reported"} · ${data.helper}`} onClick={() => setOpen(!open)}>
      <span className="nx-helper-report-heading"><Icon as={Bot} size={13} /><span>Helper reported · {data.helper}</span><Icon as={ChevronRight} size={13} className="nx-chev" /></span>
      {!open ? <span className="nx-helper-report-preview">{report.slice(0, 180)}{report.length > 180 ? "…" : ""}</span> : null}
    </button>
    {open ? <div className="nx-helper-report-body"><NeyviaMessageBody text={report} /></div> : null}
    {data.truncated ? <span>Report shortened by the transport.</span> : null}
  </div>;
}

function Block({ block, expanded, onToggle, appName, sessionId, liveId, level }) {
  if (block.type === "tools") return <ToolGroup items={block.items} expanded={expanded} onToggle={onToggle} groupKey={`g:${block.key}`} sessionId={sessionId} level={level} />;
  const { item } = block;
  const data = item.data || {};
  switch (item.kind) {
    case "user":
      return (
        <div className={`nx-msg-user${item.optimistic ? " is-pending" : ""}`}>
          <div className="nx-bubble">
            {data.text ? <div className="nx-user-text">{data.text}</div> : null}
            <Attachments items={data.attachments} sessionId={sessionId} />
          </div>
        </div>
      );
    case "assistant":
      return (
        <div className="nx-msg-assistant">
          <NeyviaMessageBody text={data.text || ""} streaming={Boolean(item.streaming)} revealKey={item.id} />
          <Attachments items={data.attachments} sessionId={sessionId} />
        </div>
      );
    case "reasoning": {
      const claude = item.data?.provider === "claude-code";
      const toggleId = claude ? `reasoning.${item.id}` : item.id;
      return <Reasoning item={item} open={claude ? expanded.has(toggleId) : detailExpanded(item.id, level, expanded)} onToggle={() => onToggle(toggleId)} live={item.id === liveId} appName={appName} />;
    }
    case "compaction":
      return (
        <div className={`nx-divider is-${data.state || "completed"}`} role="separator">
          <span>{data.state === "started" ? <><Spinner size={10} /> Compacting context…</>
            : data.state === "failed" ? "Compacting failed"
            : `Compacted${data.beforeTokens && data.afterTokens ? ` · ${compactTokens(data.beforeTokens)} → ${compactTokens(data.afterTokens)} tokens` : ""}`}</span>
        </div>
      );
    case "goal":
      return <div className="nx-goal-line"><Icon as={Star} size={13} /><span>{data.state === "cleared" ? "Goal cleared" : data.state === "achieved" ? "Goal achieved" : "Goal"}{data.text ? `: ${data.text}` : ""}</span></div>;
    case "diff":
      return <Diff item={item} open={detailExpanded(item.id, level, expanded)} onToggle={onToggle} />;
    case "approval":
    case "question":
      return data.decision || data.answers ? (
        <div className="nx-notice"><Icon as={data.decision === "deny" ? X : Check} size={13} />{data.title || (item.kind === "approval" ? "Approval" : "Question")} · {data.decision === "deny" ? "denied" : "answered"}</div>
      ) : null;
    case "notice":
      if (data.helper) return <HelperReport data={data} />;
      return <div className={`nx-notice is-${data.level || "info"}`}>{data.level === "error" ? <Icon as={TriangleAlert} size={13} /> : null}<ErrorText text={data.text} /></div>;
    default:
      return null;
  }
}

/** Scroll that sticks to the newest message unless the reader scrolled up. */
function useStickToBottom(dependency) {
  const scroller = useRef(null);
  const stuck = useRef(true);
  const [away, setAway] = useState(false);
  const onScroll = useCallback(() => {
    const element = scroller.current;
    if (!element) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    stuck.current = distance < 80;
    setAway(distance > 400);
  }, []);
  useLayoutEffect(() => {
    const element = scroller.current;
    if (element && stuck.current) element.scrollTop = element.scrollHeight;
  }, [dependency]);
  const toBottom = useCallback(() => {
    const element = scroller.current;
    if (!element) return;
    stuck.current = true;
    element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
  }, []);
  return { scroller, onScroll, away, toBottom };
}

export function NxThread({ sessionId, appName }) {
  const thread = useNx(state => state.threads[sessionId]);
  const run = useNx(state => state.runs[sessionId]);
  const level = useOs(state => state.transparency);
  const [expanded, onToggle] = useExpanded(sessionId, level);
  const items = thread?.items || [];
  const blocks = useMemo(() => groupItems(visibleTranscriptItems(items, level)), [items, level]);
  const lastSignature = `${level}:${items.length}:${items.at(-1)?.id}:${String(items.at(-1)?.data?.text || items.at(-1)?.data?.output || items.at(-1)?.data?.summary || "").length}:${run?.pendingRequest?.requestId || ""}`;
  const { scroller, onScroll, away, toBottom } = useStickToBottom(lastSignature);
  // A chat that opens quickly never flashes the skeleton; a slow one shows it after 240 ms.
  const skeleton = useCalmLoading(!thread || thread.status === "loading");

  useEffect(() => {
    if (thread?.status === "ready" && !document.hidden) markSeen(sessionId);
  }, [sessionId, thread?.status, items.length]);

  const session = useNx(state => state.sessions[sessionId]);
  const elsewhere = isWorkingElsewhere(session, run) && thread?.status === "ready";
  useEffect(() => {
    if (!elsewhere) return undefined;
    const tick = () => { if (!document.hidden) void followThread(sessionId); };
    tick();
    const timer = setInterval(tick, 2500);
    document.addEventListener("visibilitychange", tick);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", tick); };
  }, [elsewhere, sessionId]);

  // Working here (a Neyvia run) or in the Claude app / Codex: either way the chat shows it is alive.
  const working = isRunActive(run) || elsewhere;
  const last = items.at(-1);
  const liveId = working ? last?.id : null;
  const runningTool = working && last?.kind === "tool" && last?.data?.status === "running";
  const workingLabel = session?.status === "waiting_approval" ? "Waiting for your approval…"
    : runningTool ? `Running ${last.data?.category === "command" ? "a command" : "a tool"}…`
    : elsewhere ? `Working elsewhere in ${session?.app === "codex" ? "Codex" : session?.live_owner === "cli" ? "a Claude Code terminal" : "the Claude app"}…`
    : "Working…";

  if (!thread || thread.status === "loading") {
    return (
      <div className="nx-thread-state" aria-busy="true">
        {skeleton ? <div className="nx-thread-skeleton">{Array.from({ length: 5 }, (_, index) => <span key={index} className={index % 2 ? "is-right" : ""} />)}</div> : null}
      </div>
    );
  }
  if (thread.status === "error" && !items.length) {
    return (
      <div className="nx-thread-state">
        <div className="nx-empty">
          <Icon as={TriangleAlert} size={20} />
          <strong>{thread.code === "network" ? "Can't reach your PC" : "This chat couldn't be opened"}</strong>
          <p>{thread.code === "network" ? "The conversation lives on your PC. Reconnect and it will load; nothing is lost." : thread.error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="nx-thread-wrap">
      <div className="nx-thread nx-scroll" ref={scroller} onScroll={onScroll}>
        <div className="nx-thread-col">
          {thread.transportTruncated ? <p className="nx-notice" role="status">A live update was shortened. {thread.error ? "The complete thread could not be loaded. Reconnect to try again." : "Loading the complete thread…"}</p> : null}
          {thread.hasEarlier ? (
            <button type="button" className="nx-earlier" disabled={thread.loadingEarlier} onClick={() => void loadEarlier(sessionId)}>
              {thread.loadingEarlier ? <><Spinner size={11} /> Loading earlier messages…</> : "Show earlier messages"}
            </button>
          ) : null}
          {!items.length ? <EmptyState icon={MessageSquare} title="No messages yet" hint="Write below and the chat starts here." /> : null}
          {blocks.map(block => <Block key={block.key} block={block} expanded={expanded} onToggle={onToggle} appName={appName} sessionId={sessionId} liveId={liveId} level={level} />)}
          {run?.pendingRequest ? <PendingCard sessionId={sessionId} request={run.pendingRequest} appName={appName} /> : null}
          {working && !run?.pendingRequest && !items.at(-1)?.streaming && last?.kind !== "reasoning" ? (
            <div className="nx-working" role="status" aria-label={`${appName} is working`}>
              <NxGrowingTree size={22} />
              <span className="nx-working-label">{workingLabel}</span>
            </div>
          ) : null}
          {run?.state === "failed" && run.error ? <div className="nx-notice is-error"><Icon as={TriangleAlert} size={13} /><ErrorText text={run.error} /></div> : null}
          {run?.state === "interrupted" ? <div className="nx-notice"><Icon as={X} size={13} />{run.error || "Stopped. Nothing was resent."}</div> : null}
          {!working && run?.impact ? (
            <details className="nx-notice" aria-label="Edited files impact">
              <summary>Changed files · {run.impact.files?.length || 0} · Also check</summary>
              <pre style={{ whiteSpace: "pre-wrap", font: "inherit" }}>{run.impact.ok ? run.impact.text : `Impact unavailable: ${run.impact.error}`}</pre>
            </details>
          ) : null}
          {!working && !run?.pendingRequest ? <NxTaskFeedback sessionId={sessionId} run={run} /> : null}
        </div>
      </div>
      {away ? (
        <button type="button" className="nx-jump" onClick={toBottom} aria-label="Jump to latest"><Icon as={ArrowDown} size={15} /></button>
      ) : null}
    </div>
  );
}
