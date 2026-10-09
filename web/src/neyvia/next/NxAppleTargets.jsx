import {useState} from "react";
import {ChevronDown, Download, Hammer, Smartphone} from "lucide-react";
import {Button, Icon} from "./nxPrimitives.jsx";
import {CopyPath, JobLine, Missing} from "./NxMobileBuildParts.jsx";
import {backendBase} from "./nxApi.js";
export function AppleTargets({status, busy, onAction}) {
  const [target, setTarget] = useState("macos");
  const [answer, setAnswer] = useState(null);
  const [resultFolder, setResultFolder] = useState("");
  const supported = status.apple?.targets?.[target]?.build;
  const run = async (action, args) => setAnswer(await onAction(action, {...args, project: status.project.root}));
  const last = status.builds?.[target];
  const job = status.jobs?.find(row => row.platform === target && row.project === status.project.root);
  const names = {macos:"Mac", ipados:"iPad", watchos:"Watch", tvos:"Apple TV", visionos:"Vision Pro"};
  return <section className="nx-ms-card" aria-label="Apple targets">
    <header><strong>Apple targets</strong><span>Built here on Windows</span></header>
    <select className="nx-ms-select" aria-label="Apple build target" value={target} onChange={e=>{setTarget(e.target.value);setAnswer(null);}}>
      {Object.entries(names).map(([value,name])=><option key={value} value={value}>{name}</option>)}
    </select>
    <p className="nx-ms-copy">{status.apple?.targets?.[target]?.kind}</p>
    <Button size="sm" icon={Hammer} disabled={busy || !supported || job?.status === "running"} onClick={()=>run("build", {platform:target})}>Build {target === "macos" ? ".app + ZIP" : ".ipa"}</Button>
    <Button size="sm" disabled={busy || last?.status !== "completed"} onClick={()=>run("verify", {platform:target})}>Verify bundle</Button>
    <JobLine job={job}/>
    {last?.status === "completed" ? <CopyPath path={last.artifactPath}/> : null}
    <details><summary>Preview and try it</summary>
      <p className="nx-ms-copy">Instant preview emulates web behaviour. It does not run Apple's operating system.</p>
      <Button size="sm" onClick={()=>run("simulate", {tier:"instant",platform:target})}>Show {names[target]} frame</Button>
      <Button size="sm" disabled={!supported} onClick={()=>run("simulate", {tier:"device",platform:target})}>Real-device steps</Button>
      <p className="nx-ms-copy">Real Simulator uses an optional macOS runner in your GitHub account. Off by default; preparation starts no run. Review your allowance and billing before enabling it.</p>
      <Button size="sm" disabled={busy || !["macos","ipados"].includes(target)} onClick={()=>run("simulate", {tier:"cloud",platform:target === "ipados" ? "ipados" : "ios"})}>Prepare {target === "ipados" ? "iPad" : "iPhone"} Simulator workflow</Button>
      <label>Downloaded Simulator result folder<input value={resultFolder} onChange={e=>setResultFolder(e.target.value)} placeholder="Folder containing cloud-outcome.json" /></label>
      <Button size="sm" disabled={busy || !resultFolder.trim()} onClick={()=>run("simulate", {tier:"cloud",platform:target === "ipados" ? "ipados" : "ios",results:resultFolder})}>Import screenshot</Button>
      {status.cloudResult?.screenshotUrl ? <figure><img alt="Imported Apple Simulator screenshot" src={backendBase()+status.cloudResult.screenshotUrl} style={{maxWidth:"100%"}}/><figcaption>Imported result · <a href={status.cloudResult.runUrl} target="_blank" rel="noreferrer">GitHub run</a></figcaption></figure> : null}
    </details>
    {answer ? <div className="nx-ms-copy" role="status">{answer.error || answer.needsPaul || answer.note || answer.job?.step || (answer.slices ? "Bundle hashes verified; native launch needs Apple hardware." : answer.status || "Preview selected")}{answer.path ? <CopyPath path={answer.path}/> : null}{answer.steps ? <ol>{answer.steps.map(step=><li key={step}>{step}</li>)}</ol> : null}</div> : null}
  </section>;
}
export function IosCard({ status, busy, onBuild, onSetup }) {
  const ios = status.ios || {};
  const job = (status.jobs || []).find(row => row.platform === "ios" && row.project === status.project?.root);
  const last = status.builds?.ios;
  const [guide, setGuide] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const running = job?.status === "running";
  return (
    <section className="nx-ms-card" aria-label="iPhone">
      <header><Icon as={Smartphone} size={15} /><strong>iPhone</strong><span>{ios.ready ? "Ready to build" : "Needs the iPhone compiler"}</span></header>
      {!ios.ready ? (
        <>
          <p className="nx-ms-copy">Neyvia compiles the .ipa right here on Windows. It needs a one-time {ios.totalMissing} download.</p>
          <Missing items={ios.missing} />
          {confirm ? (
            <div className="nx-ms-confirm">
              <span>Download {ios.totalMissing} from GitHub (checked against pinned checksums)?</span>
              <Button size="sm" variant="primary" icon={Download} onClick={() => { setConfirm(false); onSetup(); }}>Download</Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>Not now</Button>
            </div>
          ) : <Button size="sm" variant="outline" icon={Download} disabled={running} onClick={() => setConfirm(true)}>Install iPhone compiler</Button>}
        </>
      ) : (
        <Button size="sm" variant="primary" icon={Hammer} disabled={busy || running} onClick={onBuild}>Build .ipa</Button>
      )}
      <JobLine job={job} />
      {last?.status === "completed" ? <div className="nx-ms-artifact"><span>Last .ipa</span><CopyPath path={last.ipaPath || last.artifactPath} /></div> : null}
      <button type="button" className="nx-ms-disclosure" aria-expanded={guide} onClick={() => setGuide(!guide)}>
        <Icon as={ChevronDown} size={13} /> Put it on your iPhone with a free Apple ID
      </button>
      {guide ? <ol className="nx-ms-steps">{(ios.sideload || []).map(step => <li key={step}>{step}</li>)}</ol> : null}
    </section>
  );
}

