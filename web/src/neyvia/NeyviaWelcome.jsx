import { ArrowRight, GitBranch, ShieldCheck, FolderOpen, Terminal, Cpu, ArrowUpRight, Eye } from "lucide-react";
import "./neyviaWelcome.css";

const repository = "https://github.com/bobthecomputer/Neyvia";
const capabilities = [
  { Icon: Eye, number: "01", title: "A model that can see your apps", description: "LAYA, a small local model, reads the screen of an app that is being built or used, so an agent can fix what it cannot see in code." },
  { Icon: GitBranch, number: "02", title: "Every agent on one mission", description: "Split a goal across Claude Code, Codex and Neyvia's own agent. Each task keeps its model and its place in the plan, and Claude Code stays on your own plan." },
  { Icon: ShieldCheck, number: "03", title: "Manuals that run, and receipts", description: "A manual is a procedure Neyvia executes and checks. Every step ends in a pass or a fail you can open, and every run keeps its evidence." },
];

export function NeyviaWelcome() {
  return (
    <main className="neyvia-welcome">
      <a className="neyvia-skip-link" href="#overview">Skip to main content</a>
      <nav aria-label="Neyvia" className="neyvia-welcome-nav">
        <a className="neyvia-welcome-brand" href="/" aria-label="Neyvia home"><img src="/icons/neyvia-mark.svg" alt="" width="34" height="34" /> NEYVIA</a>
        <div><a href="#workflow">How it works</a><a href="#setup">Get started</a><a className="neyvia-welcome-open" href="/control">Open workspace <ArrowUpRight size={16} aria-hidden="true" /></a></div>
      </nav>

      <section id="overview" className="neyvia-welcome-hero">
        <div className="neyvia-welcome-copy">
          <p className="neyvia-welcome-eyebrow"><span /> Your workspace. Your agents.</p>
          <h1>Good ideas deserve<br />to become <em>real work.</em></h1>
          <p className="neyvia-welcome-lede">One place to work with all your AI agents, see your apps, and keep proof of what was done. It runs on your PC, and your sign-ins and plan limits stay yours.</p>
          <div className="neyvia-welcome-actions"><a className="neyvia-welcome-primary" href="/control">Open your workspace <ArrowRight size={18} aria-hidden="true" /></a><a href="#setup">Set up locally <span aria-hidden="true">↗</span></a></div>
          <p className="neyvia-welcome-note">Runs on your PC · Your own sign-ins · Optional NAS hosting</p>
        </div>
        <aside className="neyvia-welcome-path" aria-label="The Neyvia workflow">
          <header><span>FROM INTENT TO OUTPUT</span><GitBranch size={19} aria-hidden="true" /></header>
          <div className="neyvia-welcome-path-goal"><span>YOUR GOAL</span><strong>Make something worth using.</strong><p>Bring the idea. Keep the context.</p></div>
          <ol>
            <li><span>1</span><div><strong>Choose the approach</strong><p>One assistant, or a mission across several providers.</p></div></li>
            <li><span>2</span><div><strong>Follow the work</strong><p>See agent activity and resolve what needs you.</p></div></li>
            <li><span>3</span><div><strong>Review the result</strong><p>Inspect outputs, then decide what comes next.</p></div></li>
          </ol>
          <footer><ShieldCheck size={17} aria-hidden="true" /><span>A workflow guide. Your live activity appears in the workspace.</span></footer>
        </aside>
      </section>

      <section id="workflow" className="neyvia-welcome-workflow">
        <div className="neyvia-welcome-section-heading"><p className="neyvia-welcome-eyebrow">WHAT MAKES IT DIFFERENT</p><h2>What a plain chat does not do.</h2></div>
        <div className="neyvia-welcome-features">{capabilities.map(({ Icon, number, title, description }) => <article key={number}><div><Icon size={24} aria-hidden="true" /><span>{number}</span></div><h3>{title}</h3><p>{description}</p></article>)}</div>
      </section>

      <section id="setup" className="neyvia-welcome-setup">
        <div><p className="neyvia-welcome-eyebrow">MAKE IT YOURS</p><h2>Start local.<br />Grow from there.</h2><p>Setup takes about three minutes and every step can be skipped. Add a NAS later if you want an always available host.</p><a href={`${repository}#readme`} target="_blank" rel="noreferrer">Read the setup guide <ArrowUpRight size={16} aria-hidden="true" /></a></div>
        <div className="neyvia-welcome-setup-steps">
          <article><Terminal aria-hidden="true" size={20} /><div><h3>Install and open</h3><p>From the repository, install the dependencies and start Neyvia. It opens in your browser.</p><pre aria-label="Local startup commands"><code>npm ci{"\n"}npm run neyvia</code></pre><small>Needs Node.js, Python 3.11+ and uv.</small></div></article>
          <article><Cpu aria-hidden="true" size={20} /><div><h3>Choose your downloads</h3><p>Core is on. Turn on the Claude Code mod, Neyvia skills for Codex or optional packs when you want them. Each part keeps itself current.</p></div></article>
          <article><FolderOpen aria-hidden="true" size={20} /><div><h3>Connect your agents</h3><p>Use the Claude Code, Codex or other sign-ins you already have. Start with a small task in a project folder, then give your agents more.</p></div></article>
        </div>
      </section>
      <footer className="neyvia-welcome-footer"><span>NEYVIA <span className="neyvia-welcome-footer-note">Built for people who make things.</span></span><a href={repository} target="_blank" rel="noreferrer">Repository <ArrowUpRight size={15} aria-hidden="true" /></a></footer>
    </main>
  );
}
