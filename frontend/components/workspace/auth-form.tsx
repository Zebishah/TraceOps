'use client';

import { useEffect, useRef, useState, type FormEvent, type MouseEvent } from 'react';
import { z } from 'zod';
import { ApiError, post } from '@/lib/product/client';
import { registrationResponseSchema, verificationTokenFromFragment } from '@/lib/product/auth-contracts';
import { AuthFrame } from './auth-frame';

// Volatile browser memory survives a same-route framework remount after cleaning
// the fragment. It is never stored in localStorage, sessionStorage, or history state.
let pendingVerificationToken: string | null = null;

type AuthProps = { register?: boolean; verification?: boolean };
export function AuthForm(props: AuthProps) {
  return <AuthExperience key={props.verification ? 'verification' : props.register ? 'register' : 'login'} {...props} />;
}
function AuthExperience({ register = false, verification = false }: AuthProps) {
  const [isRegister, setIsRegister] = useState(register);
  const [isVerification, setIsVerification] = useState(verification);
  const [token, setToken] = useState<string | null>(null);
  const [verified, setVerified] = useState(false);
  const [email, setEmail] = useState('');
  const [verificationEmail, setVerificationEmail] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    function syncRoute() {
      const verify = window.location.pathname === '/verify-email';
      setIsRegister(window.location.pathname === '/register'); setIsVerification(verify);
      if (!verify) { pendingVerificationToken = null; setToken(null); }
      setError(''); setNotice(''); setVerified(false); setVerificationEmail(''); setCooldown(0); formRef.current?.reset();
      const fragment = window.location.hash;
      if (verify && fragment) {
        const value = verificationTokenFromFragment(fragment);
        pendingVerificationToken = value; setToken(value);
        if (!value) setError('This verification link is incomplete. Request a new link below.');
        // Keep the token in memory; never put it in storage or send it as a URL query.
        window.history.replaceState(null, '', '/verify-email');
      } else if (verify && pendingVerificationToken) {
        setToken(pendingVerificationToken);
      }
    }
    syncRoute(); window.addEventListener('popstate', syncRoute);
    return () => window.removeEventListener('popstate', syncRoute);
  }, []);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown(value => Math.max(0, value - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  function openVerification(address: string, message: string) {
    formRef.current?.reset(); setEmail(address); setVerificationEmail(address); setIsRegister(false); setIsVerification(true);
    setError(''); setVerified(false); setCooldown(0);
    pendingVerificationToken = null; setToken(null); setNotice(message); window.history.pushState(null, '', '/verify-email');
    titleRef.current?.focus({ preventScroll: true });
  }
  function switchMode(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); if (pending) return;
    const next = !isRegister;
    window.history.pushState(null, '', next ? '/register' : '/login');
    formRef.current?.reset(); setError(''); setNotice(''); setIsRegister(next);
    titleRef.current?.focus({ preventScroll: true });
  }
  function reportFailure(cause: unknown) {
    setError(cause instanceof Error ? cause.message : 'Unable to connect. Please try again.');
    if (cause instanceof ApiError && cause.status === 429) setCooldown(cause.retryAfter ?? 60);
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (pending) return;
    setPending(true); setError('');
    const fields = new FormData(event.currentTarget);
    const address = String(fields.get('email') ?? '').trim();
    const password = String(fields.get('password') ?? '');
    try {
      if (isRegister) {
        const result = await post('auth/register', registrationResponseSchema, {
          email: address, password, full_name: fields.get('full_name'),
          organization_name: fields.get('organization_name'), organization_slug: fields.get('organization_slug'),
        });
        if (result.verification_required) {
          openVerification(address, result.verification_email_sent
            ? 'Your workspace has been created. Open the link in your email to finish signup. Check your spam folder if you don’t see it.'
            : 'Your workspace has been created, but we couldn’t send the verification email. Try sending it again below.');
          if (result.verification_email_sent) setCooldown(60);
          return;
        }
      }
      await post('auth/login', z.object({ authenticated: z.boolean() }), { email: address, password });
      // A full navigation rechecks the new HttpOnly session on the server.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign('/app');
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'email_verification_required') openVerification(address, 'Verify your email before entering the workspace. Request a link below, then return to sign in.');
      else reportFailure(cause);
    } finally { setPending(false); }
  }
  async function resend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (pending || cooldown > 0) return;
    setPending(true); setError(''); setNotice('');
    try {
      const result = await post('auth/verification/request', z.object({ message: z.string() }), { email: email.trim() });
      setNotice(result.message); setCooldown(60);
    } catch (cause) { reportFailure(cause); } finally { setPending(false); }
  }
  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (pending || !token) return;
    setPending(true); setError(''); setNotice('');
    try {
      await post('auth/verification/confirm', z.object({ verified: z.literal(true), message: z.string() }), { token });
      pendingVerificationToken = null; setToken(null); setVerified(true);
      titleRef.current?.focus({ preventScroll: true });
    } catch (cause) {
      reportFailure(cause);
      if (cause instanceof ApiError && cause.status === 400) { pendingVerificationToken = null; setToken(null); }
    } finally { setPending(false); }
  }

  return (
    <AuthFrame register={isRegister || isVerification}>
      <div className="auth-mode-marker"><span />{isVerification ? 'A VERIFIED IDENTITY. A CLEARER CONNECTION.' : isRegister ? 'A NEW CHAPTER FOR YOUR OPERATIONS' : 'YOUR WORKSPACE IS WAITING'}</div>
      {(isRegister || isVerification) && <ol className="auth-signup-steps" aria-label="Workspace signup progress"><li aria-current={isRegister ? 'step' : undefined}><span aria-hidden="true">{isVerification ? '✓' : '1'}</span>Workspace details</li><li aria-current={isVerification ? 'step' : undefined}><span aria-hidden="true">{verified ? '✓' : '2'}</span>Verify email</li></ol>}
      <h1 id="auth-title" ref={titleRef} tabIndex={-1}>{isVerification ? verified ? <>Email confirmed.<br /><em>Your workspace awaits.</em></> : token ? <>Verify your email.<br /><em>Finish your signup.</em></> : verificationEmail ? <>Check your inbox.<br /><em>Verify to continue.</em></> : <>Verify your email.<br /><em>Finish your signup.</em></> : isRegister ? <>Make room for<br /><em>clearer decisions.</em></> : <>Welcome back.<br /><em>Let’s bring clarity.</em></>}</h1>
      <p className="auth-introduction">{isVerification ? verified ? 'Your email address has been verified. Sign in to continue to OpsPilot or return to your AI application to connect.' : token ? 'Confirm your email to complete signup and access your workspace. This link can be used once.' : verificationEmail ? <>Complete signup by verifying <strong>{verificationEmail}</strong>. You’ll be able to sign in once your email is confirmed.</> : 'Use the email address you signed up with to get a new verification link and finish setting up your workspace.' : isRegister ? 'Set up your workspace, then verify your email to complete signup.' : 'Sign in to your OpsPilot workspace and pick up where you left off.'}</p>
      {isVerification ? (
        <div className="auth-verification">
          <div className={`auth-mail-emblem${verified ? ' is-verified' : ''}`} aria-hidden="true">{verified ? '✓' : token ? '◇' : '✉'}</div>
          {notice && <p className="auth-notice" role="status">{notice}</p>}
          {error && <p ref={errorRef} tabIndex={-1} className="form-error" role="alert">{error}</p>}
          {verified ? <a className="auth-submit" href="/login"><span>Continue to sign in</span><span className="auth-submit-arrow" aria-hidden="true">↗</span></a> : <>
            {token && <form onSubmit={confirm} aria-busy={pending} className="auth-fields"><button className="auth-submit" disabled={pending || cooldown > 0} type="submit"><span>{pending ? 'Confirming…' : cooldown > 0 ? `Try again in ${cooldown}s` : 'Verify my email'}</span><span className="auth-submit-arrow" aria-hidden="true">✓</span></button></form>}
            {token ? <details className="auth-resend-details"><summary>Need a new verification link?</summary><ResendForm email={email} setEmail={setEmail} pending={pending} cooldown={cooldown} submit={resend} /></details> : <ResendForm email={email} setEmail={setEmail} recipient={verificationEmail} pending={pending} cooldown={cooldown} submit={resend} />}
            <div className="auth-mode-switch">Already verified? <a href="/login">Return to sign in ↗</a></div>
          </>}
        </div>
      ) : <>
        <form ref={formRef} onSubmit={submit} aria-busy={pending} className="auth-fields">
          {isRegister && <><div className="auth-field-pair"><label>Full name<input name="full_name" required maxLength={200} autoComplete="name" placeholder="Your full name" disabled={pending} /></label><label>Organization name<input name="organization_name" required maxLength={200} autoComplete="organization" placeholder="Your organization" disabled={pending} /></label></div><label>Workspace slug<input name="organization_slug" required maxLength={100} pattern="[a-z0-9]+(-[a-z0-9]+)*" placeholder="your-team" autoCapitalize="none" spellCheck={false} disabled={pending} aria-describedby="auth-slug-help" /><small id="auth-slug-help">Lowercase letters, numbers, and single hyphens.</small></label></>}
          <label>Email address<input name="email" type="email" required maxLength={320} autoComplete="username" autoCapitalize="none" spellCheck={false} placeholder="you@company.com" disabled={pending} /></label>
          <label>Password<input name="password" type="password" required minLength={isRegister ? 8 : 1} maxLength={128} autoComplete={isRegister ? 'new-password' : 'current-password'} placeholder={isRegister ? 'At least 8 characters' : 'Enter your password'} disabled={pending} /></label>
          {isRegister && <p className="auth-field-note">We’ll email you a verification link before you can enter your workspace.</p>}
          {error && <p ref={errorRef} tabIndex={-1} className="form-error" role="alert">{error}</p>}
          <button className="auth-submit" disabled={pending || cooldown > 0} type="submit"><span>{pending ? isRegister ? 'Creating workspace…' : 'Signing in…' : cooldown > 0 ? `Try again in ${cooldown}s` : isRegister ? 'Create your workspace' : 'Enter your workspace'}</span><span className="auth-submit-arrow" aria-hidden="true">↗</span></button>
        </form>
        <div className="auth-mode-switch">{isRegister ? 'Already part of the workspace?' : 'New to OpsPilot?'} <a href={isRegister ? '/login' : '/register'} onClick={switchMode} aria-disabled={pending}>{isRegister ? 'Sign in' : 'Create a workspace'} <span aria-hidden="true">↗</span></a></div>
      </>}
      <div className="auth-trust-note"><span aria-hidden="true">◇</span><p>{isVerification ? <>Confirm your email. Keep control.<br />Verification links expire and never sign you in automatically.</> : <>Your workspace, your team.<br />Access is checked against your organization and role.</>}</p></div>
    </AuthFrame>
  );
}

function ResendForm({ email, setEmail, recipient, pending, cooldown, submit }: { email: string; setEmail: (value: string) => void; recipient?: string; pending: boolean; cooldown: number; submit: (event: FormEvent<HTMLFormElement>) => Promise<void> }) {
  return <form onSubmit={submit} aria-busy={pending} className="auth-fields auth-resend-form">{!recipient && <label>Registered email address<input name="email" type="email" required maxLength={320} autoComplete="email" autoCapitalize="none" spellCheck={false} placeholder="you@company.com" value={email} onChange={event => setEmail(event.target.value)} disabled={pending} /></label>}<button className="auth-submit" type="submit" disabled={pending || cooldown > 0}><span>{pending ? 'Requesting…' : cooldown > 0 ? `Request again in ${cooldown}s` : recipient ? 'Resend verification email' : 'Send verification link'}</span><span className="auth-submit-arrow" aria-hidden="true">↗</span></button></form>;
}
