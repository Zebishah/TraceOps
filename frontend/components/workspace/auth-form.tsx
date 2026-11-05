'use client';

import { useEffect, useRef, useState, type FormEvent, type MouseEvent } from 'react';
import { ArrowLeft, CircleCheck, Mail, MailCheck } from 'lucide-react';
import { z } from 'zod';
import { ApiError, post } from '@/lib/product/client';
import { registrationResponseSchema, verificationTokenFromFragment } from '@/lib/product/auth-contracts';
import { clearVerification, readVerification, rememberVerification } from '@/lib/product/verification-flow';
import { AuthFrame } from './auth-frame';

// Existing email links remain usable during the transition to codes.
let pendingVerificationToken: string | null = null;
const messageSchema = z.object({ message: z.string() });
const codeResponseSchema = z.object({ verified: z.literal(true), authenticated: z.literal(true) });
async function requestCode(email: string) {
  return post('auth/verification/request', messageSchema, { email });
}

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
  const [code, setCode] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [claimCooldown, setClaimCooldown] = useState(0);
  const autoRequested = useRef(new Set<string>());
  const formRef = useRef<HTMLFormElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    function syncRoute() {
      const verify = window.location.pathname === '/verify-email';
      setIsRegister(window.location.pathname === '/register'); setIsVerification(verify);
      setError(''); setNotice(''); setCode(''); setVerified(false);
      setVerificationEmail(''); setCooldown(0); setToken(null); formRef.current?.reset();
      if (!verify) { pendingVerificationToken = null; return; }
      const fragment = window.location.hash;
      if (fragment) {
        const value = verificationTokenFromFragment(fragment);
        pendingVerificationToken = value; setToken(value);
        if (!value) setError('This verification link is incomplete. Sign in to receive a new code.');
        window.history.replaceState(null, '', '/verify-email');
      } else if (pendingVerificationToken) setToken(pendingVerificationToken);
      else {
        const saved = readVerification();
        if (!saved) return;
        setEmail(saved.email); setVerificationEmail(saved.email);
        setCooldown(Math.max(0, Math.ceil((saved.resendAt - Date.now()) / 1000)));
        // Protected-session recovery knows the account but has not sent a code yet.
        if (saved.resendAt === 0 && !autoRequested.current.has(saved.email)) {
          autoRequested.current.add(saved.email); setPending(true);
          rememberVerification(saved.email, Date.now() + 60000);
          void requestCode(saved.email).then(result => {
            setNotice(result.message); setCooldown(60);
            rememberVerification(saved.email, Date.now() + 60000);
          }).catch((cause: unknown) => {
            setError(cause instanceof Error ? cause.message : 'Unable to send a code. Try again.');
            const delay = cause instanceof ApiError && cause.status === 429 ? cause.retryAfter ?? 60 : 0;
            setCooldown(delay); rememberVerification(saved.email, Date.now() + delay * 1000);
          }).finally(() => setPending(false));
        }
      }
    }
    syncRoute(); window.addEventListener('popstate', syncRoute);
    return () => window.removeEventListener('popstate', syncRoute);
  }, []);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);
  useEffect(() => {
    if (cooldown <= 0 && claimCooldown <= 0) return;
    const timer = window.setTimeout(() => {
      setCooldown(value => Math.max(0, value - 1));
      setClaimCooldown(value => Math.max(0, value - 1));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown, claimCooldown]);

  function openVerification(address: string, sent: boolean) {
    formRef.current?.reset(); setEmail(address); setVerificationEmail(address);
    setIsRegister(false); setIsVerification(true); setCode('');
    setError(''); setVerified(false); setCooldown(sent ? 60 : 0);
    pendingVerificationToken = null; setToken(null);
    setNotice(sent ? 'We sent a six-digit code to your email. Enter it below to continue.' : 'We couldn’t send your verification code. Use Resend code to try again.');
    rememberVerification(address, Date.now() + (sent ? 60000 : 0));
    window.history.pushState(null, '', '/verify-email');
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
  function reportFailure(cause: unknown, claim = false) {
    setError(cause instanceof Error ? cause.message : 'Unable to connect. Please try again.');
    if (cause instanceof ApiError && cause.status === 429) {
      if (claim) setClaimCooldown(cause.retryAfter ?? 60);
      else setCooldown(cause.retryAfter ?? 60);
    }
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
        if (result.verification_required) { openVerification(address, result.verification_email_sent); return; }
      }
      await post('auth/login', z.object({ authenticated: z.boolean() }), { email: address, password });
      clearVerification();
      // A full navigation rechecks the HttpOnly session on the server.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign('/app');
    } catch (cause) {
      if (cause instanceof ApiError && cause.verification) {
        openVerification(cause.verification.email, cause.verification.verification_email_sent === true);
        // Older backends did not send a code during sign-in; request it automatically.
        if (cause.verification.verification_email_sent === undefined) await sendCode(cause.verification.email);
      } else reportFailure(cause);
    } finally { setPending(false); }
  }
  async function sendCode(address: string) {
    setPending(true); setError('');
    try {
      const result = await requestCode(address);
      setEmail(address); setVerificationEmail(address); setNotice(result.message); setCode('');
      setCooldown(60); rememberVerification(address, Date.now() + 60000);
    } catch (cause) { reportFailure(cause); } finally { setPending(false); }
  }
  async function resend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (pending || cooldown > 0) return;
    await sendCode((verificationEmail || email).trim());
  }
  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (pending || claimCooldown > 0 || (!token && code.length !== 6)) return;
    setPending(true); setError('');
    try {
      if (token) {
        await post('auth/verification/confirm', z.object({ verified: z.literal(true), message: z.string() }), { token });
        pendingVerificationToken = null; setToken(null); clearVerification();
        // Legacy link confirmation does not create a session.
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination
        window.location.assign('/login');
      } else {
        await post('auth/verification/code', codeResponseSchema, { email: verificationEmail, code });
        clearVerification(); setVerified(true);
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination
        window.location.assign('/app');
      }
    } catch (cause) {
      reportFailure(cause, true);
      if (token && cause instanceof ApiError && cause.status === 400) {
        pendingVerificationToken = null; setToken(null);
      }
    } finally { setPending(false); }
  }

  return (
    <AuthFrame register={isRegister || isVerification}>
      <div className="auth-mode-marker"><span />{isVerification ? 'ONE LAST STEP TO YOUR WORKSPACE' : isRegister ? 'A NEW CHAPTER FOR YOUR OPERATIONS' : 'YOUR WORKSPACE IS WAITING'}</div>
      {(isRegister || isVerification) && <ol className="auth-signup-steps" aria-label="Workspace signup progress"><li aria-current={isRegister ? 'step' : undefined}><span aria-hidden="true">{isVerification ? '✓' : '1'}</span>Workspace details</li><li aria-current={isVerification ? 'step' : undefined}><span aria-hidden="true">{verified ? '✓' : '2'}</span>Verify email</li></ol>}
      <h1 id="auth-title" ref={titleRef} tabIndex={-1}>{isVerification ? verified ? <>Email confirmed.<br /><em>Opening your workspace.</em></> : verificationEmail ? <>Check your inbox.<br /><em>Enter your code.</em></> : <>Verify your email.<br /><em>Finish your signup.</em></> : isRegister ? <>Make room for<br /><em>clearer decisions.</em></> : <>Welcome back.<br /><em>Let’s bring clarity.</em></>}</h1>
      <p className="auth-introduction">{isVerification ? verified ? 'Taking you into your workspace…' : token ? 'Confirm your email to finish setting up your workspace.' : verificationEmail ? 'Enter the six-digit code from your email to verify your address and continue.' : 'Enter the email you signed up with. We’ll send your verification code automatically.' : isRegister ? 'Set up your workspace, then verify your email to complete signup.' : 'Sign in to your OpsPilot workspace and pick up where you left off.'}</p>
      {isVerification ? (
        <div className="auth-verification">
          <section className="auth-verification-card" aria-labelledby="auth-verification-heading">
            <div className="auth-verification-card-header">
              <span className={`auth-mail-emblem${verified ? ' is-verified' : ''}`} aria-hidden="true">{verified ? <CircleCheck /> : token ? <MailCheck /> : <Mail />}</span>
              <div className="auth-verification-card-title">
                <h2 id="auth-verification-heading">{verified ? 'You’re all set' : token ? 'Ready to confirm' : verificationEmail ? 'Verification for' : 'Email confirmation'}</h2>
                <p>{verified ? 'Email address verified' : token ? 'Your workspace is one step away' : verificationEmail || 'Use your workspace email address'}</p>
              </div>
            </div>
            {notice && <p className="auth-notice" role="status">{notice}</p>}
            {error && <p id="auth-verification-error" ref={errorRef} tabIndex={-1} className="form-error" role="alert">{error}</p>}
            {verified ? <p className="auth-notice" role="status">Opening your workspace…</p> : token ? <form onSubmit={confirm} aria-busy={pending} className="auth-fields"><button className="auth-submit" disabled={pending || claimCooldown > 0} type="submit"><span>{pending ? 'Confirming…' : claimCooldown > 0 ? `Try again in ${claimCooldown}s` : 'Verify my email'}</span><span className="auth-submit-arrow" aria-hidden="true">✓</span></button></form> : verificationEmail ? <>
              <form onSubmit={confirm} aria-busy={pending} className="auth-code-form">
                <label htmlFor="verification-code">Verification code</label>
                <div className="auth-code-input">
                  <div className="auth-code-group" aria-hidden="true">{Array.from({ length: 6 }, (_, index) => <span key={index} data-slot="input-otp-slot" data-active={index === Math.min(code.length, 5)}>{code[index]}</span>)}</div>
                  <input id="verification-code" name="code" type="text" maxLength={6} pattern="[0-9]{6}" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={event => { setCode(event.target.value.replace(/[^0-9]/g, '').slice(0, 6)); setError(''); }} disabled={pending} aria-invalid={Boolean(error)} aria-describedby={error ? 'auth-verification-error auth-code-help' : 'auth-code-help'} />
                </div>
                <p id="auth-code-help">Codes expire in 10 minutes. You can paste the full code.</p>
                <button className="auth-submit" disabled={pending || code.length !== 6 || claimCooldown > 0} type="submit"><span>{pending ? 'Verifying…' : claimCooldown > 0 ? `Try again in ${claimCooldown}s` : 'Verify & enter workspace'}</span><span className="auth-submit-arrow" aria-hidden="true">↗</span></button>
              </form>
              <form onSubmit={resend} className="auth-code-resend"><span>Didn’t receive a code?</span><button type="submit" disabled={pending || cooldown > 0}>{cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend code'}</button></form>
            </> : <form onSubmit={resend} aria-busy={pending} className="auth-fields"><label>Registered email address<input name="email" type="email" required maxLength={320} autoComplete="email" autoCapitalize="none" spellCheck={false} placeholder="you@company.com" value={email} onChange={event => setEmail(event.target.value)} disabled={pending} /></label><button className="auth-submit" type="submit" disabled={pending || cooldown > 0}><span>{pending ? 'Sending code…' : cooldown > 0 ? `Try again in ${cooldown}s` : 'Continue'}</span><span className="auth-submit-arrow" aria-hidden="true">↗</span></button></form>}
          </section>
          {!verified && <a className="auth-verification-back" href="/login"><ArrowLeft aria-hidden="true" />Return to sign in</a>}
        </div>
      ) : <>
        <form ref={formRef} onSubmit={submit} aria-busy={pending} className="auth-fields">
          {isRegister && <><div className="auth-field-pair"><label>Full name<input name="full_name" required maxLength={200} autoComplete="name" placeholder="Your full name" disabled={pending} /></label><label>Organization name<input name="organization_name" required maxLength={200} autoComplete="organization" placeholder="Your organization" disabled={pending} /></label></div><label>Workspace slug<input name="organization_slug" required maxLength={100} pattern="[a-z0-9]+(-[a-z0-9]+)*" placeholder="your-team" autoCapitalize="none" spellCheck={false} disabled={pending} aria-describedby="auth-slug-help" /><small id="auth-slug-help">Lowercase letters, numbers, and single hyphens.</small></label></>}
          <label>Email address<input name="email" type="email" required maxLength={320} autoComplete="username" autoCapitalize="none" spellCheck={false} placeholder="you@company.com" disabled={pending} /></label>
          <label>Password<input name="password" type="password" required minLength={isRegister ? 8 : 1} maxLength={128} autoComplete={isRegister ? 'new-password' : 'current-password'} placeholder={isRegister ? 'At least 8 characters' : 'Enter your password'} disabled={pending} /></label>
          {isRegister && <p className="auth-field-note">We’ll email you a six-digit verification code before you can enter your workspace.</p>}
          {error && <p ref={errorRef} tabIndex={-1} className="form-error" role="alert">{error}</p>}
          <button className="auth-submit" disabled={pending || cooldown > 0} type="submit"><span>{pending ? isRegister ? 'Creating workspace…' : 'Signing in…' : cooldown > 0 ? `Try again in ${cooldown}s` : isRegister ? 'Create your workspace' : 'Enter your workspace'}</span><span className="auth-submit-arrow" aria-hidden="true">↗</span></button>
        </form>
        <div className="auth-mode-switch">{isRegister ? 'Already part of the workspace?' : 'New to OpsPilot?'} <a href={isRegister ? '/login' : '/register'} onClick={switchMode} aria-disabled={pending}>{isRegister ? 'Sign in' : 'Create a workspace'} <span aria-hidden="true">↗</span></a></div>
      </>}
      <div className="auth-trust-note"><span aria-hidden="true">◇</span><p>{isVerification ? <>Your code is private.<br />Only enter it here. Never share it with anyone.</> : <>Your workspace, your team.<br />Access is checked against your organization and role.</>}</p></div>
    </AuthFrame>
  );
}
