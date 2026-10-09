import { useLayoutEffect, useState } from 'react';
import { BatteryFull, Signal, Wifi } from 'lucide-react';
import {EmulatedKeyboard} from './NxEmulatedKeyboard.jsx';
const BEZEL = 12;

export function insetsFor(device, orientation) {
  const [top, right, bottom, left] = device.safe[orientation === "landscape" ? "landscape" : "portrait"];
  return { top, right, bottom, left };
}

export function isLight(color) {
  const match = String(color || "").match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?/);
  if (!match || match[4] === "0") return null;
  const [r, g, b] = match.slice(1, 4).map(Number);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 150;
}

export function shortPath(path) {
  const parts = String(path || "").split(/[\\/]/).filter(Boolean);
  return parts.length > 3 ? `…\\${parts.slice(-2).join("\\")}` : path;
}

// ---------------------------------------------------------------- the phone

function StatusBar({ device, landscape, light, height, safe }) {
  if (["tvos","visionos"].includes(device.platform)) return null;
  if (device.platform === "macos") return <div className="nx-ms-mac-title" aria-hidden="true"><span>● ● ●</span><strong>App preview</strong></div>;
  if (landscape && device.platform === "ios") return null; // iPhones hide it in landscape
  const ink = light ? "#111" : "#fff";
  const side = landscape ? { paddingLeft: safe.left + 14, paddingRight: safe.right + 14 } : null; // clear of the camera
  return (
    <div className={`nx-ms-statusbar is-${device.platform}${device.cutout === "island" ? " has-island" : ""}`} style={{ height, color: ink, ...side }} aria-hidden="true">
      <span className="nx-ms-time">9:41</span>
      <span className="nx-ms-sysicons">
        <Signal size={device.platform === "ios" ? 15 : 13} strokeWidth={2.4} />
        <Wifi size={device.platform === "ios" ? 15 : 13} strokeWidth={2.4} />
        <BatteryFull size={device.platform === "ios" ? 20 : 15} strokeWidth={2} />
      </span>
    </div>
  );
}

/** The phone frame. With no `src`, `children` fill the screen (the tour puts real chat rows there). */
export function Phone({ device, orientation, dark, src, sandbox, frameRef, app, scale, keyboard = false, children = null }) {
  const landscape = orientation === "landscape";
  const width = landscape ? device.height : device.width;
  const height = landscape ? device.width : device.height;
  const se = device.home === "button";
  const bezel = se ? (landscape ? { x: 72, y: 14 } : { x: 14, y: 72 }) : { x: BEZEL, y: BEZEL };
  const safe = insetsFor(device, orientation);
  const cover = Boolean(app?.cover);
  // Without viewport-fit=cover the system keeps the page inside the safe area, as WKWebView and Android WebViews do.
  const inset = cover ? { top: 0, right: 0, bottom: 0, left: 0 } : safe;
  const keyboardHeight = keyboard && ["ios","ipados","android"].includes(device.platform) ? 244 : 0;
  const fill = !src ? (children ? "var(--nx-bg)" : "#0d0e0f") : app?.background && isLight(app.background) !== null ? app.background : dark ? "#000" : "#fff";
  const statusLight = isLight(app?.background) ?? !dark;
  const outer = { width: width + bezel.x * 2, height: height + bezel.y * 2 };
  return (
    <div className="nx-ms-phone-box" data-preview-path={app?.path || ""} data-preview-instance={app?.sdkInstance || ""}
      data-preview-text={app?.documentText || ""} style={{ width: outer.width * scale, height: outer.height * scale }}>
      <div className={`nx-ms-phone is-${device.platform}${se ? " is-se" : ""}`} data-orientation={orientation}
        style={{ width: outer.width, height: outer.height, borderRadius: se ? 54 : device.radius + bezel.x, padding: `${bezel.y}px ${bezel.x}px`, transform: `scale(${scale})` }}>
        <div className="nx-ms-screen" style={{ width, height, borderRadius: device.radius, background: fill }}>
          {src ? (
            <iframe ref={frameRef} key={src} src={src} title="Your app in the device frame" sandbox={sandbox} allow="clipboard-write; fullscreen"
              style={{ top: inset.top, left: inset.left, width: width - inset.left - inset.right, height: height - inset.top - inset.bottom - keyboardHeight, colorScheme: dark ? "dark" : "light" }} />
          ) : children ? (
            <div className="nx-ms-screen-content" style={{ top: inset.top, left: inset.left, right: inset.right, bottom: inset.bottom }}>{children}</div>
          ) : null}
          <StatusBar device={device} landscape={landscape} light={statusLight} height={landscape ? 24 : device.statusBar} safe={safe} />
          {keyboardHeight ? <EmulatedKeyboard frameRef={frameRef}/> : null}
          {device.cutout === "island" ? <span className="nx-ms-island" aria-hidden="true" /> : null}
          {device.cutout === "punch" ? <span className="nx-ms-punch" aria-hidden="true" /> : null}
          {device.home === "indicator" || device.home === "gesture" ? <span className={`nx-ms-homebar is-${device.home}`} style={{ background: statusLight ? "rgba(0,0,0,.82)" : "rgba(255,255,255,.88)" }} aria-hidden="true" /> : null}
        </div>
        {se ? <span className="nx-ms-homebutton" aria-hidden="true" /> : null}
        {se ? <span className="nx-ms-earpiece" aria-hidden="true" /> : null}
      </div>
    </div>
  );
}

export function useFit(element, outer) {
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    if (!element) return undefined;
    const measure = () => {
      const width = element.clientWidth - 32;
      const height = element.clientHeight - 24;
      setScale(Math.max(0.3, Math.min(1, width / outer.width, height / outer.height)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [element, outer.width, outer.height]);
  return scale;
}
