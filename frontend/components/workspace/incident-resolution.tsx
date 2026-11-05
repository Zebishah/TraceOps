'use client';

import {useState, type FormEvent} from 'react';
import {resolutionOutcomes, resolutionRequestSchema, type ResolutionRequest} from '@/lib/product/incident-resolution';
import {Panel} from './ui';

export function IncidentResolutionForm({findings, pending, onCancel, onResolve}: {
  findings?: string | null;
  pending: boolean;
  onCancel: () => void;
  onResolve: (request: ResolutionRequest) => Promise<void>;
}) {
  const [outcome, setOutcome] = useState('');
  const [reason, setReason] = useState('');
  const [message, setMessage] = useState('');
  const [nextSteps, setNextSteps] = useState('');
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = resolutionRequestSchema.safeParse({outcome, reason, customer_message: message, next_steps: nextSteps});
    if (!parsed.success) { setError(parsed.error.issues[0]?.message ?? 'Complete the resolution details.'); return; }
    setError('');
    await onResolve(parsed.data);
  }

  return <Panel title="Resolve incident">
    <p>Record what the investigation established, why the incident can close, and what the customer should know.</p>
    <form className="stack-form" onSubmit={submit}>
      <label>Resolution outcome<select value={outcome} required disabled={pending} onChange={event => setOutcome(event.target.value)}>
        <option value="">Choose an outcome</option>
        {resolutionOutcomes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <label>Findings and resolution summary<textarea value={reason} required minLength={10} maxLength={1000} rows={5} disabled={pending} onChange={event => setReason(event.target.value)} placeholder="Explain what you checked, what the evidence shows, and why no further operational action is required."/></label>
      {findings && <details><summary>Review saved investigation findings</summary><p style={{whiteSpace: 'pre-wrap'}}>{findings}</p></details>}
      <label>Customer message<textarea value={message} required minLength={10} maxLength={1000} rows={4} disabled={pending} onChange={event => {setMessage(event.target.value); setCopied(false);}} placeholder="Explain the verified outcome in plain language. Include only information appropriate for the customer."/></label>
      <p className="context-note">This wording is saved as a draft. Saving the resolution does not confirm that a customer message was delivered.</p>
      <label>Follow-up and next steps<textarea value={nextSteps} required minLength={10} maxLength={500} rows={3} disabled={pending} onChange={event => setNextSteps(event.target.value)} placeholder="Describe any next step, when the customer should contact support again, or why no follow-up is needed."/></label>
      {message.trim() && <details open><summary>Customer message preview</summary><p style={{whiteSpace: 'pre-wrap'}}>{message}</p><button type="button" className="btn secondary" onClick={async () => {try {await navigator.clipboard.writeText(message.trim()); setCopied(true);} catch {setError('Copy is unavailable. Select the preview text and copy it manually.');}}}>{copied ? 'Copied' : 'Copy customer message'}</button></details>}
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="button-row"><button className="btn primary-action" disabled={pending}>{pending ? 'Recording resolution…' : 'Record resolution and close incident'}</button><button type="button" className="btn secondary" disabled={pending} onClick={onCancel}>Cancel</button></div>
    </form>
  </Panel>;
}
