export const SOURCE_NAMES = { sessions: "Connected sessions", parallel: "Parallel branches", conductor: "Conductor", missions: "Missions", nightshift: "Night Shift" };
export const STATE_NAMES = { working: "Working", waiting: "Waiting for you", asking: "Asking", done: "Done", failed: "Failed", stopped: "Stopped", ended: "Ended", unknown: "Not started / unreported" };

/** Retain ancestors as context when a filter selects a child. Never invent a parent. */
export function overviewGroups(data, filter, grouping, project = "") {
  const nodes = data?.nodes || [];
  const byId = new Map(nodes.map(row => [row.id, row]));
  const inProject = row => !project || row.project === project || [row.worktree, row.project].some(path =>
    path && path.replaceAll("\\", "/").toLowerCase().startsWith(project.replaceAll("\\", "/").toLowerCase().replace(/\/$/, "") + "/"));
  const matches = new Set(nodes.filter(row => inProject(row) &&
    (filter === "all" || filter === "working" && row.state === "working" || filter === "needs" && ["waiting", "asking"].includes(row.state))).map(row => row.id));
  const selected = new Set(matches);
  for (const id of matches) {
    let parent = byId.get(id)?.parentId;
    const visited = new Set([id]);
    while (parent && byId.has(parent) && !visited.has(parent)) {
      selected.add(parent); visited.add(parent); parent = byId.get(parent).parentId;
    }
  }
  const groups = new Map();
  const depth = row => {
    let count = 0, parent = row.parentId;
    const visited = new Set([row.id]);
    while (parent && byId.has(parent) && !visited.has(parent)) {
      count++; visited.add(parent); parent = byId.get(parent).parentId;
    }
    return count;
  };
  for (const row of nodes.filter(row => selected.has(row.id))) {
    let root = row; const visited = new Set([row.id]);
    while (root.parentId && byId.has(root.parentId) && !visited.has(root.parentId)) { visited.add(root.parentId); root = byId.get(root.parentId); }
    const key = grouping === "project" ? root.project || "No project" : root.source;
    if (!groups.has(key)) groups.set(key, { key, title: grouping === "project" ? key : SOURCE_NAMES[key] || key, levels: [], byId: new Map(), edges: [] });
    const group = groups.get(key), level = depth(row);
    (group.levels[level] ||= []).push({ ...row, context: !matches.has(row.id), status: row.state === "working" ? "running" : row.state });
    group.byId.set(row.id, row);
  }
  for (const group of groups.values()) {
    group.levels = group.levels.filter(Boolean);
    const parents = new Set([...group.byId.values()].map(row => row.parentId).filter(Boolean));
    for (const level of group.levels) level.sort((a, b) =>
      Number(b.state === "working") - Number(a.state === "working") || Number(parents.has(b.id)) - Number(parents.has(a.id)));
    group.edges = (data?.edges || []).filter(edge => group.byId.has(edge.from) && group.byId.has(edge.to));
  }
  return [...groups.values()];
}
