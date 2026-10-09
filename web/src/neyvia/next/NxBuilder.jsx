import { useMemo } from "react";
import { ArrowRight, Bell, FolderOpen, GitBranch, History, Network, Plus, SquarePen } from "lucide-react";

import "./nxBuilder.css";
import { ProviderMark } from "./ProviderMark.jsx";
import { NxGrowingTree } from "./NxGrowingTree.jsx";
import { Button, Icon, IconButton, StatusDot, ago, elapsed, useTick } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import { isNeedsYou, placeSession } from "./nxSidebarModel.js";
import { markFor } from "./NxSidebarParts.jsx";
import { useMissions } from "./NxMissions.jsx";

// Builder: every project at a glance, so thinking about all the work is easy
// Each project
// card says what needs you, what is running, which missions work there, and
// offers the next step. "Next up" orders the whole day: answers first, then
// blocked missions, then running work. Opens as the "builder" stage pane.

const sameFolder = (a, b) => String(a || "").replace(/[\\/]+$/, "").toLowerCase() === String(b || "").replace(/[\\/]+$/, "").toLowerCase();

function projectsFrom(rows, missions, now) {
  const found = new Map();
  for (const row of rows) {
    if (row.archived) continue;
    const place = placeSession(row);
    if (place.group !== "project") continue;
    const key = place.project.toLowerCase();
    const project = found.get(key) || { key, name: place.project, path: place.path, chats: [], needs: [], running: [], latest: null };
    project.chats.push(row);
    if (isNeedsYou(row, now)) project.needs.push(row);
    if (row.status === "working") project.running.push(row);
    if (!project.latest || String(row.updated_at || "") > String(project.latest.updated_at || "")) project.latest = row;
    found.set(key, project);
  }
  for (const project of found.values()) project.missions = missions.filter(mission => sameFolder(mission.folder, project.path));
  const weight = project => project.needs.length * 100 + project.running.length * 10 + project.missions.filter(mission => mission.status === "running").length * 10;
  return [...found.values()].sort((a, b) => weight(b) - weight(a) || String(b.latest?.updated_at || "").localeCompare(String(a.latest?.updated_at || "")));
}

function nextUp(projects, missions) {
  const items = [];
  for (const project of projects) for (const row of project.needs) items.push({ key: `n:${row.id}`, tone: "needs", text: row.title || "Untitled chat", where: project.name, chat: row.id });
  for (const mission of missions) {
    for (const task of mission.tasks.filter(item => item.status === "blocked")) items.push({ key: `b:${task.id}`, tone: "blocked", text: `${task.title || task.localId} is blocked`, where: mission.goal, mission: mission.id });
    if (mission.phase === "draft") items.push({ key: `d:${mission.id}`, tone: "draft", text: "Review and start this mission", where: mission.goal, mission: mission.id });
    if (mission.acceptance === "evidence_ready_for_review" && mission.status !== "stopped") items.push({ key: `a:${mission.id}`, tone: "done", text: "Check the evidence against the acceptance checks", where: mission.goal, mission: mission.id });
  }
  return items.slice(0, 8);
}

function ProjectCard({ project, onOpenChat, onNewChat }) {
  const branch = project.latest?.git_branch;
  return (
    <article className="nx-bd-card" aria-label={project.name}>
      <header>
        <Icon as={FolderOpen} size={15} className="nx-bd-card-icon" />
        <h3 title={project.path}>{project.name}</h3>
        <span className="nx-bd-card-when">{ago(project.latest?.updated_at)}</span>
      </header>
      <p className="nx-bd-card-meta">
        <span>{project.chats.length} chat{project.chats.length === 1 ? "" : "s"}</span>
        {branch ? <span><Icon as={GitBranch} size={11} />{branch}</span> : null}
        {project.missions.length ? <span><Icon as={Network} size={11} />{project.missions.length} mission{project.missions.length === 1 ? "" : "s"}</span> : null}
      </p>
      <div className="nx-bd-lines">
        {project.needs.map(row => (
          <button key={row.id} type="button" className="nx-bd-line is-needs" onClick={() => onOpenChat(row.id)}>
            <StatusDot tone={row.status === "failed" ? "red" : "gold"} /><span className="nx-bd-line-title">{row.title || "Untitled chat"}</span><em>needs you</em>
          </button>
        ))}
        {project.running.map(row => (
          <button key={row.id} type="button" className="nx-bd-line is-running" onClick={() => onOpenChat(row.id)}>
            <NxGrowingTree size={15} /><span className="nx-bd-line-title">{row.title || "Untitled chat"}</span><em>{row.status_since ? elapsed(row.status_since) : "running"}</em>
          </button>
        ))}
        {project.missions.map(mission => (
          <button key={mission.id} type="button" className="nx-bd-line" onClick={() => os.showPane("mission", mission.id)}>
            <Icon as={Network} size={13} /><span className="nx-bd-line-title">{mission.goal}</span><em>{mission.counts.done}/{mission.tasks.length}</em>
          </button>
        ))}
        {!project.needs.length && !project.running.length && !project.missions.length && project.latest ? (
          <button type="button" className="nx-bd-line is-quiet" onClick={() => onOpenChat(project.latest.id)}>
            <ProviderMark id={markFor(project.latest)} size={13} /><span className="nx-bd-line-title">{project.latest.title || "Untitled chat"}</span><em>latest</em>
          </button>
        ) : null}
      </div>
      <footer>
        <Button size="sm" icon={SquarePen} onClick={() => onNewChat({ folder: { path: project.path, name: project.name } })}>New chat</Button>
        <Button size="sm" icon={Plus} onClick={() => os.showPane("mission", `new:${project.path}`)}>Mission</Button>
        {project.latest ? <IconButton icon={History} size="sm" label={`Replay the latest chat in ${project.name}`} onClick={() => os.showPane("replay", project.latest.id)} /> : null}
      </footer>
    </article>
  );
}

export function NxBuilder({ rows, onOpenChat, onNewChat }) {
  const { missions } = useMissions();
  const tasks = useOs(state => state.nightshift);
  const now = Date.now();
  useTick(rows.some(row => row.status === "working"), 15000);
  const projects = useMemo(() => projectsFrom(rows, missions, now), [rows, missions]); // eslint-disable-line react-hooks/exhaustive-deps
  const queue = useMemo(() => nextUp(projects, missions), [projects, missions]);
  const stats = [
    { label: "need you", value: projects.reduce((sum, project) => sum + project.needs.length, 0), tone: "needs" },
    { label: "running", value: rows.filter(row => row.status === "working" && !row.archived).length, tone: "running" },
    { label: "missions active", value: missions.filter(mission => mission.status === "running").length, tone: "missions" },
    { label: "tasks done", value: Object.values(tasks).filter(task => task.status === "done").length + missions.reduce((sum, mission) => sum + mission.counts.done, 0), tone: "done" },
  ];

  return (
    <section className="nx-bd nx-scroll" aria-label="Builder">
      <header className="nx-bd-head">
        <div>
          <h2>Builder</h2>
          <p>Every project, what needs you, and what's growing.</p>
        </div>
        <div className="nx-bd-stats">
          {stats.map(stat => <span key={stat.label} className={`is-${stat.tone}`}><strong>{stat.value}</strong>{stat.label}</span>)}
        </div>
      </header>

      {queue.length ? (
        <section className="nx-bd-next" aria-label="Next up">
          <h3><Icon as={Bell} size={14} />Next up</h3>
          {queue.map(item => (
            <button key={item.key} type="button" className={`nx-bd-next-item is-${item.tone}`}
              onClick={() => (item.chat ? onOpenChat(item.chat) : os.showPane("mission", item.mission))}>
              <span>{item.text}</span><em>{item.where}</em><Icon as={ArrowRight} size={13} />
            </button>
          ))}
        </section>
      ) : null}

      {projects.length ? (
        <div className="nx-bd-grid">
          {projects.map(project => <ProjectCard key={project.key} project={project} onOpenChat={onOpenChat} onNewChat={onNewChat} />)}
        </div>
      ) : <p className="nx-bd-empty">Chats started in a project folder gather here, one card per project.</p>}
    </section>
  );
}
