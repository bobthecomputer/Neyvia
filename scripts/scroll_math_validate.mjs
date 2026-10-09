import katex from './scroll_vendor/package/dist/katex.mjs';
let raw = '';
for await (const part of process.stdin) raw += part;
const errors = [];
for (const item of JSON.parse(raw)) {
  try { katex.renderToString(item.tex, {throwOnError: true, strict: 'error', trust: false, maxExpand: 1000}); }
  catch (error) { errors.push({cardId: item.cardId, rule: 'math', message: error.message}); }
}
process.stdout.write(JSON.stringify(errors));
