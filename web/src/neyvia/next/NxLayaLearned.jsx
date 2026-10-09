export function LayaLearned({ instant }) {
  if (!instant?.recent?.length) return null;
  const latest = instant.recent[0];
  const label = String(latest.label);
  return <section className="nx-laya-learned" aria-label="LAYA learning" aria-live="polite">
    <strong>LAYA learned this</strong>
    <p title={label}>{latest.domain} · {latest.layer} · {label.length > 120 ? `${label.slice(0, 120)}…` : label}</p>
    <p className="nx-laya-note">{instant.episodes} example{instant.episodes === 1 ? "" : "s"} saved on this computer. Uncertain answers still go to your main model.</p>
  </section>;
}
