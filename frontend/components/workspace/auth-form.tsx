'use client';

import { useEffect, useRef, useState, type FormEvent, type MouseEvent } from 'react';
import { z } from 'zod';
import { post } from '@/lib/product/client';
import './auth-scene.css';

export function AuthForm({ register = false }: { register?: boolean }) {
  const [isRegister, setIsRegister] = useState(register);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => { setIsRegister(register); }, [register]);
  useEffect(() => {
    const syncRoute = () => {
      setIsRegister(window.location.pathname === '/register');
      setError('');
      formRef.current?.reset();
    };
    window.addEventListener('popstate', syncRoute);
    return () => window.removeEventListener('popstate', syncRoute);
  }, []);

  function switchMode(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (pending) return;
    const next = !isRegister;
    window.history.pushState(null, '', next ? '/register' : '/login');
    formRef.current?.reset();
    setError('');
    setIsRegister(next);
    titleRef.current?.focus({ preventScroll: true });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError('');
    const fields = new FormData(event.currentTarget);
    const email = String(fields.get('email') ?? '');
    const password = String(fields.get('password') ?? '');
    try {
      if (isRegister) {
        await post('auth/register', z.object({ id: z.string() }), {
          email, password, full_name: fields.get('full_name'),
          organization_name: fields.get('organization_name'),
          organization_slug: fields.get('organization_slug'),
        });
      }
      await post('auth/login', z.object({ authenticated: z.boolean() }), { email, password });
      window.location.assign('/app');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to connect. Please try again.');
    } finally {
      setPending(false);
    }
  }

  return (
    <main className={`auth-screen auth-experience${isRegister ? ' is-register' : ''}`}>
      <div className="auth-stage">
        <aside className="auth-visual" aria-label="OpsPilot incident intelligence">
          <div className="auth-visual-top"><a href="/" className="auth-scene-brand"><span>◈</span> opspilot</a><span className="auth-edition">OPERATIONS, IN FOCUS.</span></div>
          <div className="auth-visual-copy"><span className="auth-overline">CONTEXT. CLARITY. CONTROL.</span><h2>Every signal.<br />A clearer <em>next step.</em></h2><p>Bring the evidence together.<br />Keep the decision in human hands.</p></div>
          <div className="auth-illustration" aria-hidden="true">
            <div className="auth-orbit auth-orbit-one" /><div className="auth-orbit auth-orbit-two" />
            <div className="auth-mini-card auth-mini-policy"><span>01 / KNOWLEDGE</span><strong>Evidence,<br />within reach.</strong><i>POLICY · SOURCE ATTACHED ↗</i></div>
            <div className="auth-case-card"><div className="auth-case-top"><span>◈ OPSPILOT</span><span>ILLUSTRATIVE CASE</span></div><span className="auth-case-label">INCIDENT INTELLIGENCE</span><strong>From scattered signals<br />to a considered decision.</strong><div className="auth-case-row"><span>▤</span><div>Gather the evidence<small>Knowledge + operational records</small></div><b>01</b></div><div className="auth-case-row"><span>◎</span><div>Understand the context<small>Findings connected to their sources</small></div><b>02</b></div><div className="auth-review-bar"><span>◈</span> Human review, built in <span>↗</span></div></div>
            <div className="auth-mini-card auth-mini-control"><span className="auth-control-icon">✓</span><div><strong>You stay in control.</strong><small>Review before taking action.</small></div></div>
          </div>
          <div className="auth-visual-bottom"><span>BUILT FOR ACCOUNTABLE OPERATIONS</span><span>01 — 03</span></div>
        </aside>
        <section className="auth-form-panel" aria-labelledby="auth-title">
          <div className="auth-form-header"><a className="auth-mobile-brand" href="/">◈ opspilot</a><a href="/" className="auth-product-link">Back to product <span>↗</span></a></div>
          <div className="auth-form-content">
            <div className="auth-mode-marker"><span />{isRegister ? 'A NEW CHAPTER FOR YOUR OPERATIONS' : 'YOUR WORKSPACE IS WAITING'}</div>
            <h1 id="auth-title" ref={titleRef} tabIndex={-1}>{isRegister ? <>Make room for<br /><em>clearer decisions.</em></> : <>Welcome back.<br /><em>Let’s bring clarity.</em></>}</h1>
            <p className="auth-introduction">{isRegister ? 'Create your account and bring your team’s incidents and knowledge into one workspace.' : 'Sign in to your OpsPilot workspace and pick up where you left off.'}</p>
            <form ref={formRef} onSubmit={submit} aria-busy={pending} className="auth-fields">
              {isRegister && <><div className="auth-field-pair"><label>Full name<input name="full_name" required maxLength={200} autoComplete="name" placeholder="Your full name" disabled={pending} /></label><label>Organization name<input name="organization_name" required maxLength={200} autoComplete="organization" placeholder="Your organization" disabled={pending} /></label></div><label>Workspace slug<input name="organization_slug" required maxLength={100} pattern="[a-z0-9]+(-[a-z0-9]+)*" placeholder="your-team" autoCapitalize="none" spellCheck={false} disabled={pending} aria-describedby="auth-slug-help" /><small id="auth-slug-help">Lowercase letters, numbers, and single hyphens.</small></label></>}
              <label>Email address<input name="email" type="email" required maxLength={320} autoComplete="email" placeholder="you@company.com" disabled={pending} /></label>
              <label>Password<input name="password" type="password" required minLength={isRegister ? 8 : 1} maxLength={128} autoComplete={isRegister ? 'new-password' : 'current-password'} placeholder={isRegister ? 'At least 8 characters' : 'Enter your password'} disabled={pending} /></label>
              {error && <p className="form-error" role="alert">{error}</p>}
              <button className="auth-submit" disabled={pending} type="submit"><span>{pending ? 'Connecting…' : isRegister ? 'Create your workspace' : 'Enter your workspace'}</span><span className="auth-submit-arrow" aria-hidden="true">↗</span></button>
            </form>
            <div className="auth-mode-switch">{isRegister ? 'Already part of the workspace?' : 'New to OpsPilot?'} <a href={isRegister ? '/login' : '/register'} onClick={switchMode} aria-disabled={pending}>{isRegister ? 'Sign in' : 'Create a workspace'} <span aria-hidden="true">↗</span></a></div>
            <div className="auth-trust-note"><span aria-hidden="true">◇</span><p>Your workspace, your team.<br />Access is checked against your organization and role.</p></div>
          </div>
          <div className="auth-form-footer"><span>OPSPILOT / INCIDENT INTELLIGENCE</span><span>Evidence before action.</span></div>
        </section>
      </div>
    </main>
  );
}
