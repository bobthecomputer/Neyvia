import { GRAIN } from "./nxLookModel.js";

// Settings > Look: what sits behind the chats when it isn't the theme's own
// (a preset, a colour or your picture), under a layer of the theme's
// background colour at the dim the contrast guard allows. Styles: nxLook.css.

/** The background layer under the whole shell. Rendered by NxShell. */
export function NxBackdrop({ background, imageUrl }) {
  if (background.kind === "theme") return null;
  const fill = background.kind === "image"
    ? { backgroundImage: imageUrl ? `url("${imageUrl}")` : "none", filter: background.blur ? `blur(${background.blur}px)` : undefined }
    : { background: background.layer };
  return (
    <div className="nx-backdrop" aria-hidden="true">
      <div className={`nx-backdrop-fill${background.blur ? " is-blurred" : ""}`} style={fill} />
      {background.grain ? <div className="nx-backdrop-grain" style={{ backgroundImage: GRAIN, opacity: background.grain * 4 }} /> : null}
      <div className="nx-backdrop-dim" style={{ background: background.overlay, opacity: background.dim / 100 }} />
    </div>
  );
}

