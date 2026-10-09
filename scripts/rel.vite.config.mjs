import config from '../vite.config.mjs';
import { resolve } from 'node:path';
export default env => ({ ...config(env), cacheDir: resolve('.agent_control/rel/vite-cache') });
