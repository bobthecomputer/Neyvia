// Keep the documented `cd web; npx vite build` entry on the repository config.
// runner mode avoids writing Vite's bundled config into the dependency junction.
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import config from "../vite.config.mjs";

export default env => {
  const repo = fileURLToPath(new URL("..", import.meta.url));
  return { ...config(env), cacheDir: resolve(repo, ".agent_control/mod/vite-cache") };
};
