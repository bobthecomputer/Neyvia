import {
  Activity,
  AppWindow,
  Archive,
  ArrowLeftRight,
  AudioLines,
  Binary,
  BookMarked,
  BookOpen,
  Bot,
  Box,
  Boxes,
  BoxSelect,
  Braces,
  BrainCircuit,
  Bug,
  Camera,
  ChartColumn,
  CircuitBoard,
  Clapperboard,
  ClipboardCheck,
  ClipboardList,
  Clock,
  Code2,
  Container,
  Cpu,
  Database,
  DatabaseZap,
  Download,
  Drama,
  Eye,
  File,
  FileBarChart,
  FileCode2,
  FileJson,
  FileText,
  FileType,
  Film,
  FlaskConical,
  FolderSearch,
  Gamepad2,
  Gauge,
  GitBranch,
  GitCompare,
  GitFork,
  Globe2,
  GraduationCap,
  Headphones,
  Highlighter,
  IdCard,
  Image,
  ImagePlus,
  Images,
  Inbox,
  Info,
  KeyRound,
  Languages,
  Layers,
  LayoutDashboard,
  LayoutGrid,
  Library,
  Link2,
  List,
  ListTree,
  Mail,
  Map,
  Megaphone,
  MessageSquare,
  MessageSquarePlus,
     MessagesSquare,
  Microscope,
  Minimize2,
  Monitor,
  MonitorSmartphone,
  MoonStar,
  MousePointerClick,
  Network,
  Newspaper,
  NotebookPen,
  Orbit,
  Package,
  PackagePlus,
  Palette,
  Paperclip,
  PenLine,
  PenTool,
  Pencil,
  Play,
  Plug,
  Pointer,
  Presentation,
  Puzzle,
  Quote,
  RefreshCw,
  Ruler,
  Save,
  ScanEye,
  ScanSearch,
  ScanText,
  Scissors,
  Search,
  Send,
  Server,
  Share2,
  Sheet,
  ShieldAlert,
  ShieldCheck,
  ShieldPlus,
  Shirt,
  Sigma,
  Smartphone,
  Sparkles,
  SpellCheck2,
  SquareTerminal,
  Swords,
  Table2,
  TabletSmartphone,
  Tag,
  Timer,
  Upload,
  Users,
  Utensils,
  WandSparkles,
  Wrench,
  Zap,
} from "lucide-react";

import { resolveNeyviaToolGlyph } from "./neyviaToolGlyphs.jsx";
import {
  getNeyviaFileTypeVisual,
  getNeyviaToolVisual,
  inferNeyviaToolPhase,
  isNeyviaToolEventChip,
  neyviaPanelEnterClass,
  neyviaToolChipClasses,
  neyviaToolPhaseLabel,
  resolveNeyviaMessageChip,
  resolveNeyviaToolId,
} from "./neyviaToolVisuals.js";

const ICON_MAP = Object.freeze({
  Activity,
  AppWindow,
  Archive,
  ArrowLeftRight,
  AudioLines,
  Binary,
  BookMarked,
  BookOpen,
  Bot,
  Box,
  Boxes,
  BoxSelect,
  Braces,
  BrainCircuit,
  Bug,
  Camera,
  ChartColumn,
  CircuitBoard,
  Clapperboard,
  ClipboardCheck,
  ClipboardList,
  Clock,
  Code2,
  Container,
  Cpu,
  Database,
  DatabaseZap,
  Download,
  Drama,
  Eye,
  File,
  FileBarChart,
  FileCode2,
  FileJson,
  FileText,
  FileType,
  Film,
  FlaskConical,
  FolderSearch,
  Gamepad2,
  Gauge,
  GitBranch,
  GitCompare,
  GitFork,
  Globe2,
  GraduationCap,
  Headphones,
  Highlighter,
  IdCard,
  Image,
  ImagePlus,
  Images,
  Inbox,
  Info,
  KeyRound,
  Languages,
  Layers,
  LayoutDashboard,
  LayoutGrid,
  Library,
  Link2,
  List,
  ListTree,
  Mail,
  Map,
  Megaphone,
  MessageSquare,
  MessageSquarePlus,
     MessagesSquare,
  Microscope,
  Minimize2,
  Monitor,
  MonitorSmartphone,
  MoonStar,
  MousePointerClick,
  Network,
  Newspaper,
  NotebookPen,
  Orbit,
  Package,
  PackagePlus,
  Palette,
  Paperclip,
  PenLine,
  PenTool,
  Pencil,
  Play,
  Plug,
  Pointer,
  Presentation,
  Puzzle,
  Quote,
  RefreshCw,
  Ruler,
  Save,
  ScanEye,
  ScanSearch,
  ScanText,
  Scissors,
  Search,
  Send,
  Server,
  Share2,
  Sheet,
  ShieldAlert,
  ShieldCheck,
  ShieldPlus,
  Shirt,
  Sigma,
  Smartphone,
  Sparkles,
  SpellCheck2,
  SquareTerminal,
  Swords,
  Table2,
  TabletSmartphone,
  Tag,
  Timer,
  Upload,
  Users,
  Utensils,
  WandSparkles,
  Wrench,
  Zap,
});

/**
 * Resolve a lucide icon component by registry name.
 * @param {string} [name]
 */
export function resolveNeyviaLucideIcon(name = "Wrench") {
  return ICON_MAP[name] || Wrench;
}

/**
 * Distinct per-tool icon for catalog / toolbar / chips.
 * Prefers custom Neyvia glyphs where Lucide collisions exist.
 */
export function NeyviaToolIcon({ toolId = "", size = 14, strokeWidth = 2, className = "", title }) {
  const visual = getNeyviaToolVisual(toolId);
  const Glyph = resolveNeyviaToolGlyph(resolveNeyviaToolId(toolId), visual.category);
  if (Glyph) {
    return <Glyph className={className || undefined} size={size} title={title} />;
  }
  const Icon = resolveNeyviaLucideIcon(visual.icon);
  return (
    <Icon
      aria-hidden={title ? undefined : true}
      className={className || undefined}
      size={size}
      strokeWidth={strokeWidth}
      title={title}
    />
  );
}

/**
 * File-type icon for Library / attachments.
 */
export function NeyviaFileTypeIcon({ file, size = 14, strokeWidth = 2, className = "" }) {
  const visual = getNeyviaFileTypeVisual(file || {});
  const Icon = resolveNeyviaLucideIcon(visual.icon);
  return (
    <Icon
      aria-hidden="true"
      className={`neyvia-file-type-icon ${visual.animationClass} ${className}`.trim()}
      data-file-kind={visual.id}
      size={size}
      strokeWidth={strokeWidth}
    />
  );
}

/**
 * Conversation / live-stream tool-call chip with phase animation.
 * Does not invent success — phase comes from caller / row tone.
 */
export function NeyviaToolCallChip({
  toolId = "",
  phase,
  row,
  title,
  detail,
  className = "",
}) {
  const resolvedId = resolveNeyviaToolId(toolId || title || detail || "");
  const resolvedPhase = phase || inferNeyviaToolPhase(row || {});
  const label = title || neyviaToolPhaseLabel(toolId || detail || resolvedId, resolvedPhase);
  const classes = `${neyviaToolChipClasses(resolvedId, resolvedPhase)} ${className}`.trim();

  return (
    <span
      className={classes}
      data-neyvia-tool-chip="true"
      data-tool-id={resolvedId}
      data-tool-phase={resolvedPhase}
      aria-label={`${label} · ${resolvedPhase === "idle" ? "recorded" : resolvedPhase}`}
      title={detail || label}
    >
      <NeyviaToolIcon size={13} toolId={resolvedId} />
      <strong>{label}</strong>
      {detail ? <em>{detail}</em> : null}
    </span>
  );
}

/**
 * Render conversation-history chips — tool events become NeyviaToolCallChip;
 * provenance / meta chips stay plain pills.
 */
export function NeyviaMessageChipList({
  chips = [],
  message = {},
  limit = 4,
  className = "fluxos-message-chips",
  plainClassName = "mini-pill muted",
}) {
  const rows = (Array.isArray(chips) ? chips : []).slice(0, limit);
  if (!rows.length) return null;

  return (
    <div className={className} data-neyvia-message-chips="true">
      {rows.map((chip, index) => {
        const key = typeof chip === "object" ? chip.id || chip.label || index : String(chip);
        const resolved = resolveNeyviaMessageChip(chip, message);
        if (resolved.isToolEvent || isNeyviaToolEventChip(chip)) {
          return (
            <NeyviaToolCallChip
              detail={resolved.detail || undefined}
              key={`${key}-${resolved.toolId}`}
              phase={resolved.phase}
              title={resolved.title}
              toolId={resolved.toolId}
            />
          );
        }
        const label = typeof chip === "object" ? chip.label || chip.title || chip.text || key : String(chip);
        return (
          <span className={plainClassName} key={`${key}-plain`}>
            {label}
          </span>
        );
      })}
    </div>
  );
}

/**
 * Overlay / drawer enter class helper for panel shells.
 */
export function neyviaOverlayEnterProps(panelId = "") {
  const enterClass = neyviaPanelEnterClass(panelId);
  return {
    className: enterClass,
    "data-neyvia-panel-enter": panelId || "default",
  };
}

export {
  getNeyviaFileTypeVisual,
  getNeyviaToolVisual,
  inferNeyviaToolPhase,
  isNeyviaToolEventChip,
  neyviaPanelEnterClass,
  neyviaToolChipClasses,
  neyviaToolPhaseLabel,
  resolveNeyviaMessageChip,
  resolveNeyviaToolId,
};
