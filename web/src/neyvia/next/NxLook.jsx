import { useCallback, useEffect, useId, useRef, useState } from "react";
import { m } from "motion/react";
import { Check, ImagePlus, Palette } from "lucide-react";

import { Button, Segmented, radioGroupKeys } from "./nxPrimitives.jsx";
import { BLUR_MAX, DIM_MAX, FONTS, GRAIN, PRESETS, SWATCHES, TEXT_SIZES, normalizeLook, shownColor } from "./nxLookModel.js";
import { uploadBackground, useLookView } from "./nxLookApi.js";
import { getOs, os, useOs } from "./nxOsStore.js";
import { THEME_DAYPAIR, THEME_LABELS } from "./nxThemeRegistry.js";
import { explainSettingsError, saveSettings } from "./nxSettingsApi.js";
import { SPRING } from "./nxSpring.js";

// Settings > Look: typeface pair, text size and background. Every choice
// shows at once and is saved on the PC (canonical Settings `look`); sliders
// save when they settle. The contrast guard (nxLookModel.resolveBackground)
// raises the dim whenever a background would make body text hard to read.

/** Apply a look at once; save it on the PC (after `wait` ms of quiet, for sliders). */
function useLookSaver() {
  const [error, setError] = useState("");
  const timer = useRef(0);
  const pending = useRef(null);
  const flush = useCallback(async () => {
    const look = pending.current;
    pending.current = null;
    if (!look) return;
    try { await saveSettings({ look }); setError(""); }
    catch (failure) {
      setError(explainSettingsError(failure).message);
      const saved = getOs().prefs?.settings?.look;
      if (saved) os.setLook(saved);
    }
  }, []);
  const change = useCallback((patch, wait = 0) => {
    const current = getOs().look;
    const next = normalizeLook({ ...current, ...patch, background: { ...current.background, ...(patch.background || {}) } });
    os.setLook(next);
    pending.current = next;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => void flush(), wait);
  }, [flush]);
  useEffect(() => () => { clearTimeout(timer.current); void flush(); }, [flush]);
  return { change, error, setError };
}

function Selected({ group }) {
  return <m.span layoutId={`nx-look-ring-${group}`} className="nx-look-ring" transition={SPRING.snappy} aria-hidden="true" />;
}

/**
 * A row of cards that behaves as one radio group: Tab reaches the chosen card,
 * arrow keys move and choose (radioGroupKeys), Space/Enter choose. The ring
 * around the chosen card slides to the next one on a spring.
 */
function RadioCards({ label, value, onChange, items, className, cardClass, group }) {
  const tabValue = items.some(item => item.value === value) ? value : items[0]?.value;
  return (
    <div role="radiogroup" aria-label={label} className={className} onKeyDown={radioGroupKeys}>
      {items.map(item => {
        const selected = item.value === value;
        return (
          <button key={item.value} type="button" role="radio" aria-checked={selected} aria-label={item.label} tabIndex={item.value === tabValue ? 0 : -1}
            className={cardClass} data-selected={selected || undefined} onClick={() => onChange(item.value)} {...item.props}>
            {selected ? <Selected group={group} /> : null}
            {item.content(selected)}
          </button>
        );
      })}
    </div>
  );
}

function FontPicker({ value, onChange }) {
  return (
    <RadioCards label="Typeface" value={value} onChange={onChange} className="nx-look-fonts" cardClass="nx-look-font" group="font"
      items={FONTS.map(font => ({
        value: font.id, label: `${font.label}: ${font.hint}`, props: { "data-nx-font-card": font.id },
        content: selected => <>
          <span className="nx-look-font-sample" style={{ fontFamily: font.display, fontWeight: font.displayWeight, letterSpacing: font.tracking }}>Ag</span>
          <span className="nx-look-font-name" style={{ fontFamily: font.text }}>{font.label}</span>
          <span className="nx-look-font-hint">{font.hint}</span>
          {selected ? <Check size={13} className="nx-look-check" aria-hidden="true" /> : null}
        </>,
      }))} />
  );
}

const THEME_TILE = { background: "var(--nx-bg)", backgroundImage: "var(--nx-ambient)" };

function BackgroundPicker({ theme, look, image, onChange, onUpload, uploading }) {
  const bg = look.background;
  const value = bg.kind === "preset" ? `preset:${bg.preset}` : bg.kind;
  const presets = PRESETS[theme] || PRESETS.dark;
  const pick = id => {
    if (id === "theme") onChange({ background: { kind: "theme" } });
    else if (id.startsWith("preset:")) onChange({ background: { kind: "preset", preset: id.slice(7) } });
    else if (id === "solid") onChange({ background: { kind: "solid", color: bg.color || SWATCHES[theme]?.[1] || "#13241b" } });
    else if (id === "image") { if (bg.image) onChange({ background: { kind: "image" } }); else onUpload(); }
  };
  const tile = (id, label, style, extra = null) => ({
    value: id, label,
    content: () => <><span className="nx-look-bg-swatch" style={style}>{extra}</span><span className="nx-look-bg-name">{label}</span></>,
  });
  const pictureStyle = image.url ? { backgroundImage: `url("${image.url}")`, backgroundSize: "cover", backgroundPosition: "center" } : { background: "var(--nx-raised-2)" };
  return (
    <RadioCards label="Background" value={value} onChange={pick} className="nx-look-bgs" cardClass="nx-look-bg" group="bg" items={[
      tile("theme", "Theme", THEME_TILE),
      ...presets.map(p => tile(`preset:${p.id}`, p.label, { background: p.css }, p.grain ? <span className="nx-look-bg-grain" style={{ backgroundImage: GRAIN }} /> : null)),
      tile("solid", "Colour", { background: bg.color || SWATCHES[theme]?.[1] }, <Palette size={15} aria-hidden="true" />),
      tile("image", bg.image ? "Your picture" : "Picture", pictureStyle,
        uploading ? <span className="nx-look-bg-busy">Saving…</span> : image.url ? null : <ImagePlus size={16} aria-hidden="true" />),
    ]} />
  );
}

/** A native range input (keyboard, screen readers and touch for free), styled like the rest. */
function LookSlider({ label, value, max, unit, onChange, min = 0 }) {
  const id = useId();
  return (
    <div className="nx-look-slider">
      <div className="nx-look-slider-head">
        <label htmlFor={id}>{label}</label>
        <output htmlFor={id}>{value}{unit}</output>
      </div>
      <input id={id} type="range" className="nx-look-range" min={0} max={max} step={1} value={value}
        style={{ "--fill": `${(value / max) * 100}%`, "--floor": `${(min / max) * 100}%` }}
        aria-valuetext={`${value}${unit}`} onChange={event => onChange(Math.max(min, Number(event.target.value)))} />
    </div>
  );
}

/** Typeface, text size and background rows of the Look card. */
const SUN_HINTS = {
  dark: "Forest by night, Morning by day: the same forest, day and night.",
  light: "Morning by day, Forest by night: the same forest, day and night.",
  sunset: "Sunset's horizon already follows the sun. Add Night Green once it is fully dark.",
  paper: "After sunset the paper warms and dims a little, like a desk lamp. Text keeps its contrast.",
};

/** Settings > Look > Follow the sun: offered only for themes with a natural day/night pair (nxThemeRegistry daypair). Off by default. */
function SunControls({ picked, look, change }) {
  const pair = THEME_DAYPAIR[picked];
  if (!pair) return null;
  const sun = look.sun;
  const set = patch => change({ sun: { ...sun, ...patch } });
  const time = (field, label) => (
    <label className="nx-sun-time">{label}
      <input type="time" className="nx-input" value={sun[field]} step={60} aria-label={label}
        onChange={event => { if (/^\d\d:\d\d$/.test(event.target.value)) set({ [field]: event.target.value }); }} />
    </label>
  );
  return (
    <>
      <div className="nx-set-row" data-sun-row="follow">
        <span>Follow the sun<small className="nx-set-hint">{SUN_HINTS[picked]} Each change is a 40-minute crossfade by your clock.</small></span>
        <Segmented size="sm" label="Follow the sun" value={sun.follow ? "on" : "off"} onChange={value => set({ follow: value === "on" })}
          options={[{ value: "off", label: "Off" }, { value: "on", label: "On" }]} />
      </div>
      {sun.follow ? (
        <div className="nx-set-row" data-sun-row="times">
          <span>Sunrise and sunset<small className="nx-set-hint">Your local times. Neyvia does not guess a place; change them with the seasons.</small></span>
          <span className="nx-sun-times">{time("sunrise", "Sunrise")}{time("sunset", "Sunset")}</span>
        </div>
      ) : null}
      {sun.follow && pair.option === "intoNight" ? (
        <div className="nx-set-row" data-sun-row="into-night">
          <span>Into the night<small className="nx-set-hint">An hour after sunset the horizon fades to {THEME_LABELS[pair.night]}, and back at sunrise.</small></span>
          <Segmented size="sm" label="Into the night" value={sun.intoNight ? "on" : "off"} onChange={value => set({ intoNight: value === "on" })}
            options={[{ value: "off", label: "Off" }, { value: "on", label: "On" }]} />
        </div>
      ) : null}
    </>
  );
}

export function LookControls() {
  const { look, theme, background, image } = useLookView();
  const { change, error, setError } = useLookSaver();
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef(null);
  const bg = look.background;
  const picked = useOs(state => state.theme);

  const onFile = async event => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true); setError("");
    try {
      const id = await uploadBackground(file);
      change({ background: { kind: "image", image: id, dim: Math.max(bg.dim, 25), blur: bg.kind === "image" ? bg.blur : 8 } });
    } catch (failure) { setError(explainSettingsError(failure).message); }
    finally { setUploading(false); }
  };

  const guard = background.kind !== "theme" && background.raised
    ? `Dimmed to ${background.dim}% so text stays readable. You can dim more, not less.`
    : null;

  return (
    <>
      <SunControls picked={picked} look={look} change={change} />
      <div className="nx-set-row nx-look-row is-stacked">
        <span>Typeface<small className="nx-set-hint">Bundled with Neyvia or built into Windows, so it works offline.</small></span>
        <FontPicker value={look.font} onChange={font => change({ font })} />
      </div>
      <div className="nx-set-row">
        <span>Text size<small className="nx-set-hint">Scales all text in Neyvia.</small></span>
        <Segmented size="sm" label="Text size" value={look.textSize} onChange={textSize => change({ textSize })}
          options={TEXT_SIZES.map(size => ({ value: size.id, label: size.label }))} />
      </div>
      <div className="nx-set-row nx-look-row is-stacked">
        <span>Background<small className="nx-set-hint">Behind the chats and sidebar. Presets follow the theme.</small></span>
        <BackgroundPicker theme={theme} look={look} image={image} onChange={change}
          onUpload={() => fileInput.current?.click()} uploading={uploading} />
        <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={event => void onFile(event)} />
        {bg.kind === "solid" ? (
          <div className="nx-look-solid">
            <div className="nx-look-swatches" role="group" aria-label="Suggested colours">
              {(SWATCHES[theme] || []).map(color => (
                <button key={color} type="button" className={`nx-look-swatch${color === bg.color ? " is-on" : ""}`} style={{ background: color }}
                  aria-label={`Colour ${color}`} aria-pressed={color === bg.color} onClick={() => change({ background: { color } })} />
              ))}
            </div>
            <label className="nx-look-color">
              <input type="color" value={bg.color || "#13241b"} onChange={event => change({ background: { color: event.target.value.toLowerCase() } }, 250)} />
              <span>Any colour</span>
              <code>{background.raised ? shownColor(theme, bg.color, background.dim) : bg.color}</code>
            </label>
          </div>
        ) : null}
        {bg.kind === "image" ? (
          <div className="nx-look-image">
            <Button size="sm" variant="outline" icon={ImagePlus} disabled={uploading} onClick={() => fileInput.current?.click()}>{uploading ? "Saving…" : "Choose another picture…"}</Button>
            {image.error ? <p className="nx-notice is-error" role="alert">{image.error}</p> : null}
          </div>
        ) : null}
        {bg.kind !== "theme" ? (
          <div className="nx-look-sliders">
            <LookSlider label="Dim" value={background.dim} max={DIM_MAX} min={background.minDim} unit="%" onChange={dim => change({ background: { dim } }, 350)} />
            {bg.kind === "image" ? <LookSlider label="Blur" value={bg.blur} max={BLUR_MAX} unit=" px" onChange={blur => change({ background: { blur } }, 350)} /> : null}
          </div>
        ) : null}
        {guard ? <p className="nx-set-hint nx-look-guard" role="status">{guard}</p> : null}
      </div>
      {error ? <p className="nx-notice is-error" role="alert">{error}</p> : null}
    </>
  );
}
