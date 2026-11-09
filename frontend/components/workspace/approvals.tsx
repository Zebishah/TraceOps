'use client';

import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { z } from 'zod';
import { ArrowLeft, ArrowRight, Check, CheckCheck, Clock3, FileCheck, Fingerprint, Info, MessageSquare, RefreshCw, ShieldCheck, UserRound, X } from 'lucide-react';
import { api, post } from '@/lib/product/client';
import { approvalSchema, can, dateValue, stringValue, type Approval, type Role } from '@/lib/product/contracts';
import { useResource } from '@/hooks/use-resource';
import { useSession } from './context';
import { Badge, Details, PageHeading, State } from './ui';
import './approval-workspace.css';

const recoverySchema = z.object({job_id:z.string(),status:z.string(),attempts:z.number(),max_attempts:z.number(),quarantined:z.boolean(),next_attempt_at:z.string().nullable(),lease_expires_at:z.string().nullable(),completed_at:z.string().nullable()});
type Recovery = z.infer<typeof recoverySchema>;

export function ApprovalPage({incidentId,approvalId}:{incidentId:string;approvalId:string}) {
  const { organizationId, role, workspace, notify } = useSession();
  const prefix = `organizations/${organizationId}/incidents/${incidentId}/approvals/${approvalId}`;
  const result = useResource(signal=>api(prefix,approvalSchema,{signal}),[organizationId,incidentId,approvalId]);
  const [poll,setPoll] = useState(false);
  const resume = useResource(result.data&&['approved','executed','failed'].includes(result.data.status)?async signal=>{
    const data=await api(`${prefix}/resume-status`,recoverySchema,{signal});
    if(!signal.aborted&&['completed','failed'].includes(data.status)){setPoll(false);result.refresh();}
    return data;
  }:null,[organizationId,approvalId,result.data?.status],poll?10000:0);
  async function recordDecision(approved:boolean,comment:string) {
    await post(`${prefix}/decision`,approvalSchema,{approved,comment});
    notify(approved?'Approval recorded. Check this record for execution status.':'Rejection recorded. The proposed action was declined.');
    result.refresh();
    resume.refresh();
  }
  return <>
    <Link className="back-link" href={`/app/incidents/${incidentId}`}><ArrowLeft size={13}/> Related investigation</Link>
    <PageHeading visual="approvals" visualVariant="review" title="Review the proposed action" description="Inspect the exact proposal, supporting reason, and recorded outcome." eyebrow={`APPROVAL / ${approvalId.slice(0,8)}`} actions={<button className="btn secondary" disabled={result.refreshing} onClick={()=>{result.refresh();resume.refresh();}}><RefreshCw size={14} className={result.refreshing?'is-spinning':''}/> Refresh status</button>}/>
    <State loading={result.loading} error={result.error} onRetry={result.refresh}>{result.data&&<ApprovalReview key={result.data.id} approval={result.data} role={role} executionEnabled={workspace?.approval_execution_enabled??null} onConfirm={recordDecision}/>}</State>
    {resume.data&&<ApprovalRecovery data={resume.data} following={poll} onToggle={()=>setPoll(value=>!value)}/>}
    {!resume.data&&resume.error&&<section className="surface approval-recovery"><State error={resume.error} onRetry={resume.refresh}/></section>}
  </>;
}

/** Presentation and confirmation UI; the parent remains responsible for the backend mutation. */
export function ApprovalReview({approval,role,executionEnabled,onConfirm}:{approval:Approval;role:Role;executionEnabled:boolean|null;onConfirm:(approved:boolean,comment:string)=>Promise<void>}) {
  const [decision,setDecision] = useState<boolean|null>(null);
  const [comment,setComment] = useState('');
  const [busy,setBusy] = useState(false);
  const [submitted,setSubmitted] = useState(false);
  const [error,setError] = useState('');
  const pending = approval.status==='pending';
  const commentValid = comment.trim().length>=10;
  const transaction = approval.action_payload.external_transaction_id;
  const amount = stringValue(approval.action_payload.amount);
  // Group the supplied decimal string without converting or rounding the proposal amount.
  const displayAmount = /^-?\d+(\.\d+)?$/.test(amount)?amount.split('.').map((part,index)=>index===0?part.replace(/\B(?=(\d{3})+(?!\d))/g,','):part).join('.'):amount;
  async function confirm(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if(decision===null||!commentValid||busy||submitted||!pending) return;
    setBusy(true);setError('');
    try { await onConfirm(decision,comment);setSubmitted(true);setDecision(null); }
    catch(cause){setError(cause instanceof Error?cause.message:'Decision could not be recorded.');}
    finally{setBusy(false);}
  }
  const executionLabel = approval.executed_at?'Action executed':approval.status==='rejected'?'Action rejected':approval.status==='superseded'?'Proposal superseded':approval.status==='failed'?'Execution needs attention':'Execution not recorded';
  return <div className="approval-review-workspace">
    <div className="approval-record-path" aria-label="Recorded approval lifecycle">
      {[{title:'Proposal captured',detail:dateValue(approval.created_at),done:true,icon:FileCheck},{title:approval.decided_at?'Decision recorded':'Human decision',detail:approval.decided_at?dateValue(approval.decided_at):pending?'Awaiting an authorized reviewer':approval.status.replaceAll('_',' '),done:Boolean(approval.decided_at),icon:ShieldCheck},{title:executionLabel,detail:approval.executed_at?dateValue(approval.executed_at):'Approval and execution are separate',done:Boolean(approval.executed_at),icon:CheckCheck}].map(({title,detail,done,icon:Icon},index)=><div key={index} className={done?'record-step recorded':'record-step'}><span><Icon size={18}/></span><div><small>0{index+1}</small><strong>{title}</strong><p>{detail}</p></div>{index<2&&<ArrowRight size={14}/>}</div>)}
    </div>
    <div className="approval-review-columns">
      <section className="surface approval-proposal"><div className="approval-section-heading"><span><FileCheck size={17}/><strong>Proposed action</strong></span><Badge value={approval.status}/></div><div className="approval-proposal-body">
        <div className="approval-value-well"><span>EXACT PROPOSED AMOUNT</span><div>{displayAmount}<small>{stringValue(approval.action_payload.currency)}</small></div><p>{approval.action_type.replaceAll('_',' ')}</p></div>
        <dl className="approval-key-facts"><div><dt>Transaction</dt><dd>{transaction?<code>{stringValue(transaction)}</code>:'Not supplied in this proposal'}</dd></div><div><dt>Proposal reference</dt><dd><code>{approval.id}</code></dd></div></dl>
        <div className="approval-rationale"><span><BrainLabel/> WHY THIS ACTION WAS PROPOSED</span><p>{approval.reason}</p></div>
        {approval.action_type.includes('refund')&&<div className="approval-simulation-note"><Info size={16}/><p>Refund execution is an internal-ledger simulation. These records do not establish external provider money movement.</p></div>}
        <Details value={approval.action_payload} title="Inspect exact proposed payload"/>
      </div></section>
      <section className="surface approval-decision"><div className="approval-section-heading"><span><UserRound size={17}/><strong>{pending?'Your review & decision':'Recorded reviewer decision'}</strong></span><ShieldCheck size={17}/></div><div className="approval-decision-body">
        {pending?<><div className="reviewer-guidance"><Fingerprint size={21}/><div><strong>A person makes the call.</strong><p>Check the related investigation and the exact transaction before recording a decision.</p></div></div><Link className="approval-evidence-link" href={`/app/incidents/${approval.incident_id}`}>Inspect the related investigation <ArrowRight size={14}/></Link>
          {can(role,'review')?<><label className="approval-comment-label" htmlFor={`comment-${approval.id}`}><MessageSquare size={14}/> Your decision note</label><textarea id={`comment-${approval.id}`} value={comment} onChange={event=>{setComment(event.target.value);setDecision(null);}} rows={4} maxLength={1000} disabled={busy||submitted} placeholder="Explain what you verified and why you are approving or rejecting this action."/><div className="approval-comment-hint"><span>At least 10 characters explaining your decision.</span><span>{comment.length}/1000</span></div>
            <div className="approval-choice-grid"><button className={`approval-choice choice-approve ${decision===true?'choice-selected':''}`} type="button" aria-pressed={decision===true} disabled={busy||submitted||!commentValid} onClick={()=>setDecision(true)}><Check size={18}/><strong>Approve proposal</strong><small>Authorize this exact action</small></button><button className={`approval-choice choice-reject ${decision===false?'choice-selected':''}`} type="button" aria-pressed={decision===false} disabled={busy||submitted||!commentValid} onClick={()=>setDecision(false)}><X size={18}/><strong>Reject proposal</strong><small>Keep this action from execution</small></button></div>
            {submitted&&pending&&<p className="context-note" role="status">Decision recorded. Refreshing the saved record…</p>}{decision!==null&&<form className="approval-confirmation" onSubmit={confirm}><strong>Confirm {decision?'approval':'rejection'}</strong><p>{decision?'Record approval for the exact action and payload shown. Execution is tracked separately.':'Reject the exact action shown in this proposal.'}</p><blockquote>{comment}</blockquote><div className="button-row"><button className={`btn ${decision?'primary-action':'danger'}`} disabled={busy||submitted||!commentValid}>{busy?'Recording decision…':'Confirm decision'}</button><button type="button" className="btn secondary" disabled={busy} onClick={()=>setDecision(null)}>Cancel</button></div></form>}
          </>:<div className="notice">Your role can inspect this request. An authorized reviewer is required to approve or reject it.</div>}
        </>:<><div className={`decision-record-emblem decision-${approval.status}`}><span>{['rejected','failed'].includes(approval.status)?<X size={25}/>:approval.status==='superseded'?<Clock3 size={25}/>:approval.executed_at?<CheckCheck size={25}/>:<ShieldCheck size={25}/>}</span><div><small>RECORDED OUTCOME</small><strong>{approval.status.replaceAll('_',' ')}</strong><p>{approval.executed_at?'Execution has a recorded timestamp.':approval.status==='approved'?'Approval recorded. Inspect execution separately.':'Inspect the decision and recorded context below.'}</p></div></div><dl className="approval-key-facts decision-record-facts"><div><dt>Reviewer</dt><dd><code>{approval.decided_by_user_id??'Not recorded'}</code></dd></div><div><dt>Decision time</dt><dd>{dateValue(approval.decided_at)}</dd></div><div><dt>Execution time</dt><dd>{dateValue(approval.executed_at)}</dd></div></dl><div className="decision-note"><span><MessageSquare size={14}/> REVIEWER NOTE</span><p>{approval.decision_comment??'No decision comment is recorded.'}</p></div>{approval.supersession_reason&&<div className="notice">{approval.supersession_reason}</div>}<Link className="approval-evidence-link" href={`/app/incidents/${approval.incident_id}`}>Return to supporting investigation <ArrowRight size={14}/></Link></>}
        {approval.status==='approved'&&executionEnabled===false&&<div className="notice">Approval recovery execution is disabled. This decision may remain waiting for execution.</div>}{error&&<p className="form-error" role="alert">{error}</p>}
      </div></section>
    </div>
  </div>;
}
function BrainLabel(){return <Fingerprint size={13}/>;}

export function ApprovalRecovery({data,following,onToggle}:{data:Recovery;following:boolean;onToggle:()=>void}) {
  return <section className="surface approval-recovery"><div className="approval-section-heading"><span><RefreshCw size={17}/><strong>Durable execution & recovery</strong></span><button className="btn subtle" onClick={onToggle}><ActivityLabel following={following}/>{following?'Pause updates':'Follow updates'}</button></div><div className="approval-recovery-body"><div className="recovery-record-state"><Badge value={data.status}/>{data.quarantined&&<Badge value="quarantined"/>}<div><span>ATTEMPTS USED</span><strong>{data.attempts}<small> / {data.max_attempts}</small></strong></div><progress value={data.attempts} max={Math.max(1,data.max_attempts)} aria-label="Recovery attempts used"/></div><dl className="recovery-record-times"><div><dt><Clock3 size={13}/> Next attempt</dt><dd>{dateValue(data.next_attempt_at)}</dd></div><div><dt><ShieldCheck size={13}/> Lease expires</dt><dd>{dateValue(data.lease_expires_at)}</dd></div><div><dt><CheckCheck size={13}/> Completed</dt><dd>{dateValue(data.completed_at)}</dd></div></dl><p className="context-note">Updates read this approval’s recovery status. They do not trigger a global worker or change execution controls.</p></div></section>;
}
function ActivityLabel({following}:{following:boolean}){return <RefreshCw size={12} className={following?'is-spinning':''}/>;}
