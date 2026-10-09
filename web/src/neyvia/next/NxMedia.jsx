import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { FileText, X } from "lucide-react";

import { Icon, useFocusTrap } from "./nxPrimitives.jsx";
import { backendBase, callNx, isDesktopApp } from "./nxApi.js";

// Images in a chat: the user's pasted screenshots, images in replies, and
// tool screenshots. Transcripts carry a mediaRef (a hash of the image), not a
// URL. Browsers load it from the media route with their session cookie; the
// desktop app has no cookie there, so it reads the bytes over IPC once.

const desktopCache = new Map(); // mediaRef -> Promise<object URL | null>

function desktopUrl(sessionId, mediaRef) {
  if (!desktopCache.has(mediaRef)) {
    desktopCache.set(mediaRef, callNx("connected_session_media_command", { id: sessionId, mediaRef })
      .then(found => {
        const bytes = Uint8Array.from(atob(found.data), char => char.charCodeAt(0));
        return URL.createObjectURL(new Blob([bytes], { type: found.mime }));
      })
      .catch(() => { desktopCache.delete(mediaRef); return null; }));
  }
  return desktopCache.get(mediaRef);
}

/** Where an attachment's image can be loaded from, or a promise of it on the desktop app. */
export function mediaSource(sessionId, attachment) {
  const ref = attachment?.mediaRef || attachment?.id;
  const served = !attachment?.url || String(attachment.url).startsWith("/api/");
  // The service rewrites every attachment to its media route; the desktop app can't send a cookie there.
  if (isDesktopApp() && ref && sessionId && served) return desktopUrl(sessionId, ref);
  if (attachment?.url) return String(attachment.url).startsWith("/") ? `${backendBase()}${attachment.url}` : attachment.url;
  if (!ref || !sessionId) return null;
  return `${backendBase()}/api/connected/media?session=${encodeURIComponent(sessionId)}&media=${encodeURIComponent(ref)}`;
}

function useSource(sessionId, attachment) {
  const initial = mediaSource(sessionId, attachment);
  const [src, setSrc] = useState(typeof initial === "string" ? initial : null);
  useEffect(() => {
    let live = true;
    if (initial && typeof initial.then === "function") void initial.then(url => { if (live) setSrc(url || false); });
    else setSrc(initial || null);
    return () => { live = false; };
  }, [initial]);
  return src;
}

function Viewer({ src, alt, onClose }) {
  const box = useRef(null);
  useFocusTrap(box, true);
  useEffect(() => { box.current?.querySelector("button")?.focus(); }, []);
  useEffect(() => {
    const onKey = event => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  // At the shell root, so no transformed message bubble can clip a fixed overlay.
  return createPortal(
    <div ref={box} className="nx-media-viewer" role="dialog" aria-modal="true" aria-label={alt} onClick={onClose}>
      <img src={src} alt={alt} />
      <button type="button" className="nx-media-close" aria-label="Close" onClick={onClose}><Icon as={X} size={18} /></button>
    </div>,
    document.querySelector(".nx") || document.body,
  );
}

function ImageAttachment({ sessionId, item }) {
  const src = useSource(sessionId, item);
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);
  const alt = item.label || "Attached image";
  if (failed || src === false || (!src && !item.mediaRef && !item.id)) {
    return <span className="nx-attach-file"><Icon as={FileText} size={13} />Image (not available on this device)</span>;
  }
  return (
    <>
      <button type="button" className={`nx-attach-image${src ? "" : " is-loading"}`} onClick={() => src && setOpen(true)} aria-label={`Open ${alt}`}>
        {src ? <img src={src} alt={alt} loading="lazy" onError={() => setFailed(true)} /> : null}
      </button>
      {open ? <Viewer src={src} alt={alt} onClose={() => setOpen(false)} /> : null}
    </>
  );
}

export function Attachments({ items, sessionId }) {
  if (!items?.length) return null;
  return (
    <div className="nx-attachments">
      {items.map(item => item.kind === "image" ? <ImageAttachment key={item.id} sessionId={sessionId} item={item} /> : (
        <span key={item.id} className="nx-attach-file"><Icon as={FileText} size={13} />{item.label || "File"}</span>
      ))}
    </div>
  );
}
