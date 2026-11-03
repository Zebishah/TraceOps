'use client';

import { Activity, ArrowRight, BookOpen, BrainCircuit, Check, CheckCheck, CircleDot, Clock3, Database, FileText, GitBranch, Layers3, ShieldCheck, Terminal, Workflow } from 'lucide-react';
import { classificationConfidenceLabel, dateValue, stringValue, type Approval, type Incident, type Investigation, type Job, type Row, type Workspace } from '@/lib/product/contracts';
import { Badge } from './ui';
import {workflowStageStates,savedResultLabel} from '@/lib/product/workflow-view';

export function SignalMark({ small = false }: { small?: boolean }) {
  return <span className={`signal-mark ${small ? 'small' : ''}`} aria-hidden="true"><BrainCircuit size={small ? 17 : 25} /></span>;
}

export function WorkflowMap({ workspace, counts }: { workspace?: Workspace | null; counts?: { documents: number; memories: number; pending_approvals: number; pending_automation: number } }) {
  const model = workspace?.integrations.find(item => /classification|analysis|reasoning/i.test(item.role) && item.model)?.model;
  return <section className="orchestration-map" aria-label="Investigation architecture">
    <div className="map-topline"><span><GitBranch size={14} /> INVESTIGATION ENGINE</span><a href="/app/developer">Explore architecture <ArrowRight size={13} /></a></div>
    <div className="map-layout">
      <div className="map-inputs"><a href="/app/knowledge"><BookOpen size={18} /><span><strong>Company knowledge</strong><small>{counts ? `${counts.documents} documents` : 'Cited policy passages'}</small></span></a><a href="/app/operations"><Database size={18} /><span><strong>Operational records</strong><small>Customers · orders · payments</small></span></a><a href="/app/memory"><Layers3 size={18} /><span><strong>Incident memory</strong><small>{counts ? `${counts.memories} saved memories` : 'Historical context'}</small></span></a></div>
      <div className="map-engine"><div className="engine-orbit"><SignalMark /></div><span className="engine-label">LANGGRAPH WORKFLOW</span><h3>Context → investigation</h3><p>Retrieve evidence. Inspect records.<br />Prepare a grounded next step.</p><code>{model ?? 'Model configured in System & Integrations'}</code></div>
      <div className="map-outputs"><a href="/app/incidents"><FileText size={18} /><span><strong>Evidence & findings</strong><small>Sources attached to the result</small></span><ArrowRight size={14} /></a><a href="/app/approvals" className="human-node"><ShieldCheck size={18} /><span><strong>Human decision</strong><small>{counts ? `${counts.pending_approvals} pending proposals` : 'Sensitive actions pause here'}</small></span><ArrowRight size={14} /></a><a href="/app/automations"><Workflow size={18} /><span><strong>Durable automation</strong><small>{counts ? `${counts.pending_automation} pending deliveries` : 'Intake · delivery · recovery'}</small></span><ArrowRight size={14} /></a></div>
    </div>
    <div className="map-caption"><span><ShieldCheck size={12} /> Organization-scoped context</span><span><CheckCheck size={12} /> Human approval for sensitive actions</span><span>Architecture view · counts are a workspace snapshot</span></div>
  </section>;
}

export function InvestigationStages({ incident, job, result, approval }: { incident: Incident; job?: Job | null; result?: Investigation | null; approval?: Approval | null }) {
  const states=workflowStageStates({incidentStatus:incident.status,jobStatus:job?.status,hasResult:Boolean(result),approvalRequired:result?.approval_required,approvalStatus:approval?.status});
  const steps = [
    { title: 'Report captured', detail: 'Customer context & issue', state: 'done', icon: FileText },
    { title: 'AI investigation', detail: job?.status === 'processing' ? `${job.progress_percent}% · worker processing` : job?.status === 'queued' ? 'Waiting for a worker' : job?.status === 'failed' ? 'Worker needs attention' : job?.status === 'succeeded' ? 'Saved investigation ready' : 'Start when ready', state: states.investigation, icon: BrainCircuit },
    { title: result?.needs_more_information ? 'Clarification needed' : 'Evidence & findings', detail: result ? `${result.evidence.length} ${result.evidence.length===1?'source':'sources'} · ${result.tool_results.length} tool ${result.tool_results.length===1?'result':'results'}` : 'Available after investigation', state: states.evidence, icon: BookOpen },
    { title: 'Human review', detail: approval ? approval.status.replaceAll('_', ' ') : result ? (result.approval_required ? 'Review required' : 'No proposal in this result') : 'When a sensitive action is proposed', state: states.review, icon: ShieldCheck },
    { title: 'Outcome', detail: incident.status === 'resolved' ? 'Incident resolved' : approval?.executed_at ? 'Action executed · inspect incident state' : 'Resolution tracked separately', state: states.outcome, icon: CheckCheck },
  ];
  return <section className="investigation-stages" aria-label="Recorded investigation stages">{steps.map(({ title, detail, state, icon: Icon }, index) => <div className={`investigation-stage ${state}`} key={title}><div className="stage-track"><span>{state === 'done' ? <Check size={16} /> : <Icon size={16} />}</span><i /></div><small>0{index + 1}</small><strong>{title}</strong><p>{detail}</p></div>)}</section>;
}

export function InvestigationWaiting({ job }: { job?: Job | null }) {
  const active = job?.status === 'queued' || job?.status === 'processing';
  return <section className={`investigation-waiting ${active ? 'working' : ''}`}><div className="waiting-visual"><span /><span /><SignalMark /></div><div><span className="app-eyebrow">{active ? 'BACKGROUND WORKFLOW' : 'AI INVESTIGATION WORKSPACE'}</span><h2>{job?.status === 'failed' ? 'The investigation needs attention.' : active ? 'Building a clearer picture.' : 'Turn a report into an informed decision.'}</h2><p>{active ? 'The background worker gathers context and prepares a saved result. Stage details become available when the investigation finishes.' : job?.status === 'failed' ? 'Review the worker error and use the retry control when the cause is resolved.' : 'Start the investigation to bring together company policy, operational records, and relevant incident history.'}</p><div className="waiting-capabilities"><span><BookOpen size={13} /> Source evidence</span><span><Terminal size={13} /> Operational tools</span><span><ShieldCheck size={13} /> Human oversight</span></div>{active && <div className="waiting-progress"><progress value={job?.progress_percent ?? 0} max={100} aria-label="Reported worker progress" /><span>{job?.progress_percent ?? 0}% reported by worker</span></div>}</div></section>;
}

export function InvestigationSummary({ result, approval }: { result: Investigation; approval?: Approval|null }) {
  return <div className="investigation-summary"><div><SignalMark small /><span><small>SAVED AI RESULT</small><strong>{savedResultLabel(result.needs_more_information,result.approval_required,approval?.status)}</strong></span></div><div><BookOpen size={16} /><strong>{result.evidence.length}</strong><span>{result.evidence.length===1?'source':'sources'}</span></div><div><Terminal size={16} /><strong>{result.tool_results.length}</strong><span>{result.tool_results.length===1?'tool result':'tool results'}</span></div><div><Layers3 size={16} /><strong>{result.similar_memories.length}</strong><span>{result.similar_memories.length===1?'memory':'memories'}</span></div><div className="classification-score"><strong>{classificationConfidenceLabel(result.classification_confidence)}</strong><span>classification confidence</span></div></div>;
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
  return <div className="approval-card-grid">{rows.map((row, index) => { const payload = row.action_payload && typeof row.action_payload === 'object' && !Array.isArray(row.action_payload) ? row.action_payload as Row : null; return <button key={stringValue(row.id ?? index)} className="proposal-card" onClick={() => onSelect(row)}><header><span><ShieldCheck size={17} /> HUMAN REVIEW</span><Badge value={row.status} /></header><h3>{stringValue(row.action_type).replaceAll('_', ' ')}</h3>{payload && <div className="proposal-value">{stringValue(payload.amount)} <small>{stringValue(payload.currency)}</small></div>}<p>{stringValue(row.reason)}</p><footer><span>{dateValue(row.created_at)}</span><span>Review decision <ArrowRight size={14} /></span></footer></button>; })}</div>;
}

export function JobCards({ rows, onSelect }: { rows: Row[]; onSelect: (row: Row) => void }) {
  return <div className="job-card-list">{rows.map((row, index) => <button className="job-card" key={stringValue(row.id ?? index)} onClick={() => onSelect(row)}><span className="job-card-icon"><Activity size={20} /></span><div><span className="mono-label">JOB / {stringValue(row.id).slice(0, 8)}</span><h3>{stringValue(row.job_type ?? 'Approval recovery').replaceAll('_', ' ')}</h3><small>{dateValue(row.created_at ?? row.next_attempt_at)}</small></div><Badge value={row.status} /><div className="job-card-progress">{typeof row.progress_percent === 'number' ? <><progress value={row.progress_percent} max={100} aria-label="Reported job progress" /><span>{row.progress_percent}%</span></> : <span>{stringValue(row.attempts)} attempts</span>}</div><ArrowRight size={16} /></button>)}</div>;
}

export function DeliveryCards({ rows, onSelect }: { rows: Row[]; onSelect: (row: Row) => void }) {
  return <div className="delivery-card-list">{rows.map((row, index) => <button className="delivery-card" key={stringValue(row.id ?? index)} onClick={() => onSelect(row)}><div className="delivery-symbol"><Workflow size={22} /></div><div><span className="mono-label">DURABLE EVENT DELIVERY</span><h3>{stringValue(row.event_type).replaceAll('_', ' ')}</h3><div className="delivery-route"><span>OpsPilot</span><ArrowRight size={13} /><span>n8n intake</span><ArrowRight size={13} /><span>{String(row.status) === 'delivered' ? 'Accepted' : 'Awaiting acceptance'}</span></div>{typeof row.last_error === 'string' && <p className="delivery-error">{row.last_error}</p>}</div><div className="delivery-card-state"><Badge value={row.status} /><small>{stringValue(row.attempt_count ?? row.attempts ?? 0)} attempts</small></div><ArrowRight size={16} /></button>)}</div>;
}

export function AnalystText({ text, onCitation }: { text: string; onCitation: (kind: string, index: number) => void }) {
  const sections = text.split(/\n\s*\n/).filter(Boolean);
  return <div className="analyst-text">{sections.map((section, index) => { const lines = section.split('\n'); const first = lines[0].replace(/^#+\s*|\*\*/g, '').trim(); const isHeading = lines.length > 1 && ['findings', 'uncertainty', 'current state', 'recommendation', 'recommended action'].includes(first.toLowerCase()); const body = isHeading ? lines.slice(1).join('\n') : section; return <section key={index}>{isHeading && <h3>{first}</h3>}<p>{body.split(/(\[(?:SOURCE|TOOL|MEMORY|DETECTION)\s+\d+\])/g).map((part, n) => { const match = part.match(/^\[(SOURCE|TOOL|MEMORY|DETECTION)\s+(\d+)\]$/); return match && match[1] !== 'DETECTION' ? <button className="citation" key={n} onClick={() => onCitation(match[1], Number(match[2]) - 1)}>{part}</button> : <span key={n}>{part.replaceAll('**', '')}</span>; })}</p></section>; })}</div>;
}

export function ContextReadiness({ hasCustomer }: { hasCustomer: boolean }) {
  return <aside className="context-readiness"><span className="app-eyebrow">FROM REPORT TO RESOLUTION</span><div className="intake-illustration"><FileText size={25} /><ArrowRight size={19} /><SignalMark /><ArrowRight size={19} /><ShieldCheck size={25} /></div><h2>A focused brief.<br />A grounded investigation.</h2><p>Give the investigator the context it needs. It will check the available records before proposing a next step.</p><div className="readiness-item"><Check size={15} /><div><strong>Describe the observed issue</strong><p>What happened, and what outcome is needed?</p></div></div><div className={`readiness-item ${hasCustomer ? 'ready' : ''}`}><CircleDot size={15} /><div><strong>{hasCustomer ? 'Customer selected' : 'Identify the customer when known'}</strong><p>{hasCustomer ? 'The investigation can access scoped customer records.' : 'Missing identification may lead to a clarification request.'}</p></div></div><div className="readiness-item"><Database size={15} /><div><strong>Include relevant identifiers</strong><p>Order and transaction IDs help connect the facts.</p></div></div><div className="guardrail-note"><ShieldCheck size={16} />Sensitive actions require an authorized human decision.</div></aside>;
}
