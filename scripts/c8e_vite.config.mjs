import config from '../vite.config.mjs';
import { resolve } from 'node:path';

// Package the actual design specimens as well as the product. All entries share
// the candidate's authenticated origin; no extra server or development fallback.
export default env => {
  const base = config(env);
  return {
    ...base,
    cacheDir: resolve('.agent_control/C8e/vite-cache'),
    build: {
      ...base.build,
      rollupOptions: {
        ...base.build.rollupOptions,
        input: {
          product: resolve('web/index.html'),
          design: resolve('web/design-lab.html'),
          kit: resolve('web/src/neyvia/next/details/kit/demo.html'),
        },
      },
    },
  };
};
