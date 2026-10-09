import { avatarHue, initials } from "./nxAccountsModel.js";

/** A person's initials on a sun- or leaf-toned disc, the same colour on every screen. Styles: neyviaSignIn.css. */
export function NxAvatar({ username, name, size = 40 }) {
  return (
    <span className="ny-avatar" aria-hidden="true"
      style={{ "--hue": avatarHue(username), width: size, height: size, fontSize: Math.round(size * 0.4) }}>
      {initials(name || username)}
    </span>
  );
}
