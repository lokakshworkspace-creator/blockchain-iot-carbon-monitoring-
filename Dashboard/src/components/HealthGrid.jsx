/**
 * The five-layer health strip. Every tile's state comes from lib/health.js,
 * which only ever reports what the event stream actually evidences - an
 * 'unknown' tile means "we have no data on this yet", not "this is fine".
 */

const STATE_LABEL = {
  ok: 'Healthy',
  warn: 'Degraded',
  error: 'Problem',
  unknown: 'Unknown',
}

export default function HealthGrid({ components }) {
  return (
    <div className="health-grid">
      {components.map((component) => (
        <div key={component.name} className={`health-card state-${component.state}`}>
          <div className="health-head">
            <span className="health-dot" />
            <span className="health-name">{component.name}</span>
          </div>
          <div className="health-state">{STATE_LABEL[component.state]}</div>
          <div className="health-detail" title={component.detail}>
            {component.detail}
          </div>
        </div>
      ))}
    </div>
  )
}
