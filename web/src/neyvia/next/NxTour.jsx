import { Suspense, lazy, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Pause, Play, RotateCcw, X } from "lucide-react";

import { Icon, IconButton, Spinner, useMedia } from "./nxPrimitives.jsx";
import { locate, timeline } from "./nxOnboardingModel.js";

// The tour: a short "video" made of Neyvia's real screens. Each chapter is a
// scene in NxTourScenes.jsx that renders the shipped components (sidebar,
// chat, checklist, launcher, missions, workspace, PDF, dictation, phone) with
// example data and moves them by time, so it follows the theme and stays
// true to what the app does. The chapters shown are the ones the person's
// picks call for. Scenes load only when the tour opens.

// The canvas is drawn at a fixed size and scaled to fit. On a phone it is narrower and taller, so the
// scene is still readable (the chat scenes then drop their sidebar).
const SIZE_WIDE = { W: 1120, H: 640 };
const SIZE_NARROW = { W: 640, H: 720 };

const SceneHost = lazy(() => import("./NxTourScenes.jsx").then(module => ({
  default: function SceneHost({ id, p }) {
    const Scene = module.SCENES[id];
    return Scene ? <Scene p={p} /> : null;
  },
})));

function useFit(ref, W) {
  const [scale, setScale] = useState(0.5);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    const observer = new ResizeObserver(() => setScale(Math.min(node.clientWidth / W, 1.2)));
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref, W]);
  return scale;
}

/** The player: play/pause, chapter segments, skip; replayable. */
export function NxTour({ chapters, onDone, onChapter, autoPlay = true, extra = null }) {
  const reduced = useMedia("(prefers-reduced-motion: reduce)");
  const plan = useMemo(() => timeline(chapters), [chapters]);
  const [ms, setMs] = useState(0);
  const [playing, setPlaying] = useState(autoPlay && !reduced);
  const frame = useRef(null);
  const screen = useRef(null);
  const narrow = useMedia("(max-width: 760px)");
  const { W, H } = narrow ? SIZE_NARROW : SIZE_WIDE;
  const scale = useFit(screen, W);
  const { index, chapter, progress } = locate(plan, ms);
  const ended = ms >= plan.totalMs && plan.totalMs > 0;

  useEffect(() => {
    if (!playing) return undefined;
    let last = performance.now();
    const tick = now => {
      setMs(value => Math.min(plan.totalMs, value + (now - last)));
      last = now;
      frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame.current);
  }, [playing, plan.totalMs]);

  useEffect(() => { if (ended) setPlaying(false); }, [ended]);
  useEffect(() => { if (chapter) onChapter?.(chapter.id); }, [chapter?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const jump = useCallback(target => {
    const row = plan.chapters[Math.max(0, Math.min(plan.chapters.length - 1, target))];
    if (row) setMs(row.start + (reduced ? row.durationMs - 1 : 0));
  }, [plan, reduced]);

  const onKey = event => {
    if (event.key === " ") { event.preventDefault(); setPlaying(value => !value); }
    else if (event.key === "ArrowRight") jump(index + 1);
    else if (event.key === "ArrowLeft") jump(index - 1);
  };

  if (!chapter) return null;
  // With reduced motion, each chapter shows its finished frame; Next moves on.
  const p = reduced && !playing ? 1 : progress;
  return (
    <section className="nx-tour" aria-label="Neyvia tour" tabIndex={-1} onKeyDown={onKey}>
      <div className="nx-tour-screen" ref={screen} style={{ height: H * scale }}>
        <div className={`nx-tour-canvas${narrow ? " is-narrow" : ""}`} data-chapter={chapter.id} style={{ width: W, height: H, transform: `scale(${scale})` }} aria-hidden="true" inert>
          <Suspense fallback={<div className="nx-tour-loading"><Spinner size={18} /></div>}>
            <SceneHost key={chapter.id} id={chapter.id} p={p} />
          </Suspense>
        </div>
        {ended ? (
          <div className="nx-tour-end">
            <button type="button" className="nx-btn nx-btn-outline nx-btn-md" onClick={() => { setMs(0); setPlaying(true); }}><Icon as={RotateCcw} size={15} /><span className="nx-btn-label">Watch again</span></button>
          </div>
        ) : null}
      </div>
      <div className="nx-tour-caption" aria-live="polite">
        <small>{index + 1} of {plan.chapters.length} · Example data, not your chats</small>
        <h3>{chapter.title}</h3>
        <p>{chapter.caption}</p>
        {extra ? extra(chapter) : null}
      </div>
      <div className="nx-tour-controls">
        <IconButton icon={playing ? Pause : Play} label={playing ? "Pause" : ended ? "Play again" : "Play"}
          onClick={() => { if (ended) setMs(0); setPlaying(!playing); }} />
        <IconButton icon={ChevronLeft} label="Previous chapter" size="sm" onClick={() => jump(index - 1)} disabled={index === 0} />
        <div className="nx-tour-track" role="group" aria-label="Chapters">
          {plan.chapters.map((row, at) => (
            <button key={row.id} type="button" className="nx-tour-seg" title={row.title} aria-label={`Chapter ${at + 1}: ${row.title}`}
              aria-current={at === index || undefined} style={{ flexGrow: row.durationMs }} onClick={() => jump(at)}>
              <i style={{ width: `${at < index ? 100 : at === index ? progress * 100 : 0}%` }} />
            </button>
          ))}
        </div>
        <IconButton icon={ChevronRight} label="Next chapter" size="sm" onClick={() => jump(index + 1)} disabled={index === plan.chapters.length - 1} />
        <span className="nx-tour-time">{Math.round(plan.totalMs / 1000)} s</span>
        {onDone ? <IconButton icon={X} label="Close the tour" size="sm" onClick={onDone} /> : null}
      </div>
    </section>
  );
}
