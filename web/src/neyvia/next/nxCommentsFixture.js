// Development-only stand-in for /api/ui/comments (`?fixtures=1` under `vite dev`; never bundled into a
// production build: nxComments imports it only behind `import.meta.env.DEV`). It follows
// plans/logs/COMMENTS-contract.md closely enough to design against: append-only revisions, per-target
// marker numbers, tombstones, delivery receipts. Comments live in localStorage so a reload keeps them.

const KEY = "nx.dev.comments";
const load = () => { try { return JSON.parse(localStorage.getItem(KEY) || "null") || { comments: [], sends: {} }; } catch { return { comments: [], sends: {} }; } };
const save = db => { try { localStorage.setItem(KEY, JSON.stringify(db)); } catch { /* best effort */ } };
const wait = () => new Promise(resolve => setTimeout(resolve, 80));
const now = () => new Date().toISOString();
const uid = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}${Math.random().toString(16).slice(2)}`;

export async function read({ target = "", status = "all" } = {}) {
  await wait();
  const db = load();
  const comments = db.comments.filter(comment => !comment.deleted && (!target || comment.target === target) && (status === "all" || comment.status === status));
  return { ok: true, comments, total: comments.length };
}

export async function write(body) {
  await wait();
  const db = load();
  const find = id => { const row = db.comments.find(comment => comment.id === id); if (!row) throw new Error("That comment is gone."); return row; };
  const touch = (row, patch) => { Object.assign(row, patch, { updatedAt: now(), revision: row.revision + 1 }); save(db); return { ok: true, comment: { ...row } }; };
  switch (body.op) {
    case "add": {
      if (!body.target || !body.anchor || !String(body.text || "").trim()) throw new Error("A comment needs a target, an anchor and words.");
      const number = Math.max(0, ...db.comments.filter(comment => comment.target === body.target).map(comment => comment.number)) + 1;
      const row = { id: `comment-${uid()}`, number, target: body.target, targetKind: body.targetKind || "dom", anchor: body.anchor, text: String(body.text).trim(), author: body.author || "you", status: "open", createdAt: now(), updatedAt: now(), revision: 1, delivery: null };
      db.comments.push(row); save(db);
      return { ok: true, comment: { ...row } };
    }
    case "edit": return touch(find(body.id), { ...(body.text != null ? { text: String(body.text).trim() } : {}), ...(body.anchor ? { anchor: body.anchor } : {}) });
    case "resolve": return touch(find(body.id), { status: "resolved" });
    case "reopen": return touch(find(body.id), { status: "open" });
    case "delete": return touch(find(body.id), { deleted: true });
    case "send": {
      if (body.requestId && db.sends[body.requestId]) return db.sends[body.requestId];
      const ids = body.ids || (body.id ? [body.id] : db.comments.filter(comment => !comment.deleted && comment.status === "open" && (!body.target || comment.target === body.target)).map(comment => comment.id));
      const rows = ids.map(find).filter(row => row.status === "open");
      if (!rows.length) throw new Error("There are no open comments to send.");
      if (!body.sessionId && !body.runId && !body.newSession) throw new Error("Choose where to send the comments.");
      const messageId = `comments-message-${uid()}`;
      const receipt = { ok: true, messageId, requestId: body.requestId, commentIds: rows.map(row => row.id), channel: body.runId ? "steer" : body.newSession ? "new-run" : "session", runId: body.runId || `run-${uid()}`, sessionId: body.sessionId || null, delivery: { messageId, sentAt: now() } };
      for (const row of rows) { row.delivery = { messageId, channel: receipt.channel, runId: receipt.runId, sessionId: receipt.sessionId, sentAt: now() }; row.updatedAt = now(); row.revision += 1; }
      db.sends[body.requestId || messageId] = receipt; save(db);
      return receipt;
    }
    default: throw new Error(`Unknown comments op: ${body.op}`);
  }
}

// What an agent does with `neyvia.comments.resolve` / `.add`, for design states and screenshots.
if (globalThis.window) {
  globalThis.window.__nxCommentsFixture = {
    agentResolve: async id => { await write({ op: "resolve", id }); await window.__nxComments?.reload?.(); },
    agentAdd: async (target, anchor, text, author = "reviewer") => { await write({ op: "add", target, targetKind: "app-factory", anchor, text, author }); await window.__nxComments?.reload?.(); },
    reset: () => { try { localStorage.removeItem(KEY); } catch { /* nothing to clear */ } },
  };
}
