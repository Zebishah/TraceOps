'use client';

import Link from 'next/link';

import { useState } from 'react';
import { useMotionActivity } from '@/hooks/use-motion-activity';
import { Pause, Play, Activity, ArrowRight, BookOpen, BrainCircuit, Check, CheckCheck, CircleDot, Clock3, Database, FileText, GitBranch, Layers3, ShieldCheck, Terminal, Workflow } from 'lucide-react';
import { classificationConfidenceLabel, dateValue, stringValue, type Approval, type Incident, type Investigation, type Job, type Row, type Workspace } from '@/lib/product/contracts';
import { Badge } from './ui';
import {savedResultLabel} from '@/lib/product/workflow-view';
import {InvestigationTheater} from './investigation-theater';

export function SignalMark({ small = false }: { small?: boolean }) {
  return <span className={`signal-mark ${small ? 'small' : ''}`} aria-hidden="true"><BrainCircuit size={small ? 17 : 25} /></span>;
}

export function WorkflowMap({ workspace, counts }: { workspace?: Workspace | null; counts?: { documents: number; memories: number; pending_approvals: number; pending_automation: number } }) {
  const [motion, setMotion] = useState(true);
  const { element, active } = useMotionActivity(motion);
  const model = workspace?.integrations.find(item => /classification|analysis|reasoning/i.test(item.role) && item.model)?.model;
  return <section ref={element} className="orchestration-map map-motion" data-motion={active?'running':'paused'} aria-label="Investigation architecture">
    <div className="map-topline"><span><GitBranch size={14} /> INVESTIGATION ENGINE</span><div className="map-controls"><button type="button" className="map-motion-button" onClick={() => setMotion(value => !value)} aria-label={motion?'Pause architecture animation':'Resume architecture animation'}>{motion?<Pause size={12}/>:<Play size={12}/>}</button><Link href="/app/developer">Explore architecture <ArrowRight size={13} /></Link></div></div>
    <div className="map-layout">
      <div className="map-inputs"><Link href="/app/knowledge"><BookOpen size={18} /><span><strong>Company knowledge</strong><small>{counts ? `${counts.documents} documents` : 'Cited policy passages'}</small></span></Link><Link href="/app/operations"><Database size={18} /><span><strong>Operational records</strong><small>Customers · orders · payments</small></span></Link><Link href="/app/memory"><Layers3 size={18} /><span><strong>Incident memory</strong><small>{counts ? `${counts.memories} saved memories` : 'Historical context'}</small></span></Link></div>
      <div className="map-engine"><div className="engine-orbit"><SignalMark /></div><span className="engine-label">LANGGRAPH WORKFLOW</span><h3>Context → investigation</h3><p>Retrieve evidence. Inspect records.<br />Prepare a grounded next step.</p><code>{model ?? 'Model configured in System & Integrations'}</code></div>
      <div className="map-outputs"><Link href="/app/incidents"><FileText size={18} /><span><strong>Evidence & findings</strong><small>Sources attached to the result</small></span><ArrowRight size={14} /></Link><Link href="/app/approvals" className="human-node"><ShieldCheck size={18} /><span><strong>Human decision</strong><small>{counts ? `${counts.pending_approvals} pending proposals` : 'Sensitive actions pause here'}</small></span><ArrowRight size={14} /></Link><Link href="/app/automations"><Workflow size={18} /><span><strong>Durable automation</strong><small>{counts ? `${counts.pending_automation} pending deliveries` : 'Intake · delivery · recovery'}</small></span><ArrowRight size={14} /></Link></div>
    </div>
    <div className="map-caption"><span><ShieldCheck size={12} /> Organization-scoped context</span><span><CheckCheck size={12} /> Human approval for sensitive actions</span><span>Architecture view · counts are a workspace snapshot</span></div>
  </section>;
}

export function InvestigationStages(props: { incident: Incident; job?: Job | null; result?: Investigation | null; approval?: Approval | null; onInspect?: (tab: string) => void }) {
  return <InvestigationTheater {...props}/>;
}

export function InvestigationSummary({ result, approval, job, onInspect }: { result: Investigation; approval?: Approval|null; job?: Job|null; onInspect?: (tab: string) => void }) {
  const { element, active } = useMotionActivity(true);
  const confidence=result.classification_confidence;
  const label=savedResultLabel(result.needs_more_information,result.approval_required,approval?.status);
  return <section ref={element} className="result-dossier" data-motion={active?'running':'paused'} aria-label="Saved investigation overview"><div className="dossier-grid" aria-hidden="true"/><header><span><CheckCheck size={14}/> INVESTIGATION / SAVED RESULT</span><span className="dossier-state"><i/>{result.needs_more_information?'Clarification requested':'Analysis available'}</span></header><div className="dossier-main"><div className="dossier-heading"><span className="dossier-sigil"><BrainCircuit size={24}/></span><div><span className="dossier-overline">FROM SIGNAL TO UNDERSTANDING</span><h2>{label}</h2><p>{result.needs_more_information?'Review the missing context before continuing.':'Explore the sources, operational records, and history behind this result.'}</p></div></div><div className="dossier-metrics">{[{value:result.evidence.length,label:'Source evidence',tab:'Evidence',icon:BookOpen},{value:result.tool_results.length,label:'Tool results',tab:'Operational records',icon:Terminal},{value:result.similar_memories.length,label:'Related memories',tab:'Memory',icon:Layers3}].map(({value,label:metricLabel,tab,icon:Icon})=><button type="button" key={tab} onClick={()=>onInspect?.(tab)} disabled={!onInspect}><span><Icon size={14}/><ArrowRight size={11}/></span><strong>{String(value).padStart(2,'0')}</strong><small>{metricLabel}</small></button>)}<div className="dossier-confidence"><div aria-label={`Classification confidence: ${classificationConfidenceLabel(confidence)}`} style={{background:confidence===null?'#394132':`conic-gradient(#d4b47e ${Math.max(0,Math.min(100,confidence*100))}%,#394132 0)`}}><span>{confidence===null?'—':Math.round(confidence*100)}{confidence!==null&&<small>%</small>}</span></div><span>Classification<br/>{confidence===null?'unavailable':'confidence'}</span></div></div></div><footer><span><ShieldCheck size={12}/>{result.approval_required?'Sensitive proposal requires human authorization':'Review findings before taking further action'}</span><span>{job?'RUN / '+job.id.slice(0,8):'SAVED INVESTIGATION SNAPSHOT'}</span></footer></section>;
}

export function IncidentCards({ rows, onSelect, compact = false }: { rows: Row[]; onSelect: (row: Row) => void; compact?: boolean }) {
  return <div className={`incident-card-list ${compact ? 'compact' : ''}`}>{rows.map((row, index) => <button className="incident-card" key={stringValue(row.id ?? index)} onClick={() => onSelect(row)}><div className={`incident-priority-mark priority-${stringValue(row.priority)}`}><CircleDot size={17} /></div><div className="incident-card-content"><div className="incident-card-kicker"><span>INC-{stringValue(row.id).slice(0, 8).toUpperCase()}</span><span>{typeof row.category === 'string' ? row.category : 'Classification pending'}</span></div><h3>{stringValue(row.title)}</h3>{!compact && typeof row.description === 'string' && <p>{row.description}</p>}<div className="incident-card-tags"><Badge value={row.status} /><Badge value={row.priority ?? 'unclassified'} /><span><Clock3 size={11} />{dateValue(row.created_at)}</span></div></div><ArrowRight size={17} /></button>)}</div>;
}

export function IncidentBoard({ rows, onSelect }: { rows: Row[]; onSelect: (row: Row) => void }) {
  const lanes = [{ name: 'Intake', states: ['new'] }, { name: 'Investigating', states: ['investigating'] }, { name: 'Human review', states: ['awaiting_approval'] }, { name: 'Resolved / other', states: [] }];
  return <div className="incident-board">{lanes.map(lane => { const items = rows.filter(row => lane.states.length ? lane.states.includes(String(row.status)) : !['new', 'investigating', 'awaiting_approval'].includes(String(row.status))); return <section key={lane.name}><header><span><i />{lane.name}</span><strong>{items.length}</strong></header>{items.map(row => <button key={stringValue(row.id)} onClick={() => onSelect(row)}><span className="mono-label">INC-{stringValue(row.id).slice(0, 8)}</span><h3>{stringValue(row.title)}</h3><div><Badge value={row.priority ?? 'unclassified'} /><span>{stringValue(row.category)}</span></div></button>)}{!items.length && <p className="lane-empty">No incidents in this stage on this page.</p>}</section>; })}</div>;
}

export function MemoryCards({ rows, onSelect }: { rows: Row[]; onSelect: (row: Row) => void }) {
  return <div className="memory-grid">{rows.map((row, index) => <button className="memory-card" key={stringValue(row.id ?? index)} onClick={() => onSelect(row)}><header><span><Layers3 size={16} /> INCIDENT MEMORY</span><Badge value={row.category} /></header><h3>{stringValue(row.summary)}</h3><p>{typeof row.resolution === 'string' ? row.resolution : 'Open to inspect the recorded outcome.'}</p><footer><span>{dateValue(row.created_at)}</span><span>Inspect memory <ArrowRight size={14} /></span></footer></button>)}</div>;
}

export function MemoryDetail({ record }: { record: Row }) {
  return <div className="memory-detail"><div className="memory-detail-label"><Layers3 size={19} /><span>RECORDED INCIDENT CONTEXT</span><Badge value={record.category} /></div><h3>What happened</h3><p>{stringValue(record.summary)}</p><div className="memory-resolution"><CheckCheck size={19} /><div><h3>Recorded resolution</h3><p>{stringValue(record.resolution)}</p></div></div><div className="record-footprint"><span>Recorded {dateValue(record.created_at)}</span><code>Memory {stringValue(record.id)}</code></div><p className="context-note">Historical context supports investigation; it does not independently verify current facts or external money movement.</p></div>;
}

export function ApprovalCards({ rows, onSelect }: { rows: Row[]; onSelect: (row: Row) => void }) {
  return <div className="approval-card-grid">{rows.map((row,index)=>{
    const payload=row.action_payload&&typeof row.action_payload==='object'&&!Array.isArray(row.action_payload)?row.action_payload as Row:null;
    const pending=row.status==='pending';
    return <button key={stringValue(row.id??index)} className={`proposal-card ${pending?'proposal-pending':''}`} onClick={()=>onSelect(row)}>
      <header><span className="proposal-card-identity"><span className="proposal-card-glyph"><ShieldCheck size={20}/></span><span><small>{pending?'REVIEW REQUIRED':'RECORDED PROPOSAL'}</small><code>APR-{stringValue(row.id).slice(0,8).toUpperCase()}</code></span></span><Badge value={row.status}/></header>
      <div className="proposal-card-heading"><h3>{stringValue(row.action_type).replaceAll('_',' ')}</h3>{payload?.amount!==undefined&&payload.amount!==null&&<span className="proposal-inline-amount">{stringValue(payload.amount)} <small>{stringValue(payload.currency)}</small></span>}</div>
      <span className="proposal-reason-label">PROPOSAL CONTEXT</span><p>{stringValue(row.reason)}</p>
      <div className="proposal-scope"><ShieldCheck size={12}/> Organization-scoped action <span>•</span> {pending?'Human decision needed':'Open to inspect the recorded outcome'}</div>
      <footer><span><Clock3 size={12}/>{dateValue(row.created_at)}</span><span>{pending?'Review proposal':'Inspect decision'} <ArrowRight size={14}/></span></footer>
    </button>;
  })}</div>;
}

export function JobCards({ rows, onSelect }: { rows: Row[]; onSelect: (row: Row) => void }) {
  return <div className="job-card-list">{rows.map((row, index) => <button className="job-card" key={stringValue(row.id ?? index)} onClick={() => onSelect(row)}><span className="job-card-icon"><Activity size={20} /></span><div><span className="mono-label">JOB / {stringValue(row.id).slice(0, 8)}</span><h3>{stringValue(row.job_type ?? 'Approval recovery').replaceAll('_', ' ')}</h3><small>{dateValue(row.created_at ?? row.next_attempt_at)}</small></div><Badge value={row.status} /><div className="job-card-progress">{typeof row.progress_percent === 'number' ? <><progress value={row.progress_percent} max={100} aria-label="Reported job progress" /><span>{row.progress_percent}%</span></> : <span>{stringValue(row.attempts)} attempts</span>}</div><ArrowRight size={16} /></button>)}</div>;
}

export function DeliveryCards({ rows, onSelect }: { rows: Row[]; onSelect: (row: Row) => void }) {
  return <div className="delivery-card-list">{rows.map((row, index) => <button className="delivery-card" key={stringValue(row.id ?? index)} onClick={() => onSelect(row)}><div className="delivery-symbol"><Workflow size={22} /></div><div><span className="mono-label">DURABLE EVENT DELIVERY</span><h3>{stringValue(row.event_type).replaceAll('_', ' ')}</h3><div className="delivery-route"><span>TraceOps</span><ArrowRight size={13} /><span>n8n intake</span><ArrowRight size={13} /><span>{String(row.status) === 'delivered' ? 'Accepted' : 'Awaiting acceptance'}</span></div>{typeof row.last_error === 'string' && <p className="delivery-error">{row.last_error}</p>}</div><div className="delivery-card-state"><Badge value={row.status} /><small>{stringValue(row.attempt_count ?? row.attempts ?? 0)} attempts</small></div><ArrowRight size={16} /></button>)}</div>;
}

export function AnalystText({ text, onCitation }: { text: string; onCitation: (kind: string, index: number) => void }) {
  const sections = text.split(/\n\s*\n/).filter(Boolean);
  return <div className="analyst-text">{sections.map((section, index) => { const lines = section.split('\n'); const first = lines[0].replace(/^#+\s*|\*\*/g, '').trim(); const isHeading = lines.length > 1 && ['findings', 'uncertainty', 'current state', 'recommendation', 'recommended action'].includes(first.toLowerCase()); const body = isHeading ? lines.slice(1).join('\n') : section; return <section className={`analysis-part ${isHeading?'analysis-'+first.toLowerCase().replaceAll(' ','-'):''}`} key={index}>{isHeading && <div className="analysis-part-heading"><span className="analysis-part-index">{String(index+1).padStart(2,'0')}</span><h3>{first}</h3><small>{first.toLowerCase()==='uncertainty'?'REQUIRES JUDGMENT':first.toLowerCase()==='current state'?'SAVED CONTEXT':'INVESTIGATOR SYNTHESIS'}</small></div>}<p>{body.split(/(\[(?:SOURCE|TOOL|MEMORY|DETECTION)\s+\d+\])/g).map((part, n) => { const match = part.match(/^\[(SOURCE|TOOL|MEMORY|DETECTION)\s+(\d+)\]$/); return match && match[1] !== 'DETECTION' ? <button className="citation" key={n} onClick={() => onCitation(match[1], Number(match[2]) - 1)}>{part}</button> : <span key={n}>{part.replaceAll('**', '')}</span>; })}</p></section>; })}</div>;
}

export function ContextReadiness({ hasCustomer }: { hasCustomer: boolean }) {
  return <aside className="context-readiness"><span className="app-eyebrow">FROM REPORT TO RESOLUTION</span><div className="intake-illustration"><FileText size={25} /><ArrowRight size={19} /><SignalMark /><ArrowRight size={19} /><ShieldCheck size={25} /></div><h2>A focused brief.<br />A grounded investigation.</h2><p>Give the investigator the context it needs. It will check the available records before proposing a next step.</p><div className="readiness-item"><Check size={15} /><div><strong>Describe the observed issue</strong><p>What happened, and what outcome is needed?</p></div></div><div className={`readiness-item ${hasCustomer ? 'ready' : ''}`}><CircleDot size={15} /><div><strong>{hasCustomer ? 'Customer selected' : 'Identify the customer when known'}</strong><p>{hasCustomer ? 'The investigation can access scoped customer records.' : 'Missing identification may lead to a clarification request.'}</p></div></div><div className="readiness-item"><Database size={15} /><div><strong>Include relevant identifiers</strong><p>Order and transaction IDs help connect the facts.</p></div></div><div className="guardrail-note"><ShieldCheck size={16} />Sensitive actions require an authorized human decision.</div></aside>;
}
