import { useEffect,  useRef, useState } from "react";
import {
  Aperture,
  AudioLines,
  Check,
  ChevronLeft,
  Clock3,
  Download,
  FileJson,
  FileText,
  Film,
  ImagePlus,
  Link2,
  Pause,
  Play,
  Plus,
  RotateCcw,
    ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import "./neyviaNativeStudios.css";

const STUDIO_META = Object.freeze({
  "lumaforge": {
    id: "lumaforge",
    name: "LumaForge",
    eyebrow: "Image studio",
    summary: "Adjust an image, create a variation, and export at full size.",
    logo: "/neyvia-apps/lumaforge.png?v=20260728",
    icon: Aperture,
  },
  "frameweave": {
    id: "frameweave",
    name: "Frameweave",
    eyebrow: "Video studio",
    summary: "Review footage, mark a cut, and capture a frame.",
    logo: "/neyvia-apps/frameweave.png?v=20260728",
    icon: Film,
  },
  "citecraft": {
    id: "citecraft",
    name: "CiteCraft",
    eyebrow: "Research studio",
    summary: "Keep sources, claims, and research notes together.",
    logo: "/neyvia-apps/citecraft.png?v=20260728",
    icon: FileText,
  },
  "aegis-range": {
    id: "aegis-range",
    name: "Aegis Range",
    eyebrow: "Authorized security workspace",
    summary: "Set the scope of an authorized assessment and record your findings.",
    logo: "/neyvia-apps/aegis-range.png?v=20260728",
    icon: ShieldCheck,
  },
  "cueledger": {
    id: "cueledger",
    name: "CueLedger",
    eyebrow: "Audio review studio",
    summary: "Listen, mark a moment, and keep your notes in time.",
    logo: "/neyvia-apps/cueledger.png?v=20260728",
    icon: AudioLines,
  },
});

function loadStored(key, fallback) {
  if (typeof window === "undefined") return fallback;
  try {
    const value = window.localStorage.getItem(key);
    return value ? { ...fallback, ...JSON.parse(value) } : fallback;
  } catch {
    return fallback;
  }
}

function usePersistentProject(key, fallback) {
  const [project, setProject] = useState(() => loadStored(key, fallback));
  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(project));
    } catch {
      // The workspace remains usable when storage is unavailable.
    }
  }, [key, project]);
  return [project, setProject];
}

function downloadText(filename, value, type = "text/plain;charset=utf-8") {
  const blob = new Blob([value], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function formatTimestamp(value) {
  const seconds = Math.max(0, Number(value) || 0);
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${remainder.toFixed(2).padStart(5, "0")}`;
}

function StudioLogo({ meta }) {
  const Icon = meta.icon;
  const [broken, setBroken] = useState(false);
  return (
    <span className="neyvia-studio-logo" data-logo={meta.id}>
      {!broken ? (
        <img alt="" onError={() => setBroken(true)} src={meta.logo} />
      ) : (
        <Icon aria-hidden="true" size={23} />
      )}
    </span>
  );
}

function StudioShell({ children, meta, onSetSurface, status }) {
  useEffect(() => {
    window.scrollTo({ left: 0, top: 0 });
  }, [meta.id]);

  return (
    <section
      aria-label={`${meta.name} workspace`}
      className="neyvia-native-studio"
      data-native-studio={meta.id}
    >
      <header className="neyvia-studio-header">
        <button
          aria-label="Back to Neyvia"
          className="neyvia-studio-back"
          onClick={() => onSetSurface?.("agent")}
          type="button"
        >
          <ChevronLeft aria-hidden="true" size={17} />
        </button>
        <StudioLogo meta={meta} />
        <div className="neyvia-studio-title">
          <span>{meta.eyebrow}</span>
          <h1>{meta.name}</h1>
          <p>{meta.summary}</p>
        </div>
        <div className="neyvia-studio-save-state" data-state={status?.tone || "saved"}>
          <Check aria-hidden="true" size={14} />
          <span>{status?.label || "Saved locally"}</span>
        </div>
      </header>
      {children}
    </section>
  );
}

const IMAGE_DEFAULT = Object.freeze({
  name: "Untitled image",
  source: "",
  prompt: "Editorial geometric composition, luminous cobalt glass, deep black ground, precise modern identity",
  brightness: 100,
  contrast: 100,
  saturation: 100,
  blur: 0,
  rotation: 0,
  flipX: false,
  background: "#111317",
  receipt: null,
});

function LumaForge({ callBackend, meta, onSetSurface }) {
  const [project, setProject] = usePersistentProject("neyvia.studio.lumaforge.v1", IMAGE_DEFAULT);
  const [runtimeSource, setRuntimeSource] = useState(project.source || "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const canvasRef = useRef(null);
  const [loadedImage, setLoadedImage] = useState(null);

  useEffect(() => {
    setLoadedImage(null);
    if (!runtimeSource) return;
    let cancelled = false;
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => {
      if (cancelled) return;
      setLoadedImage(image);
      setMessage(`Loaded image · ${image.naturalWidth} × ${image.naturalHeight}`);
    };
    image.onerror = () => { if (!cancelled) setMessage("The selected image could not be rendered. Choose another image."); };
    image.src = runtimeSource;
    return () => { cancelled = true; if (runtimeSource.startsWith('blob:')) URL.revokeObjectURL(runtimeSource); };
  }, [runtimeSource]);

  useEffect(() => {
    if (!loadedImage) {
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");
      if (context) {
        canvas.width = 960;
        canvas.height = 720;
        const gradient = context.createLinearGradient(0, 0, canvas.width, canvas.height);
        gradient.addColorStop(0, "#0d1220");
        gradient.addColorStop(0.55, project.background);
        gradient.addColorStop(1, "#1749ff");
        context.fillStyle = gradient;
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.fillStyle = "rgba(255,255,255,.92)";
        context.font = "600 34px system-ui";
        context.fillText("LumaForge", 42, 64);
        context.fillStyle = "rgba(255,255,255,.55)";
        context.font = "16px system-ui";
        context.fillText("Upload or generate an image to begin.", 44, 96);
      }
      return;
    }
    const image = loadedImage;
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");
      if (!context) return;
      const sideways = project.rotation % 180 !== 0;
      canvas.width = sideways ? image.naturalHeight : image.naturalWidth;
      canvas.height = sideways ? image.naturalWidth : image.naturalHeight;
      context.save();
      context.fillStyle = project.background;
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.filter = `brightness(${project.brightness}%) contrast(${project.contrast}%) saturate(${project.saturation}%) blur(${project.blur}px)`;
      context.translate(canvas.width / 2, canvas.height / 2);
      context.rotate((project.rotation * Math.PI) / 180);
      context.scale(project.flipX ? -1 : 1, 1);
      const width = image.naturalWidth;
      const height = image.naturalHeight;
      context.drawImage(image, -width / 2, -height / 2, width, height);
      context.restore();
  }, [
    loadedImage,
    project.background,
    project.blur,
    project.brightness,
    project.contrast,
    project.flipX,
    project.rotation,
    project.saturation,
  ]);

  const update = (field, value) => setProject(current => ({ ...current, [field]: value }));
  const resetAdjustments = () =>
    setProject(current => ({
      ...current,
      brightness: 100,
      contrast: 100,
      saturation: 100,
      blur: 0,
      rotation: 0,
      flipX: false,
    }));

  const onFile = event => {
    const file = event.target.files?.[0];
    if (!file) return;
    const source = URL.createObjectURL(file);
    setRuntimeSource(source);
    setProject(current => ({ ...current, name: file.name, receipt: null, source: "" }));
    setMessage(`Opening ${file.name}…`);
  };

  const generate = async () => {
    if (!project.prompt.trim() || typeof callBackend !== "function") return;
    setBusy(true);
    setMessage("Generating through the installed image skill…");
    try {
      const requestId = `lumaforge-${Date.now().toString(36)}`;
      const result = await callBackend("image_playground_operation_command", {
        requestId,
        operation: "generate",
        providerId: "codex_subscription_gpt_image2",
        size: "1024x1024",
        canvas: { width: 1024, height: 1024 },
        prompt: { text: project.prompt.trim() },
        skillInvocation: {
          skillId: "imagegen",
          mode: "installed-skill",
          requireReceipt: true,
        },
      });
      const receipt = result?.receipt?.skillInvocation;
      const dimensionsMatch = result?.receipt?.dimensionCheck?.matches !== false;
      if (
        result?.providerStatus !== "available"
        || !result?.previewUrl
        || receipt?.status !== "executed"
        || receipt?.skillId !== "imagegen"
      ) {
        throw new Error(result?.message || "The image provider did not return a verified artifact.");
      }
      setRuntimeSource(result.previewUrl);
      setProject(current => ({
        ...current,
        name: `Generated ${new Date().toLocaleTimeString()}`,
        source: result.previewUrl,
        receipt: {
          requestId: result.requestId || requestId,
          artifactPath: result.outputArtifactPath || result.imagePath || "",
          manifestPath: result.manifestPath || "",
          model: result.model || "gpt-image-2",
          provider: result.provider || "openai-codex",
          skillSha256: receipt.skillSha256 || "",
          dimensionsMatch,
          semanticReview: result?.receipt?.semanticReview || "required",
        },
      }));
      setMessage(
        dimensionsMatch
          ? "Generated image and skill receipt are attached. Visual review is still required."
          : "Artifact received, but its dimensions do not match the requested canvas. Do not publish it.",
      );
    } catch (error) {
      setMessage(String(error?.message || error || "Image generation failed."));
    } finally {
      setBusy(false);
    }
  };

  const exportPng = () => {
    const canvas = canvasRef.current;
    if (!canvas || !loadedImage) return;
    const anchor = document.createElement("a");
    anchor.download = `${project.name.replace(/\.[^.]+$/, "") || "lumaforge"}-export.png`;
    anchor.href = canvas.toDataURL("image/png");
    anchor.click();
    setMessage("PNG exported from the visible canvas.");
  };

  return (
    <StudioShell
      meta={meta}
      onSetSurface={onSetSurface}
      status={{
        label: project.receipt
          ? project.receipt.dimensionsMatch === false
            ? "Dimension mismatch"
            : "Visual review required"
          : runtimeSource ? "Image open" : "Choose an image",
        tone: project.receipt?.dimensionsMatch === false ? "warning" : "saved",
      }}
    >
      <div className="neyvia-studio-grid neyvia-lumaforge-grid">
        <aside className="neyvia-studio-rail" aria-label="Image project controls">
          <label className="neyvia-studio-file-button">
            <Upload aria-hidden="true" size={16} />
            <span>Open image</span>
            <input accept="image/*" data-studio-file-input="lumaforge" onChange={onFile} type="file" />
          </label>
          <label>
            Project name
            <input
              onChange={event => update("name", event.target.value)}
              value={project.name}
            />
          </label>
          <div className="neyvia-studio-control-group">
            {[
              ["brightness", "Brightness", 25, 175],
              ["contrast", "Contrast", 25, 175],
              ["saturation", "Saturation", 0, 200],
              ["blur", "Blur", 0, 12],
            ].map(([field, label, min, max]) => (
              <label key={field}>
                <span><span>{label}</span><output>{project[field]}</output></span>
                <input
                  max={max}
                  min={min}
                  onChange={event => update(field, Number(event.target.value))}
                  type="range"
                  value={project[field]}
                />
              </label>
            ))}
          </div>
          <div className="neyvia-studio-inline-actions">
            <button onClick={() => update("rotation", (project.rotation + 90) % 360)} type="button">
              Rotate
            </button>
            <button onClick={() => update("flipX", !project.flipX)} type="button">
              Flip
            </button>
            <button aria-label="Reset image adjustments" onClick={resetAdjustments} type="button">
              <RotateCcw aria-hidden="true" size={15} />
            </button>
          </div>
        </aside>
        <main className="neyvia-studio-canvas-wrap">
          <canvas
            aria-label="LumaForge image canvas"
            height="720"
            ref={canvasRef}
            width="960"
          />
          <div className="neyvia-studio-canvas-actions">
            <button className="is-primary" disabled={!loadedImage} onClick={exportPng} type="button">
              <Download aria-hidden="true" size={15} />
              Export PNG
            </button>
            <span role="status">{message || "Your original file stays unchanged."}</span>
          </div>
        </main>
        <aside className="neyvia-studio-inspector" aria-label="AI image generation">
          <div>
            <span>Generate</span>
            <strong>Create an image</strong>
          </div>
          <label>
            Prompt
            <textarea
              onChange={event => update("prompt", event.target.value)}
              rows="7"
              value={project.prompt}
            />
          </label>
          <button className="is-primary" disabled={busy || !project.prompt.trim()} onClick={generate} type="button">
            <Sparkles aria-hidden="true" size={15} />
            {busy ? "Generating…" : "Generate image"}
          </button>
          {project.receipt ? (
            <dl className="neyvia-studio-receipt">
              <div><dt>Provider</dt><dd>{project.receipt.provider}</dd></div>
              <div><dt>Model</dt><dd>{project.receipt.model}</dd></div>
              <div><dt>Request</dt><dd>{project.receipt.requestId}</dd></div>
              <div><dt>Skill hash</dt><dd>{project.receipt.skillSha256.slice(0, 12) || "recorded"}</dd></div>
            </dl>
          ) : (
            <div className="neyvia-studio-empty">
              <ImagePlus aria-hidden="true" size={20} />
              <p>Describe the image you want. Results appear on the canvas.</p>
            </div>
          )}
        </aside>
      </div>
    </StudioShell>
  );
}

const VIDEO_DEFAULT = Object.freeze({
  name: "Untitled cut",
  inPoint: 0,
  outPoint: 0,
  duration: 0,
  notes: "",
  sourceName: "",
});

function Frameweave({ meta, onSetSurface }) {
  const [project, setProject] = usePersistentProject("neyvia.studio.frameweave.v1", VIDEO_DEFAULT);
  const [videoUrl, setVideoUrl] = useState("");
  const [playing, setPlaying] = useState(false);
  const [message, setMessage] = useState("Load local footage to create an edit decision.");
  const videoRef = useRef(null);
  const posterRef = useRef(null);

  const update = (field, value) => setProject(current => ({ ...current, [field]: value }));
  const onFile = event => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (videoUrl) URL.revokeObjectURL(videoUrl);
    setVideoUrl(URL.createObjectURL(file));
    setProject(current => ({ ...current, name: file.name.replace(/\.[^.]+$/, ""), sourceName: file.name }));
    setMessage(`Loaded ${file.name}.`);
  };
  const onMetadata = event => {
    const duration = Number(event.currentTarget.duration || 0);
    setProject(current => ({ ...current, duration, inPoint: 0, outPoint: duration }));
  };
  const togglePlayback = async () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      video.currentTime = Math.max(project.inPoint, Math.min(video.currentTime, project.outPoint || video.duration));
      try { await video.play(); } catch { setPlaying(false); setMessage("Playback could not start. Choose a supported video file."); }
    } else {
      video.pause();
      setPlaying(false);
    }
  };
  const onTimeUpdate = event => {
    if (project.outPoint > 0 && event.currentTarget.currentTime >= project.outPoint) {
      event.currentTarget.pause();
      event.currentTarget.currentTime = project.inPoint;
      setPlaying(false);
    }
  };
  const captureFrame = () => {
    const video = videoRef.current;
    const canvas = posterRef.current;
    const context = canvas?.getContext("2d");
    if (!video || !canvas || !context || !video.videoWidth) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const anchor = document.createElement("a");
    anchor.download = `${project.name || "frameweave"}-frame.png`;
    anchor.href = canvas.toDataURL("image/png");
    anchor.click();
    setMessage(`Captured frame at ${video.currentTime.toFixed(2)} seconds.`);
  };
  const exportDecision = () => {
    const receipt = {
      schema: "neyvia.frameweave.edl/v1",
      exportedAt: new Date().toISOString(),
      project: project.name,
      source: project.sourceName,
      durationSeconds: project.duration,
      inPointSeconds: project.inPoint,
      outPointSeconds: project.outPoint,
      selectedDurationSeconds: Math.max(0, project.outPoint - project.inPoint),
      notes: project.notes,
    };
    downloadText(`${project.name || "frameweave"}-edit.json`, JSON.stringify(receipt, null, 2), "application/json");
    setMessage("Edit decision JSON exported.");
  };

  return (
    <StudioShell meta={meta} onSetSurface={onSetSurface} status={{label:videoUrl ? 'Footage open' : project.sourceName ? 'Relink footage' : 'Choose footage'}}>
      <div className="neyvia-studio-grid neyvia-frameweave-grid">
        <aside className="neyvia-studio-rail">
          <label className="neyvia-studio-file-button">
            <Upload aria-hidden="true" size={16} />
            <span>Open footage</span>
            <input accept="video/*" data-studio-file-input="frameweave" onChange={onFile} type="file" />
          </label>
          <label>
            Project
            <input onChange={event => update("name", event.target.value)} value={project.name} />
          </label>
          <label>
            Cut in
            <input
              max={project.duration || 0}
              min="0"
              onChange={event => update("inPoint", Math.min(Number(event.target.value), project.outPoint))}
              step="0.01"
              type="number"
              value={project.inPoint}
            />
          </label>
          <label>
            Cut out
            <input
              max={project.duration || 0}
              min={project.inPoint}
              onChange={event => update("outPoint", Number(event.target.value))}
              step="0.01"
              type="number"
              value={project.outPoint}
            />
          </label>
          <label>
            Edit notes
            <textarea onChange={event => update("notes", event.target.value)} rows="6" value={project.notes} />
          </label>
        </aside>
        <main className="neyvia-studio-video-stage">
          {videoUrl ? (
            <video
              aria-label="Frameweave video preview"
              onEnded={() => setPlaying(false)}
              onLoadedMetadata={onMetadata}
              onPause={() => setPlaying(false)}
              onPlay={() => setPlaying(true)}
              onError={() => {setPlaying(false);setMessage('This video could not be loaded. Choose a supported video file.');}}
              onTimeUpdate={onTimeUpdate}
              ref={videoRef}
              src={videoUrl}
            />
          ) : (
            <div className="neyvia-studio-empty is-stage">
              <Film aria-hidden="true" size={36} />
              <strong>No footage loaded</strong>
              <p>Files stay on this device; only the edit decision is persisted.</p>
            </div>
          )}
          <div className="neyvia-video-transport">
            <button aria-label={playing ? "Pause video" : "Play video"} disabled={!videoUrl} onClick={togglePlayback} type="button">
              {playing ? <Pause aria-hidden="true" size={17} /> : <Play aria-hidden="true" size={17} />}
            </button>
            <div className="neyvia-video-time">
              <span style={{ left: `${project.duration ? (project.inPoint / project.duration) * 100 : 0}%` }} />
              <span style={{ left: `${project.duration ? (project.outPoint / project.duration) * 100 : 100}%` }} />
            </div>
            <output>{Math.max(0, project.outPoint - project.inPoint).toFixed(2)} s selected</output>
          </div>
          <canvas hidden ref={posterRef} />
          <div className="neyvia-studio-canvas-actions">
            <button disabled={!videoUrl} onClick={captureFrame} type="button">
              <Download aria-hidden="true" size={15} />
              Capture frame
            </button>
            <button className="is-primary" disabled={!project.sourceName} onClick={exportDecision} type="button">
              <FileJson aria-hidden="true" size={15} />
              Export edit decision
            </button>
            <span role="status">{message}</span>
          </div>
        </main>
      </div>
    </StudioShell>
  );
}

const RESEARCH_DEFAULT = Object.freeze({
  title: "Untitled evidence review",
  question: "",
  sources: [],
  claims: [],
});

// A small, real example review: shown faded while the ledger is empty, and loadable as a start.
const RESEARCH_EXAMPLE = Object.freeze({
  title: "Do street trees cool a city?",
  question: "How much do street trees lower summer street temperatures, and when?",
  sources: [
    { id: "source-s1", title: "Ziter et al. 2019, PNAS: Scale-dependent interactions between tree canopy cover and impervious surfaces reduce daytime urban heat", url: "https://doi.org/10.1073/pnas.1817561116", note: "Canopy above about 40% cools a block by up to 5 °C in the day; the effect grows with canopy share." },
    { id: "source-s2", title: "Bowler et al. 2010, Landscape and Urban Planning: Urban greening to cool towns and cities", url: "https://doi.org/10.1016/j.landurbplan.2010.05.006", note: "Meta-analysis: parks are about 1 °C cooler than built areas in the day." },
  ],
  claims: [
    { id: "claim-c1", text: "Dense street canopy lowers daytime street temperature by a few degrees.", sourceIds: ["source-s1", "source-s2"] },
    { id: "claim-c2", text: "The cooling needs enough canopy; a few scattered trees do little.", sourceIds: ["source-s1"] },
  ],
});

// Sources are numbered in the order they were added; a claim cites them as [1], [2]. Internal ids stay internal.
const sourceRefs = (sources, ids) => ids.map(id => {
  const index = sources.findIndex(source => source.id === id);
  return index >= 0 ? `[${index + 1}]` : "A removed source";
}).join(" ");

function ResearchExample({ kind }) {
  if (kind === "source") {
    const source = RESEARCH_EXAMPLE.sources[0];
    return (
      <li className="neyvia-research-example" aria-hidden="true">
        <Link2 aria-hidden="true" size={16} />
        <div><strong>{source.title}</strong><small>[1] · example</small><p>{source.note}</p></div>
      </li>
    );
  }
  const claim = RESEARCH_EXAMPLE.claims[0];
  return (
    <li className="neyvia-research-example" data-linked="true" aria-hidden="true">
      <span>01</span>
      <div><strong>{claim.text}</strong><small>{sourceRefs(RESEARCH_EXAMPLE.sources, claim.sourceIds)} · example</small></div>
    </li>
  );
}

function Citecraft({ meta, onSetSurface }) {
  const [project, setProject] = usePersistentProject("neyvia.studio.citecraft.v1", RESEARCH_DEFAULT);
  const [sourceDraft, setSourceDraft] = useState({ title: "", url: "", note: "" });
  const [claimDraft, setClaimDraft] = useState({ claim: "", sourceIds: "" });
  const [message, setMessage] = useState("Add traceable sources before writing conclusions.");
  const update = (field, value) => setProject(current => ({ ...current, [field]: value }));
  const addSource = event => {
    event?.preventDefault();
    if (!sourceDraft.title.trim() || !sourceDraft.url.trim()) return;
    const source = { ...sourceDraft, id: `source-${Date.now().toString(36)}` };
    setProject(current => ({ ...current, sources: [...current.sources, source] }));
    setSourceDraft({ title: "", url: "", note: "" });
    setMessage("Source added to the ledger.");
  };
  const addClaim = event => {
    event?.preventDefault();
    if (!claimDraft.claim.trim()) return;
    // People pick sources by their number in the ledger; ids stay internal.
    const sourceIds = claimDraft.sourceIds.split(/[\s,]+/).map(value => value.replace(/^\[|\]$/g, "").trim()).filter(Boolean)
      .map(value => (/^\d+$/.test(value) ? project.sources[Number(value) - 1]?.id : value)).filter(Boolean);
    const claim = { id: `claim-${Date.now().toString(36)}`, text: claimDraft.claim.trim(), sourceIds };
    setProject(current => ({ ...current, claims: [...current.claims, claim] }));
    setClaimDraft({ claim: "", sourceIds: "" });
    setMessage(sourceIds.length ? "Claim added with its sources." : "Claim added. Link the sources that back it.");
  };
  const loadExample = () => {
    setProject({ ...RESEARCH_EXAMPLE, sources: RESEARCH_EXAMPLE.sources.map(item => ({ ...item })), claims: RESEARCH_EXAMPLE.claims.map(item => ({ ...item, sourceIds: [...item.sourceIds] })) });
    setMessage("Example review loaded. Edit or remove anything; it is saved on this device.");
  };
  const exportMarkdown = () => {
    const lines = [
      `# ${project.title}`,
      "",
      project.question ? `Research question: ${project.question}` : "Research question: not set",
      "",
      "## Claims",
      "",
      ...project.claims.flatMap((claim, index) => [
        `${index + 1}. ${claim.text}`,
        `   - Sources: ${sourceRefs(project.sources, claim.sourceIds) || "unlinked"}`,
      ]),
      "",
      "## Source ledger",
      "",
      ...project.sources.flatMap((source, index) => [
        `### [${index + 1}] ${source.title}`,
        "",
        `- URL: ${source.url}`,
        `- Note: ${source.note || "None"}`,
        "",
      ]),
    ];
    downloadText(`${project.title || "citecraft"}.md`, lines.join("\n"));
    setMessage("Markdown research packet exported.");
  };

  return (
    <StudioShell meta={meta} onSetSurface={onSetSurface}>
      <div className="neyvia-studio-grid neyvia-citecraft-grid">
        <aside className="neyvia-studio-rail">
          <label>
            Review title
            <input onChange={event => update("title", event.target.value)} value={project.title} />
          </label>
          <label>
            Research question
            <textarea onChange={event => update("question", event.target.value)} rows="5" value={project.question} />
          </label>
          <div className="neyvia-studio-stat-grid">
            <div><strong>{project.sources.length}</strong><span>Sources</span></div>
            <div><strong>{project.claims.length}</strong><span>Claims</span></div>
            <div>
              <strong>{project.claims.filter(item => item.sourceIds.length).length}</strong>
              <span>Linked</span>
            </div>
          </div>
          <button className="is-primary" onClick={exportMarkdown} type="button">
            <Download aria-hidden="true" size={15} />
            Export notes
          </button>
        </aside>
        <main className="neyvia-research-ledger">
          <section>
            <div className="neyvia-studio-section-head">
              <div><span>Evidence</span><h2>Source ledger</h2></div>
            </div>
            <form className="neyvia-research-form" onSubmit={addSource}>
              <input
                aria-label="Source title"
                onChange={event => setSourceDraft(current => ({ ...current, title: event.target.value }))}
                placeholder="Source title"
                value={sourceDraft.title}
              />
              <input
                aria-label="Source URL"
                onChange={event => setSourceDraft(current => ({ ...current, url: event.target.value }))}
                placeholder="https:// or DOI"
                value={sourceDraft.url}
              />
              <textarea
                aria-label="Source note"
                onChange={event => setSourceDraft(current => ({ ...current, note: event.target.value }))}
                placeholder="What this source actually supports"
                rows="3"
                value={sourceDraft.note}
              />
              <button
                data-studio-action="add-source"
                disabled={!sourceDraft.title.trim() || !sourceDraft.url.trim()}
                onClick={addSource}
                type="button"
              >
                <Plus aria-hidden="true" size={15} />
                Add source
              </button>
            </form>
            <ul className="neyvia-research-list" aria-label="Research sources">
              {project.sources.length === 0 ? <ResearchExample kind="source" /> : null}
              {project.sources.map((source, index) => (
                <li key={source.id}>
                  <Link2 aria-hidden="true" size={16} />
                  <div><strong>{source.title}</strong><small>[{index + 1}]</small><p>{source.note}</p></div>
                  <button
                    aria-label={`Remove ${source.title}`}
                    onClick={() => update("sources", project.sources.filter(item => item.id !== source.id))}
                    type="button"
                  >
                    <Trash2 aria-hidden="true" size={14} />
                  </button>
                </li>
              ))}
            </ul>
          </section>
          <section>
            <div className="neyvia-studio-section-head">
              <div><span>Synthesis</span><h2>Claim matrix</h2></div>
            </div>
            <form className="neyvia-research-form" onSubmit={addClaim}>
              <textarea
                aria-label="Research claim"
                onChange={event => setClaimDraft(current => ({ ...current, claim: event.target.value }))}
                placeholder="One falsifiable claim"
                rows="3"
                value={claimDraft.claim}
              />
              <input
                aria-label="Sources that back it"
                onChange={event => setClaimDraft(current => ({ ...current, sourceIds: event.target.value }))}
                placeholder={project.sources.length ? "Which sources back it? Their numbers, like 1, 2" : "Add a source first, then name it by number"}
                value={claimDraft.sourceIds}
              />
              <button
                data-studio-action="add-claim"
                disabled={!claimDraft.claim.trim()}
                onClick={addClaim}
                type="button"
              >
                <Plus aria-hidden="true" size={15} />
                Add claim
              </button>
            </form>
            <ul className="neyvia-claim-list">
              {project.claims.length === 0 ? <ResearchExample kind="claim" /> : null}
              {project.claims.map((claim, index) => (
                <li key={claim.id} data-linked={claim.sourceIds.length ? "true" : "false"}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <div><strong>{claim.text}</strong><small>{sourceRefs(project.sources, claim.sourceIds) || "No supporting source linked"}</small></div>
                  <button
                    aria-label={`Remove claim ${index + 1}`}
                    onClick={() => update("claims", project.claims.filter(item => item.id !== claim.id))}
                    type="button"
                  >
                    <Trash2 aria-hidden="true" size={14} />
                  </button>
                </li>
              ))}
            </ul>
          </section>
          <p className="neyvia-studio-message" role="status">
            {message}
            {project.sources.length === 0 && project.claims.length === 0 ? (
              <button className="neyvia-research-try" data-studio-action="load-example" onClick={loadExample} type="button">Start from the example review</button>
            ) : null}
          </p>
        </main>
      </div>
    </StudioShell>
  );
}

const SECURITY_DEFAULT = Object.freeze({
  engagement: "Authorized assessment",
  target: "",
  scope: "",
  rules: "Only systems explicitly listed in scope. Stop on instability or unexpected data exposure.",
  authorizationConfirmed: false,
  checklist: {
    inventory: false,
    boundaries: false,
    evidence: false,
    cleanup: false,
  },
  findings: [],
});

function AegisRange({ meta, onSetSurface }) {
  const [project, setProject] = usePersistentProject("neyvia.studio.aegis-range.v1", SECURITY_DEFAULT);
  const [draft, setDraft] = useState({ title: "", severity: "medium", evidence: "", remediation: "" });
  const [message, setMessage] = useState("Authorization and exact target boundaries are required before testing.");
  const update = (field, value) => setProject(current => ({ ...current, [field]: value }));
  const ready = project.authorizationConfirmed && project.target.trim() && project.scope.trim();
  const addFinding = event => {
    event?.preventDefault();
    if (!ready || !draft.title.trim()) return;
    const finding = { ...draft, id: `finding-${Date.now().toString(36)}`, createdAt: new Date().toISOString() };
    setProject(current => ({ ...current, findings: [...current.findings, finding] }));
    setDraft({ title: "", severity: "medium", evidence: "", remediation: "" });
    setMessage("Finding recorded inside the authorized engagement.");
  };
  const exportReport = () => {
    const report = {
      schema: "neyvia.aegis-range.report/v1",
      exportedAt: new Date().toISOString(),
      engagement: project.engagement,
      target: project.target,
      scope: project.scope,
      rules: project.rules,
      authorizationConfirmed: project.authorizationConfirmed,
      checklist: project.checklist,
      findings: project.findings,
    };
    downloadText(`${project.engagement || "aegis-range"}-report.json`, JSON.stringify(report, null, 2), "application/json");
    setMessage("Assessment report exported with scope and authorization record.");
  };

  return (
    <StudioShell
      meta={meta}
      onSetSurface={onSetSurface}
      status={{ label: ready ? "Scope ready" : "Scope required", tone: ready ? "saved" : "blocked" }}
    >
      <div className="neyvia-studio-grid neyvia-aegis-grid">
        <aside className="neyvia-studio-rail">
          <label>
            Engagement
            <input onChange={event => update("engagement", event.target.value)} value={project.engagement} />
          </label>
          <label>
            Authorized target
            <input onChange={event => update("target", event.target.value)} placeholder="Host, application, or lab" value={project.target} />
          </label>
          <label>
            Exact scope
            <textarea onChange={event => update("scope", event.target.value)} placeholder="Assets, ports, accounts, dates" rows="5" value={project.scope} />
          </label>
          <label>
            Rules of engagement
            <textarea onChange={event => update("rules", event.target.value)} rows="7" value={project.rules} />
          </label>
          <label className="neyvia-authorization-check">
            <input
              checked={project.authorizationConfirmed}
              onChange={event => update("authorizationConfirmed", event.target.checked)}
              type="checkbox"
            />
            <span>I confirm this target is authorized for the assessment.</span>
          </label>
          <button className="is-primary" disabled={!ready} onClick={exportReport} type="button">
            <Download aria-hidden="true" size={15} />
            Export report
          </button>
        </aside>
        <main className="neyvia-security-board">
          <section className="neyvia-security-readiness" data-ready={ready ? "true" : "false"}>
            <div>
              <ShieldCheck aria-hidden="true" size={22} />
              <div><span>Assessment scope</span><strong>{ready ? "Authorized scope recorded" : "Record the authorized scope"}</strong></div>
            </div>
            <p>{ready ? `Assessment target: ${project.target}.` : "Add a target, scope, and authorization to start recording findings."}</p>
          </section>
          <section>
            <div className="neyvia-studio-section-head">
              <div><span>Method</span><h2>Assessment checklist</h2></div>
            </div>
            <div className="neyvia-security-checklist">
              {[
                ["inventory", "Asset inventory", "Record versions, owners, and exposed interfaces."],
                ["boundaries", "Boundary validation", "Confirm that every test stays inside scope."],
                ["evidence", "Evidence custody", "Keep timestamps and reproducible observations."],
                ["cleanup", "Cleanup", "Remove test data and confirm service stability."],
              ].map(([id, label, detail]) => (
                <label key={id}>
                  <input
                    checked={project.checklist[id]}
                    onChange={event => update("checklist", { ...project.checklist, [id]: event.target.checked })}
                    type="checkbox"
                  />
                  <span><strong>{label}</strong><small>{detail}</small></span>
                </label>
              ))}
            </div>
          </section>
          <section>
            <div className="neyvia-studio-section-head">
              <div><span>Evidence</span><h2>Finding register</h2></div>
            </div>
            <form className="neyvia-security-finding-form" onSubmit={addFinding}>
              <input
                aria-label="Finding title"
                disabled={!ready}
                onChange={event => setDraft(current => ({ ...current, title: event.target.value }))}
                placeholder="Finding title"
                value={draft.title}
              />
              <select
                aria-label="Finding severity"
                disabled={!ready}
                onChange={event => setDraft(current => ({ ...current, severity: event.target.value }))}
                value={draft.severity}
              >
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
                <option value="informational">Informational</option>
              </select>
              <textarea
                aria-label="Finding evidence"
                disabled={!ready}
                onChange={event => setDraft(current => ({ ...current, evidence: event.target.value }))}
                placeholder="Observed behavior and reproducible evidence"
                rows="3"
                value={draft.evidence}
              />
              <textarea
                aria-label="Finding remediation"
                disabled={!ready}
                onChange={event => setDraft(current => ({ ...current, remediation: event.target.value }))}
                placeholder="Practical remediation"
                rows="3"
                value={draft.remediation}
              />
              <button
                data-studio-action="record-finding"
                disabled={!ready || !draft.title.trim()}
                onClick={addFinding}
                type="button"
              >
                <Plus aria-hidden="true" size={15} />
                Record finding
              </button>
            </form>
            <ul className="neyvia-security-findings">
              {project.findings.map(finding => (
                <li data-severity={finding.severity} key={finding.id}>
                  <span>{finding.severity}</span>
                  <div><strong>{finding.title}</strong><p>{finding.evidence || "Evidence not yet written."}</p><small>{finding.remediation || "Remediation not yet written."}</small></div>
                  <button
                    aria-label={`Remove ${finding.title}`}
                    onClick={() => update("findings", project.findings.filter(item => item.id !== finding.id))}
                    type="button"
                  >
                    <Trash2 aria-hidden="true" size={14} />
                  </button>
                </li>
              ))}
            </ul>
          </section>
          <p className="neyvia-studio-message" role="status">{message}</p>
        </main>
      </div>
    </StudioShell>
  );
}

const AUDIO_DEFAULT = Object.freeze({
  title: "Untitled audio review",
  sourceName: "",
  sourceType: "",
  sourceSize: 0,
  duration: 0,
  inPoint: 0,
  outPoint: 0,
  peaks: [],
  notes: [],
});

function audioPeaks(buffer, count = 112) {
  const channel = buffer.getChannelData(0);
  const blockSize = Math.max(1, Math.floor(channel.length / count));
  return Array.from({ length: count }, (_, index) => {
    const start = index * blockSize;
    const end = Math.min(channel.length, start + blockSize);
    let peak = 0;
    for (let cursor = start; cursor < end; cursor += 1) {
      peak = Math.max(peak, Math.abs(channel[cursor]));
    }
    return Number(Math.max(0.035, Math.min(1, peak)).toFixed(4));
  });
}

function CueLedger({ meta, onSetSurface }) {
  const [project, setProject] = usePersistentProject("neyvia.studio.cueledger.v1", AUDIO_DEFAULT);
  const [audioUrl, setAudioUrl] = useState("");
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(Number(project.duration) || 0);
  const [playing, setPlaying] = useState(false);
  const [noteDraft, setNoteDraft] = useState("");
  const [message, setMessage] = useState(
    project.sourceName ? `Relink ${project.sourceName} to continue this local review.` : "Choose a local audio file to begin.",
  );
  const audioRef = useRef(null);

  useEffect(() => () => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
  }, [audioUrl]);

  const update = (field, value) => setProject(current => ({ ...current, [field]: value }));
  const activeDuration = Math.max(0, duration || Number(project.duration) || 0);
  const activeOutPoint = Math.max(Number(project.inPoint) || 0, Number(project.outPoint) || activeDuration);
  const sourceLinked = Boolean(audioUrl);

  const selectAudio = async event => {
    const file = event.target.files?.[0];
    if (!file) return;
    const nextUrl = URL.createObjectURL(file);
    setAudioUrl(nextUrl);
    setCurrentTime(0);
    setPlaying(false);
    setMessage("Reading local audio metadata and waveform…");

    let decodedDuration = 0;
    let peaks = [];
    const AudioContextImplementation = window.AudioContext || window.webkitAudioContext;
    if (AudioContextImplementation) {
      const context = new AudioContextImplementation();
      try {
        const decoded = await context.decodeAudioData(await file.arrayBuffer());
        decodedDuration = Number(decoded.duration) || 0;
        peaks = audioPeaks(decoded);
      } catch {
        setMessage("Audio linked. This codec can play, but its waveform could not be decoded.");
      } finally {
        await context.close().catch(() => {});
      }
    }

    setDuration(decodedDuration);
    setProject(current => ({
      ...current,
      sourceName: file.name,
      sourceType: file.type || "audio",
      sourceSize: file.size,
      duration: decodedDuration,
      inPoint: 0,
      outPoint: decodedDuration,
      peaks,
      notes: [],
    }));
    if (peaks.length) setMessage("Audio linked locally. Set a range or add a timestamped note.");
    event.target.value = "";
  };

  const handleLoadedMetadata = event => {
    const nextDuration = Number(event.currentTarget.duration) || 0;
    setDuration(nextDuration);
    setProject(current => ({
      ...current,
      duration: nextDuration,
      outPoint: Number(current.outPoint) > 0
        ? Math.min(Number(current.outPoint), nextDuration)
        : nextDuration,
    }));
  };

  const handleTimeUpdate = event => {
    const nextTime = Number(event.currentTarget.currentTime) || 0;
    if (activeOutPoint > Number(project.inPoint) && nextTime >= activeOutPoint) {
      event.currentTarget.pause();
      event.currentTarget.currentTime = Number(project.inPoint) || 0;
      setCurrentTime(Number(project.inPoint) || 0);
      setPlaying(false);
      setMessage("Reached the marked out point.");
      return;
    }
    setCurrentTime(nextTime);
  };

  const togglePlayback = async () => {
    const audio = audioRef.current;
    if (!audio) {
      setMessage("Relink the local audio file before playback.");
      return;
    }
    if (!audio.paused) {
      audio.pause();
      return;
    }
    const inPoint = Number(project.inPoint) || 0;
    if (audio.currentTime < inPoint || audio.currentTime >= activeOutPoint) {
      audio.currentTime = inPoint;
      setCurrentTime(inPoint);
    }
    try {
      await audio.play();
    } catch {
      setMessage("Playback was blocked by the browser. Press play again.");
    }
  };

  const seek = event => {
    const nextTime = Number(event.target.value) || 0;
    if (audioRef.current) audioRef.current.currentTime = nextTime;
    setCurrentTime(nextTime);
  };

  const markIn = () => {
    const nextIn = Math.max(0, Math.min(currentTime, activeDuration));
    setProject(current => ({
      ...current,
      inPoint: nextIn,
      outPoint: Math.max(Number(current.outPoint) || activeDuration, Math.min(activeDuration, nextIn + 0.05)),
    }));
    setMessage(`In point set to ${formatTimestamp(nextIn)}.`);
  };

  const markOut = () => {
    const inPoint = Number(project.inPoint) || 0;
    const nextOut = Math.max(inPoint + 0.05, Math.min(currentTime, activeDuration));
    update("outPoint", Math.min(activeDuration, nextOut));
    setMessage(`Out point set to ${formatTimestamp(Math.min(activeDuration, nextOut))}.`);
  };

  const addNote = event => {
    event?.preventDefault();
    const note = noteDraft.trim();
    if (!note || !project.sourceName) return;
    const entry = {
      id: `cue-${Date.now().toString(36)}`,
      time: Number(currentTime.toFixed(3)),
      note,
    };
    setProject(current => ({
      ...current,
      notes: [...current.notes, entry].sort((left, right) => left.time - right.time),
    }));
    setNoteDraft("");
    setMessage(`Cue saved at ${formatTimestamp(entry.time)}.`);
  };

  const jumpToCue = cue => {
    const nextTime = Math.min(Number(cue.time) || 0, activeDuration);
    if (audioRef.current) audioRef.current.currentTime = nextTime;
    setCurrentTime(nextTime);
    setMessage(`Moved to ${formatTimestamp(nextTime)}.`);
  };

  const exportCueSheet = () => {
    const payload = {
      schema: "neyvia.cueledger.cue-sheet/v1",
      exportedAt: new Date().toISOString(),
      title: project.title,
      source: {
        name: project.sourceName,
        mediaType: project.sourceType,
        bytes: project.sourceSize,
        durationSeconds: activeDuration,
        localOnly: true,
      },
      range: {
        inSeconds: Number(project.inPoint) || 0,
        outSeconds: activeOutPoint,
      },
      cues: project.notes,
    };
    const filename = (project.title || "cueledger").trim().replace(/[^\w.-]+/g, "-").toLowerCase();
    downloadText(`${filename || "cueledger"}-cues.json`, JSON.stringify(payload, null, 2), "application/json");
    setMessage("Cue sheet exported with source metadata, range, and timestamped notes.");
  };

  return (
    <StudioShell
      meta={meta}
      onSetSurface={onSetSurface}
      status={{
        label: sourceLinked ? "Audio linked locally" : project.sourceName ? "Relink source" : "Source required",
        tone: sourceLinked ? "saved" : "blocked",
      }}
    >
      <div className="neyvia-studio-grid neyvia-cueledger-grid">
        <aside className="neyvia-studio-rail">
          <label>
            Review title
            <input onChange={event => update("title", event.target.value)} value={project.title} />
          </label>
          <label className="neyvia-studio-file-button">
            <Upload aria-hidden="true" size={16} />
            <span>{project.sourceName ? "Relink local audio" : "Choose local audio"}</span>
            <input
              accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus"
              data-studio-file-input="cueledger"
              onChange={selectAudio}
              type="file"
            />
          </label>
          <div className="neyvia-audio-source">
            <span>Source</span>
            <strong>{project.sourceName || "No audio selected"}</strong>
            <small>
              {project.sourceName
                ? `${project.sourceType || "audio"} · ${(Number(project.sourceSize) / 1_000_000).toFixed(2)} MB`
                : "The source remains on this device and is never uploaded."}
            </small>
          </div>
          <div className="neyvia-audio-range">
            <div><span>In</span><strong>{formatTimestamp(project.inPoint)}</strong></div>
            <div><span>Out</span><strong>{formatTimestamp(activeOutPoint)}</strong></div>
            <div><span>Length</span><strong>{formatTimestamp(Math.max(0, activeOutPoint - Number(project.inPoint || 0)))}</strong></div>
          </div>
          <button className="is-primary" disabled={!project.sourceName} onClick={exportCueSheet} type="button">
            <Download aria-hidden="true" size={15} />
            Export cue sheet
          </button>
        </aside>

        <main className="neyvia-audio-board">
          <section className="neyvia-audio-review">
            <div className="neyvia-studio-section-head">
              <div><span>Local playback</span><h2>Review range</h2></div>
              <small>{formatTimestamp(currentTime)} / {formatTimestamp(activeDuration)}</small>
            </div>
            {sourceLinked ? (
              <>
                <audio
                  onEnded={() => setPlaying(false)}
                  onLoadedMetadata={handleLoadedMetadata}
                  onPause={() => setPlaying(false)}
                  onPlay={() => setPlaying(true)}
                  onTimeUpdate={handleTimeUpdate}
                  ref={audioRef}
                  src={audioUrl}
                />
                {project.peaks.length ? (
                  <div aria-label="Decoded audio waveform" className="neyvia-audio-waveform">
                    {project.peaks.map((peak, index) => {
                      const position = activeDuration ? (index / Math.max(1, project.peaks.length - 1)) * activeDuration : 0;
                      const inside = position >= Number(project.inPoint) && position <= activeOutPoint;
                      const passed = position <= currentTime;
                      return (
                        <span
                          data-inside={inside ? "true" : "false"}
                          data-passed={passed ? "true" : "false"}
                          key={`${index}-${peak}`}
                          style={{ "--neyvia-audio-peak": peak }}
                        />
                      );
                    })}
                  </div>
                ) : (
                  <div className="neyvia-audio-waveform-empty">Waveform unavailable for this codec; playback and cues remain usable.</div>
                )}
                <input
                  aria-label="Audio playhead"
                  className="neyvia-audio-scrubber"
                  max={Math.max(activeDuration, 0.01)}
                  min="0"
                  onChange={seek}
                  onInput={seek}
                  step="0.01"
                  type="range"
                  value={Math.min(currentTime, activeDuration)}
                />
                <div className="neyvia-audio-transport">
                  <button aria-label={playing ? "Pause audio" : "Play audio"} onClick={togglePlayback} type="button">
                    {playing ? <Pause aria-hidden="true" size={18} /> : <Play aria-hidden="true" size={18} />}
                    {playing ? "Pause" : "Play"}
                  </button>
                  <button onClick={markIn} type="button"><Clock3 aria-hidden="true" size={15} />Mark in</button>
                  <button onClick={markOut} type="button"><Clock3 aria-hidden="true" size={15} />Mark out</button>
                </div>
              </>
            ) : (
              <div className="neyvia-studio-empty is-stage">
                <AudioLines aria-hidden="true" size={34} />
                <strong>{project.sourceName ? `Relink ${project.sourceName}` : "No local audio linked"}</strong>
                <p>{project.sourceName ? "Metadata and notes are saved; choose the original file to resume playback." : "Choose a recording, interview, or soundtrack from this device."}</p>
              </div>
            )}
          </section>

          <section className="neyvia-audio-cues">
            <div className="neyvia-studio-section-head">
              <div><span>Evidence</span><h2>Timestamped cues</h2></div>
              <small>{project.notes.length} saved</small>
            </div>
            <form onSubmit={addNote}>
              <span>{formatTimestamp(currentTime)}</span>
              <input
                aria-label="Cue note"
                disabled={!project.sourceName}
                onChange={event => setNoteDraft(event.target.value)}
                placeholder="Speaker change, edit note, quote, or decision"
                value={noteDraft}
              />
              <button
                data-studio-action="add-cue"
                disabled={!project.sourceName || !noteDraft.trim()}
                onClick={addNote}
                type="button"
              >
                <Plus aria-hidden="true" size={15} />
                Add cue
              </button>
            </form>
            {project.notes.length ? (
              <ol>
                {project.notes.map(cue => (
                  <li key={cue.id}>
                    <button onClick={() => jumpToCue(cue)} type="button">{formatTimestamp(cue.time)}</button>
                    <p>{cue.note}</p>
                    <button
                      aria-label={`Remove cue at ${formatTimestamp(cue.time)}`}
                      onClick={() => update("notes", project.notes.filter(item => item.id !== cue.id))}
                      type="button"
                    >
                      <Trash2 aria-hidden="true" size={14} />
                    </button>
                  </li>
                ))}
              </ol>
            ) : (
              <div className="neyvia-audio-cues-empty">
                <Clock3 aria-hidden="true" size={20} />
                <p>Play or seek to an exact moment, then add the first review cue.</p>
              </div>
            )}
          </section>
          <p className="neyvia-studio-message" role="status">{message}</p>
        </main>
      </div>
    </StudioShell>
  );
}

export function NeyviaNativeStudioSurface({ callBackend, onSetSurface, studioId }) {
  const meta = STUDIO_META[studioId] || STUDIO_META.lumaforge;
  if (meta.id === "lumaforge") return <LumaForge callBackend={callBackend} meta={meta} onSetSurface={onSetSurface} />;
  if (meta.id === "frameweave") return <Frameweave meta={meta} onSetSurface={onSetSurface} />;
  if (meta.id === "citecraft") return <Citecraft meta={meta} onSetSurface={onSetSurface} />;
  if (meta.id === "aegis-range") return <AegisRange meta={meta} onSetSurface={onSetSurface} />;
  return <CueLedger meta={meta} onSetSurface={onSetSurface} />;
}

export { STUDIO_META };
