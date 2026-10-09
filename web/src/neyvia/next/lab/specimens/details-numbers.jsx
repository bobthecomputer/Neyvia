import { useState } from "react";
import { Minus, Plus } from "lucide-react";

import { Button } from "../../nxPrimitives.jsx";
import { Meter, PRESS, RollingNumber } from "../../details/nxDetails.jsx";
import "./details.css";

// Details: numbers and progress (plan 17 A2). Press the buttons to watch the wheels roll
// the short way and the meter fill; "Start a task" creeps toward 90 % until "Finish".
export const title = "Details: numbers and progress";

export default function DetailsNumbers() {
  const [count, setCount] = useState(98);
  const [size, setSize] = useState(12.4);
  const [steps, setSteps] = useState(2);
  const [task, setTask] = useState({ startedAt: null, done: false });
  return (
    <div className="nx-lab-sheet">
      <div className="nx-lab-row">
        <span className="nx-dl-figure"><RollingNumber value={count} /></span>
        <Button size="sm" icon={Plus} className={PRESS} onClick={() => setCount(value => value + 1)}>Add 1</Button>
        <Button size="sm" icon={Plus} className={PRESS} onClick={() => setCount(value => value + 27)}>Add 27</Button>
        <Button size="sm" icon={Minus} className={PRESS} onClick={() => setCount(value => Math.max(0, value - 1))}>Take 1</Button>
      </div>
      <div className="nx-lab-row">
        <span className="nx-dl-inline">Notes folder: <RollingNumber value={size} decimals={1} suffix=" MB" /></span>
        <Button size="sm" className={PRESS} onClick={() => setSize(value => Math.round((value + 3.7) * 10) / 10)}>Add a file</Button>
      </div>
      <div className="nx-lab-row">
        <span className="nx-dl-inline"><RollingNumber value={steps} /> of 4 steps</span>
        <Meter value={steps} max={4} label="Steps done" />
        <Button size="sm" className={PRESS} onClick={() => setSteps(value => (value + 1) % 5)}>{steps === 4 ? "Start over" : "Next step"}</Button>
      </div>
      <div className="nx-lab-row">
        <span className="nx-dl-inline">{task.done ? "Finished" : task.startedAt ? "Working, about 6 s" : "Idle"}</span>
        <Meter startedAt={task.startedAt ?? undefined} estimateMs={6000} done={task.done} tone="running" label="Task progress" className="nx-dl-wide" />
        {task.startedAt && !task.done
          ? <Button size="sm" className={PRESS} onClick={() => setTask(value => ({ ...value, done: true }))}>Finish</Button>
          : <Button size="sm" className={PRESS} onClick={() => setTask({ startedAt: Date.now(), done: false })}>Start a task</Button>}
      </div>
    </div>
  );
}
