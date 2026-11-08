'use client';

import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { z } from 'zod';
import { post } from '@/lib/product/client';
import { AuthFrame } from '@/components/workspace/auth-frame';

const resultSchema = z.object({ message: z.string() });

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');
  const [cooldown, setCooldown] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading || cooldown) return;
    setLoading(true); setError('');
    try {
      await post('auth/password-reset/request', resultSchema, { email: email.trim() });
      setSent(true); setCooldown(true);
      window.setTimeout(() => setCooldown(false), 60_000);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to request a reset link.');
    } finally { setLoading(false); }
  }
  return <AuthFrame><section className="auth-verification">
    <h1>{sent ? 'Check your inbox.' : 'Reset your password.'}</h1>
    <p>{sent ? 'If your account is eligible, a one-time reset link will arrive. Check spam too. It expires in 30 minutes.' : 'Enter the email you use for your TraceOps workspace.'}</p>
    {error && <p role="alert" className="form-error">{error}</p>}
    <form onSubmit={(event) => void submit(event)} className="auth-fields">
      <label>Email address<input type="email" required maxLength={320} autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} /></label>
      <button className="auth-submit" type="submit" disabled={loading || cooldown}>{loading ? 'Sending…' : cooldown ? 'Try again in one minute' : sent ? 'Resend reset link' : 'Send reset link'}</button>
    </form>
    <Link href="/login" className="auth-verification-back">Return to sign in</Link>
  </section></AuthFrame>;
}
