import type { ReactNode } from 'react';
import Link from 'next/link';
import './auth-scene.css';

export function AuthFrame({ register = false, children }: { register?: boolean; children: ReactNode }) {
  return (
    <main className={`auth-screen auth-experience${register ? ' is-register' : ''}`}>
      <div className="auth-stage">
        <aside className="auth-visual" aria-label="TraceOps incident intelligence">
          <div className="auth-visual-top"><Link href="/" className="auth-scene-brand"><span>◈</span> TraceOps</Link><span className="auth-edition">OPERATIONS, IN FOCUS.</span></div>
          <div className="auth-visual-copy"><span className="auth-overline">CONTEXT. CLARITY. CONTROL.</span><h2>Every signal.<br />A clearer <em>next step.</em></h2><p>Bring the evidence together.<br />Keep the decision in human hands.</p></div>
          <div className="auth-illustration" aria-hidden="true">
            <div className="auth-orbit auth-orbit-one" /><div className="auth-orbit auth-orbit-two" />
            <div className="auth-mini-card auth-mini-policy"><span>01 / KNOWLEDGE</span><strong>Evidence,<br />within reach.</strong><i>POLICY · SOURCE ATTACHED ↗</i></div>
            <div className="auth-case-card"><div className="auth-case-top"><span>◈ TRACEOPS</span><span>ILLUSTRATIVE CASE</span></div><span className="auth-case-label">INCIDENT INTELLIGENCE</span><strong>From scattered signals<br />to a considered decision.</strong><div className="auth-case-row"><span>▤</span><div>Gather the evidence<small>Knowledge + operational records</small></div><b>01</b></div><div className="auth-case-row"><span>◎</span><div>Understand the context<small>Findings connected to their sources</small></div><b>02</b></div><div className="auth-review-bar"><span>◈</span> Human review, built in <span>↗</span></div></div>
            <div className="auth-mini-card auth-mini-control"><span className="auth-control-icon">✓</span><div><strong>You stay in control.</strong><small>Review before taking action.</small></div></div>
          </div>
          <div className="auth-visual-bottom"><span>BUILT FOR ACCOUNTABLE OPERATIONS</span><span>01 — 03</span></div>
        </aside>
        <section className="auth-form-panel" aria-labelledby="auth-title">
          <div className="auth-form-header"><Link className="auth-mobile-brand" href="/">◈ TraceOps</Link><Link href="/" className="auth-product-link">Back to product <span>↗</span></Link></div>
          <div className="auth-form-content">{children}</div>
          <div className="auth-form-footer"><span>TRACEOPS / INCIDENT INTELLIGENCE</span><span>Evidence before action.</span></div>
        </section>
      </div>
    </main>
  );
}
