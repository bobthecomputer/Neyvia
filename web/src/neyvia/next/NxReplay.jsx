import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Bell, Brain, FileDiff, Pause, Play, RotateCcw, Scissors, Wrench } from "lucide-react";

import "./nxReplay.css";
import { NxGrowingTree } from "./NxGrowingTree.jsx";
import { Icon, IconButton, Segmented, Spinner, local } from "./nxPrimitives.jsx";
import { loadEarlier, openThread, useNx } from "./nxStore.js";
import { IDLE_CAP_MS, SPEEDS, buildTimeline, formatSpan, playbackMs, recordedAt, timelineMarks, visibleCount } from "./nxReplayModel.js";

// Accelerated playback of a whole chat: everything the user and the agents
// did, in order, at 1-60x, with long silences squeezed (nxReplayModel). Opens
// as a stage pane ("replay", target = chat id) so the live chat stays docked.

const MAX_PAGES = 12; // up to ~2,000 items of history
const SHOWN = 160; // render the latest items only; older ones scroll away
const plain = text => String(text || "").replace(/(\*\*|__|`+|^#+\s|^>\s)/gm, "");
const clock = ms => (ms ? new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "");

function useWholeHistory(sessionId) {
  const thread = useNx(state => state.threads[sessionId]);
  const [pages, setPages] = useState(0);
  useEffect(() => { void openThread(sessionId); setPages(0); }, [sessionId]);
  useEffect(() => {
    if (thread?.status !== "ready" || !thread.hasEarlier || thread.loadingEarlier || pages >= MAX_PAGES) return;
    setPages(count => count + 1);
    void loadEarlier(sessionId);
  }, [sessionId, thread?.status, thread?.hasEarlier, thread?.loadingEarlier, pages]);
  const complete = thread?.status === "ready" && (!thread.hasEarlier || pages >= MAX_PAGES) && !thread.loadingEarlier;
  return { thread, complete, truncated: complete && thread?.hasEarlier };
}

function Entry({ item }) {
  const data = item.data || {};
  switch (item.kind) {
    case "user": return <p className="nx-rp-user">{plain(data.text)}</p>;
    case "assistant": return <p className="nx-rp-reply">{plain(data.text)}</p>;
    case "reasoning": return <p className="nx-rp-line is-faint"><Icon as={Brain} size={13} />Thought</p>;
    case "tool":
      return (
        <p className={`nx-rp-line is-tool${data.status === "error" ? " is-error" : ""}`}>
          <Icon as={Wrench} size={13} /><span>{data.title || data.name || "Tool"}</span>
        </p>
      );
    case "diff": return <p className="nx-rp-line is-tool"><Icon as={FileDiff} size={13} />{data.title || "Changed files"}</p>;
    case "approval":
    case "question": return <p className="nx-rp-line is-needs"><Icon as={Bell} size={13} />{data.title || (item.kind === "approval" ? "Asked for approval" : "Asked a question")}</p>;
    case "compaction": return <p className="nx-rp-line is-faint"><Icon as={Scissors} size={13} />Context compacted</p>;
    default: return data.title || data.text ? <p className="nx-rp-line is-faint">{plain(data.title || data.text).slice(0, 160)}</p> : null;
  }
}

export function NxReplay({ sessionId, title }) {
  const { thread, complete, truncated } = useWholeHistory(sessionId);
  const [speed, setSpeed] = useState(() => local.get("replay.speed", 16));
  const [squeeze, setSqueeze] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);
  const feed = useRef(null);
  const track = useRef(null);
  const timeline = useMemo(() => buildTimeline(thread?.items, { idleCap: squeeze ? IDLE_CAP_MS : Infinity }), [thread?.items, squeeze]);
  const marks = useMemo(() => timelineMarks(timeline), [timeline]);
  const end = timeline.replayDuration;
  const count = visibleCount(timeline, pos);
  const shown = timeline.entries.slice(Math.max(0, count - SHOWN), count);

  // Start playing once the whole history is in.
  useEffect(() => { if (complete && timeline.entries.length) setPlaying(true); }, [complete, timeline.entries.length]);
  useEffect(() => {
    if (!playing) return undefined;
    let frame = 0;
    let last = performance.now();
    const step = now => {
      const dt = now - last;
      last = now;
      setPos(current => {
        const next = Math.min(end, current + dt * speed);
        if (next >= end) setPlaying(false);
        return next;
      });
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [playing, speed, end]);
  useLayoutEffect(() => { if (playing && feed.current) feed.current.scrollTop = feed.current.scrollHeight; }, [count, playing]);

  const seekTo = clientX => {
    const rect = track.current.getBoundingClientRect();
    setPos(Math.min(1, Math.max(0, (clientX - rect.left) / rect.width)) * end);
  };
  const onTrackKey = event => {
    const stepMs = end * (event.shiftKey ? 0.1 : 0.02);
    const next = { ArrowLeft: pos - stepMs, ArrowRight: pos + stepMs, Home: 0, End: end }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    setPos(Math.min(end, Math.max(0, next)));
  };
  const toggle = () => { if (pos >= end) setPos(0); setPlaying(value => !value); };

  if (!thread || !complete) {
    return (
      <div className="nx-rp-loading"><Spinner size={16} /><span>Gathering the whole session{thread?.items?.length ? ` · ${thread.items.length} items so far` : ""}…</span></div>
    );
  }
  if (!timeline.entries.length) return <div className="nx-rp-loading"><span>This chat has nothing to replay yet.</span></div>;

  return (
    <section className="nx-rp" aria-label={`Replay of ${title || "this chat"}`}
      onKeyDown={event => { if (event.key === " " && event.target === event.currentTarget) { event.preventDefault(); toggle(); } }} tabIndex={-1}>
      <header className="nx-rp-head">
        {playing ? <NxGrowingTree size={22} /> : <NxGrowingTree size={22} growing={false} />}
        <div className="nx-rp-facts">
          <strong>{formatSpan(timeline.duration)} of work</strong>
          <span>{timeline.entries.length} events · plays in {formatSpan(playbackMs(timeline, speed))} at {speed}×{truncated ? " · latest part only" : ""}</span>
        </div>
        <span className="nx-rp-clock" title="When this happened">{clock(recordedAt(timeline, pos))}</span>
      </header>

      <div className="nx-rp-feed nx-scroll" ref={feed} aria-live="off">
        {count > SHOWN ? <p className="nx-rp-line is-faint">{count - SHOWN} earlier events</p> : null}
        {shown.map(({ item }) => <div key={item.id} className="nx-rp-entry"><Entry item={item} /></div>)}
      </div>

      <footer className="nx-rp-controls">
        <IconButton icon={playing ? Pause : Play} label={playing ? "Pause" : pos >= end ? "Play again" : "Play"} onClick={toggle} />
        <IconButton icon={RotateCcw} label="Back to the start" onClick={() => setPos(0)} />
        <div className="nx-rp-track" ref={track} role="slider" tabIndex={0} aria-label="Replay position"
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={end ? Math.round((pos / end) * 100) : 0} aria-valuetext={clock(recordedAt(timeline, pos))}
          onKeyDown={onTrackKey}
          onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); setPlaying(false); seekTo(event.clientX); }}
          onPointerMove={event => { if (event.buttons === 1) seekTo(event.clientX); }}>
          {marks.map(mark => <i key={mark.id} className={`nx-rp-mark is-${mark.tone}`} style={{ left: `${mark.at * 100}%` }} />)}
          <span className="nx-rp-fill" style={{ transform: `scaleX(${end ? pos / end : 0})` }} />
          <span className="nx-rp-head-dot" style={{ left: `${end ? (pos / end) * 100 : 0}%` }} />
        </div>
        <Segmented size="sm" label="Speed" value={speed}
          options={SPEEDS.map(value => ({ value, label: `${value}×` }))}
          onChange={value => { setSpeed(value); local.set("replay.speed", value); }} />
        <label className="nx-rp-squeeze" title="Shorten long silences to a short pause">
          <input type="checkbox" checked={squeeze} onChange={event => setSqueeze(event.target.checked)} />Skip idle
        </label>
      </footer>
    </section>
  );
}
