// Untracked: a fixtures build for the theme screenshot rig (import.meta.env.DEV true so ?fixtures=1 works).
import base from "./vite.config.mjs";
export default env => {
  const config = base(env);
  return { ...config, define: { ...(config.define || {}), "import.meta.env.DEV": "true" } };
};
