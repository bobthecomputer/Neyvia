import { Button, StatusDot } from '../../nxPrimitives.jsx';
import './agent-run-card.css';

function AgentRunCard({ name, state, duration, path, onOpen, onStop, onAnswer }) {
  const stateTone = {
    running: 'live',
    needs: 'gold',
    done: 'green',
    failed: 'red'
  }[state];

  const stateLabel = {
    running: 'Running',
    needs: 'Needs you',
    done: 'Done',
    failed: 'Failed'
  }[state];

  return (
    <div className="nx-agent-run-card">
      <div className="nx-agent-run-card-header">
        <div className="nx-agent-run-card-title-section">
          <h3 className="nx-agent-run-card-name">{name}</h3>
          <div className="nx-agent-run-card-state">
            <StatusDot tone={stateTone} pulse={state === 'running'} />
            <span>{stateLabel}</span>
          </div>
        </div>
      </div>

      <div className="nx-agent-run-card-path">{path}</div>

      <div className="nx-agent-run-card-footer">
        <div className="nx-agent-run-card-duration">{duration}</div>
        <div className="nx-agent-run-card-actions">
          {state === 'running' && (
            <>
              <Button variant="ghost" size="sm" onClick={onStop}>Stop</Button>
              <Button variant="ghost" size="sm" onClick={onOpen}>Open</Button>
            </>
          )}
          {state === 'needs' && (
            <>
              <Button variant="primary" size="sm" onClick={onAnswer}>Answer</Button>
              <Button variant="ghost" size="sm" onClick={onOpen}>Open</Button>
            </>
          )}
          {(state === 'done' || state === 'failed') && (
            <Button variant="ghost" size="sm" onClick={onOpen}>Open</Button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function AgentRunCardSpecimen() {
  const cards = [
    {
      name: 'Build and test',
      state: 'running',
      duration: 'Working 3m',
      path: '/projects/mobile-app/build-pipeline',
    },
    {
      name: 'API integration check',
      state: 'needs',
      duration: 'Waiting 2m',
      path: '/workspace/backend-services/integration-tests',
    },
    {
      name: 'Generate test data',
      state: 'done',
      duration: 'Done 5m ago',
      path: '/data/fixtures/production-mirror',
    },
    {
      name: 'Security scan',
      state: 'failed',
      duration: 'Failed 2m ago',
      path: '/security-tests/production-environment',
    },
  ];

  return (
    <div className="nx-agent-run-card-specimen">
      {cards.map((card, i) => (
        <AgentRunCard
          key={i}
          {...card}
          onOpen={() => {}}
          onStop={() => {}}
          onAnswer={() => {}}
        />
      ))}
    </div>
  );
}

export const title = 'Agent run card';
