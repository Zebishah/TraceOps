import './trace-ops-loader.css';
export function TraceOpsActionSpinner({ label = 'Processing' }: { label?: string }) {
  return <span aria-label={label} role="status" className="trace-action-spinner">
    <span className="trace-action-spinner__ring" aria-hidden="true" />
    <span className="trace-action-spinner__mark" aria-hidden="true">◈</span>
  </span>;
}

export function TraceOpsPageLoader({ label = 'Preparing your workspace' }: { label?: string }) {
  return <main className="trace-loading-page" role="status" aria-live="polite">
    <div className="trace-loading-page__symbol" aria-hidden="true">◈</div>
    <strong>TraceOps</strong>
    <p>{label}</p>
  </main>;
}
