import { TraceOpsActionSpinner } from '@/components/workspace/trace-ops-loader';
'use client';

import { useEffect, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { z } from 'zod';
import { post } from '@/lib/product/client';
import { AuthFrame } from '@/components/workspace/auth-frame';

const resultSchema = z.object({ message: z.string() });

export default function ResetPasswordPage() {
  const [token, setToken] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    setToken(new URLSearchParams(window.location.hash.slice(1)).get('token') ?? '');
    window.history.replaceState(null, '', '/reset-password');
  }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password !== confirm) { setError('Passwords do not match.'); return; }
    setLoading(true); setError('');
    try {
      await post('auth/password-reset/confirm', resultSchema, { token, password });
      setComplete(true); setToken(''); setPassword(''); setConfirm('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to reset password.');
    } finally { setLoading(false); }
  }
  return <AuthFrame><section className="auth-verification">
    <h1 id="auth-title">{complete ? 'Password updated.' : 'Choose a new password.'}</h1>
    {complete ? <><p>Previous web access tokens have been revoked. Sign in again.</p><Link href="/login" className="auth-submit">Continue to sign in</Link></> : <>
      <p>Use a new password with at least eight characters. This link expires after 30 minutes.</p>
      {error && <p role="alert" className="form-error">{error}</p>}
      {!/^[A-Za-z0-9_-]{43}$/.test(token) ? <p role="status">This link is invalid or missing. Request another one.</p> : <form onSubmit={(e) => void submit(e)} className="auth-fields">
        <label>New password<input required type="password" minLength={8} maxLength={128} autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
        <label>Confirm new password<input required type="password" minLength={8} maxLength={128} autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} /></label>
        <button className="auth-submit" disabled={loading} type="submit">{loading ? <><TraceOpsActionSpinner label="Saving new password" /> Saving…</> : 'Update password'}</button>
      </form>}
      <Link href="/forgot-password" className="auth-verification-back">Request another reset link</Link>
    </>}
  </section></AuthFrame>;
}
