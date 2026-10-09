// Keep generated Vite data out of the shared node_modules junction.
import { resolve } from "node:path";
import { createServer } from "vite";

const backend = new URL(process.env.FLUXIO_WEB_BACKEND_URL || "http://127.0.0.1:48131");
if (backend.protocol !== "http:" || backend.hostname !== "127.0.0.1" || Number(backend.port) < 48131 || Number(backend.port) > 48139) {
  throw new Error("The T3 backend must use 127.0.0.1 and ports 48131-48139");
}
process.env.FLUXIO_WEB_BACKEND_URL = backend.origin;
const server = await createServer({
  configFile: resolve("vite.config.mjs"),
  cacheDir: resolve("scripts/evidence/T3-vite-cache"),
  server: { host: "127.0.0.1", port: 48132, strictPort: true },
});
await server.listen();
server.printUrls();
