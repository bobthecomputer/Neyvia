import { NxStage } from "./NxStage.jsx";
import { LookControls } from "./NxLook.jsx";
import { useEffect, useState } from "react";
import { NxAgentView } from "./agentview/NxAgentView.jsx";
import { holdExampleRuns } from "./agentview/nxAgentViewApi.js";
import { exampleRuns } from "./agentview/nxAgentViewExample.js";
import { PlacementControls } from "./NxPlacement.jsx";

const NOOP = () => {};
const NAV = { onNewChat: NOOP };

// These scenes mount the shipped read-only entry screens. No generation,
// editor connection, chat turn or consent is started by the tour.
function AppScene({ app }) {
  return <div className="nx-tour-feature"><NxStage stage={{ type: "app", app }} readOnly nav={NAV} onClose={NOOP} /></div>;
}
export function LookScene() {
  return <div className="nx-tour-feature nx-scroll"><LookControls /></div>;
}
// The real "Agents at work" cards on two made-up runs. The example is held before the cards first ask
// (a child asks before its parent's effects run) and let go when the scene ends.
export function WatchingScene() {
  const [release] = useState(() => holdExampleRuns(exampleRuns()));
  useEffect(() => release, [release]);
  return <div className="nx-tour-feature"><NxAgentView /></div>;
}
export function FactoryScene() { return <AppScene app="app-factory" />; }
export function ConnectorsScene() { return <AppScene app="3d-studio" />; }
export function ImagesScene() { return <AppScene app="image-studio" />; }
export function PlacementScene({ p }) {
  const placement = p < .25 ? "main" : p < .5 ? "side" : p < .75 ? "full" : "bubble";
  const win = { id: "tour:placement", placement };
  return <div className={`nx-tour-feature is-placement-${placement}`}>
    <header><strong>Apps anywhere</strong><PlacementControls win={win} title="App" phone={false} sideOnLeft={false} onPlace={NOOP} onRestore={NOOP} /></header>
    <p>{placement === "main" ? "Beside the chat" : placement === "side" ? "In the side panel" : placement === "full" ? "Full screen" : "A bubble you can reopen"}</p>
    <div className="nx-tour-placement-preview"><AppScene app="laya" /></div>
  </div>;
}
