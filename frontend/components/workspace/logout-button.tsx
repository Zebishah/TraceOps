'use client';

import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, LogOut } from 'lucide-react';
import { z } from 'zod';
import { dashboardCache } from '@/lib/product/dashboard-cache';
import { clearVerification } from '@/lib/product/verification-flow';

const signedOutSchema = z.object({ signed_out: z.literal(true) });

export function LogoutButton() {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const errorMessage = useRef<HTMLParagraphElement>(null);
  const request = useRef<AbortController | null>(null);
  const locked = useRef(false);
  const [phase, setPhase] = useState<'idle' | 'signing-out' | 'redirecting'>('idle');
  const [error, setError] = useState('');
  const busy = phase !== 'idle';

  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => { if (error) errorMessage.current?.focus(); }, [error]);

  function open() {
    if (locked.current) return;
    setError(''); dialog.current?.showModal(); cancelButton.current?.focus();
  }
  function cancel() {
    if (!locked.current) dialog.current?.close();
  }
  async function signOut() {
    if (locked.current) return;
    locked.current = true; setPhase('signing-out'); setError('');
    const controller = new AbortController(); request.current = controller;
    try {
      const response = await fetch('/api/session', {
        method: 'DELETE', credentials: 'same-origin', cache: 'no-store',
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]),
      });
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok || !signedOutSchema.safeParse(body).success) {
        throw new Error('We couldn’t confirm sign-out. Please try again.');
      }
      if (controller.signal.aborted) return;
      // Clear private snapshots only after the server confirms the session cookie is expired.
      // Notify other tabs without starting new reads in the page being signed out.
      dashboardCache.invalidate('*', true, false);
      clearVerification();
      try { window.localStorage.removeItem('opspilot.organization'); } catch { /* Storage may be disabled. */ }
      setPhase('redirecting');
      // A full navigation drops in-memory credentials and replaces the current workspace entry.
      window.location.replace('/login');
    } catch (cause) {
      if (controller.signal.aborted) return;
      locked.current = false; setPhase('idle');
      setError(cause instanceof Error && cause.name === 'TimeoutError'
        ? 'Signing out took too long. Please try again.'
        : cause instanceof Error && cause.message === 'We couldn’t confirm sign-out. Please try again.'
          ? cause.message : 'We couldn’t connect to sign you out. Please try again.');
    }
  }

  return <>
    <button type="button" aria-label="Sign out" aria-haspopup="dialog" disabled={busy} onClick={open}>
      {busy ? <LoaderCircle size={16} className="is-spinning" /> : <LogOut size={16} />}
    </button>
    <dialog ref={dialog} className="workspace-dialog logout-dialog" role="alertdialog" aria-labelledby="logout-title" aria-describedby="logout-description" aria-busy={busy}
      onCancel={event => { if (locked.current) event.preventDefault(); }} onClose={() => { if (!locked.current) setError(''); }}>
      <div className="logout-dialog-content">
        <span className="logout-dialog-icon" aria-hidden="true"><LogOut size={24} strokeWidth={1.6} /></span>
        <span className="app-eyebrow">YOUR WORKSPACE SESSION</span>
        <h2 id="logout-title">{phase === 'redirecting' ? 'You’re signed out.' : 'Sign out of IncidentIQ?'}</h2>
        <p id="logout-description">{phase === 'redirecting' ? 'Taking you to the sign-in page…' : busy ? 'Closing your session. Please wait a moment.' : 'You’ll need to sign in again to return to your workspace.'}</p>
        {error && <p ref={errorMessage} tabIndex={-1} className="form-error" role="alert">{error}</p>}
        <div className="logout-dialog-actions">
          <button ref={cancelButton} type="button" className="btn secondary" disabled={busy} onClick={cancel}>Cancel</button>
          <button type="button" className="btn primary-action" disabled={busy} onClick={() => void signOut()}>
            {busy ? <LoaderCircle size={15} className="is-spinning" aria-hidden="true" /> : <LogOut size={15} aria-hidden="true" />}
            <span aria-live="polite">{phase === 'redirecting' ? 'Opening sign in…' : busy ? 'Signing out…' : 'Sign out'}</span>
          </button>
        </div>
      </div>
    </dialog>
  </>;
}
