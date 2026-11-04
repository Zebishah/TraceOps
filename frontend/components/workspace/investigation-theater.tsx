'use client';

import Link from 'next/link';

import { useId, useState } from 'react';
import { useMotionActivity } from '@/hooks/use-motion-activity';
import { Activity, ArrowRight, BookOpen, BrainCircuit, CheckCheck, ChevronRight, CircleDot, FileText, Fingerprint, Pause, Play, ShieldCheck } from 'lucide-react';
import { dateValue, type Approval, type Incident, type Investigation, type Job } from '@/lib/product/contracts';
import { workflowStageStates, type StageState } from '@/lib/product/workflow-view';
import { SignalField } from './investigation-scene';
import { StageArtwork, type InvestigationStageId } from './stage-artwork';
import './investigation-theater.css';

const stages = [
  { id:'report', title:'Report & context', short:'Intake', icon:FileText, heading:'A clear starting point.', description:'Capture the reported issue and connect it to the right customer before investigating.', method:[['Capture the report','Save the observed issue and relevant order or transaction identifiers.'],['Scope the context','Use the selected organization and customer to limit access to operational records.'],['Identify missing details','The saved investigation may ask for clarification when the context is incomplete.']] },
  { id:'analysis', title:'AI investigation', short:'Reasoning', icon:BrainCircuit, heading:'Connect the available signals.', description:'Use the investigation workflow to classify the incident and bring relevant policy, history, and operational records into context.', method:[['Classify the incident','Assign a category and priority from the reported issue.'],['Gather working context','Retrieve relevant knowledge and inspect authorized operational records.'],['Save the investigation','Persist the result through the background workflow for later review.']] },
  { id:'evidence', title:'Evidence & findings', short:'Evidence', icon:BookOpen, heading:'Make every finding inspectable.', description:'Review the saved analysis alongside its source passages, tool output, and relevant incident history.', method:[['Read the findings','See what the available evidence supports and what remains uncertain.'],['Inspect the sources','Open cited passages and the operational tools used in this investigation.'],['Review the recommendation','Check the suggested next step against current facts before acting.']] },
  { id:'review', title:'Human authorization', short:'Review', icon:ShieldCheck, heading:'Keep the decision with a person.', description:'Sensitive proposals pause for an authorized reviewer. Review the exact action, reason, and supporting records.', method:[['Inspect the proposal','Check the proposed transaction, amount, and reason against the investigation.'],['Record a decision','An authorized person approves or rejects the action with a comment.'],['Track execution separately','Approval and execution are separate recorded states.']] },
  { id:'outcome', title:'Outcome & follow-through', short:'Outcome', icon:CheckCheck, heading:'Close the loop with a record.', description:'Inspect the incident’s final state and any recorded execution. A completed investigation alone does not resolve an incident.', method:[['Verify the recorded result','Read the incident state and any approved action’s execution timestamp.'],['Resolve deliberately','Record a supported outcome, including a no-action resolution when appropriate.'],['Keep context for later','Saved history and delivery records support future investigation and follow-through.']] },
] as const;

const stateLabels: Record<StageState,string> = {done:'Recorded',active:'In progress',failed:'Needs attention',review:'Decision needed',waiting:'Pending', 'not-required':'No active proposal'};

export function InvestigationTheater({incident,job,result,approval,onInspect}:{incident:Incident;job?:Job|null;result?:Investigation|null;approval?:Approval|null;onInspect?:(tab:string)=>void}) {
  const [chosen,setChosen]=useState<InvestigationStageId|null>(null);
  const [motion,setMotion]=useState(true);
  const { element, active }=useMotionActivity(motion);
  const labelId=useId();
  const states=workflowStageStates({incidentStatus:incident.status,jobStatus:job?.status,hasResult:Boolean(result),approvalRequired:result?.approval_required,approvalStatus:approval?.status});
  const defaultStage:InvestigationStageId=incident.status==='resolved'||approval?.status==='executed'||approval?.status==='approved'?'outcome':approval?'review':result?.needs_more_information?'report':result?'evidence':job?'analysis':'report';
  const selection=chosen??defaultStage;
  const selected=stages.find(stage=>stage.id===selection)??stages[0];
  const statusFor=(id:InvestigationStageId):StageState=>id==='report'?'done':id==='analysis'?states.investigation:id==='evidence'?states.evidence:id==='review'?states.review:states.outcome;
  const labelFor=(id:InvestigationStageId)=>id==='analysis'&&job?job.status.replaceAll('_',' '):id==='report'?'Captured':id==='outcome'?incident.status==='resolved'?'Resolved':'Resolution pending':id==='review'&&approval?approval.status.replaceAll('_',' '):stateLabels[statusFor(id)];
  const facts:Record<InvestigationStageId,Array<[string,string]>>={
    report:[['Created',dateValue(incident.created_at)],['Customer context',incident.subject_customer_id?'Customer linked':'Customer not identified'],['Category',result?.category??incident.category??'Not classified yet'],['Clarification',result?.needs_more_information?'More context requested':result?'No clarification requested':'Determined by the investigation']],
    analysis:[['Worker state',job?.status??'Not started'],['Reported progress',job?`${job.progress_percent}%`:'No job yet'],['Category',result?.category??incident.category??'Pending classification'],['Priority',result?.priority??incident.priority??'Pending classification']],
    evidence:[['Source passages',result?String(result.evidence.length):'Not available yet'],['Operational tool results',result?String(result.tool_results.length):'Not available yet'],['Historical memories',result?String(result.similar_memories.length):'Not available yet'],['Saved result',result?'Available to inspect':'Available after investigation']],
    review:[['Approval request',approval?approval.status:result?.approval_required?'Required · inspect proposal':result?'No proposal in this result':'Determined after investigation'],['Decision recorded',dateValue(approval?.decided_at)],['Action executed',dateValue(approval?.executed_at)],['Action',approval?.action_type.replaceAll('_',' ')??'No action recorded']],
    outcome:[['Incident state',incident.status.replaceAll('_',' ')],['Resolved at',dateValue(incident.resolved_at)],['Action execution',approval?.executed_at?'Execution recorded':'No execution recorded'],['Memory indexing',result?result.memory_indexed?'Indexed':'Not indexed in this result':'Not recorded yet']],
  };
  const summary=selection==='report'&&result?.needs_more_information?result.clarification_question:selection==='analysis'&&job?.status==='queued'?'Queued for a background worker. No model or tool substep timing is reported by this endpoint.':selection==='analysis'&&job?.status==='processing'?'The worker is processing this incident. Progress is reported for the whole investigation, rather than individual internal substeps.':selection==='analysis'&&job?.status==='failed'?job.error_message:selection==='outcome'&&incident.resolution_reason?incident.resolution_reason:null;
  return <section ref={element} className="investigation-theater theater-motion" data-motion={active?'running':'paused'} aria-label="Interactive investigation workflow">
    <header className="theater-header"><div><Fingerprint size={17}/><span>OPSPILOT / INVESTIGATION ATLAS<small>Five connected stages. One accountable workflow.</small></span></div><div>{chosen&&<button type="button" className="theater-follow" onClick={()=>setChosen(null)}>Follow current stage <ArrowRight size={12}/></button>}<span className="theater-record-state"><i/>{job?job.status.replaceAll('_',' '):'Report captured'}</span><button className="theater-motion-button" type="button" onClick={()=>setMotion(value=>!value)} aria-label={motion?'Pause workflow animation':'Resume workflow animation'}>{motion?<Pause size={14}/>:<Play size={14}/>}</button></div></header>
    <div className="theater-layout">
      <div className="theater-universe"><div className="theater-starfield" aria-hidden="true"><SignalField animate={active}/></div><div className="universe-grid" aria-hidden="true"/><div className="universe-caption"><span>SELECT A STAGE TO EXPLORE</span><span>ILLUSTRATED WORKFLOW</span></div>
        <svg className="theater-connections" viewBox="0 0 600 500" preserveAspectRatio="none" aria-hidden="true"><path d="M300 67C420 65 500 128 505 210C511 303 457 399 411 414C312 466 211 466 177 414C101 356 57 274 95 210C144 126 205 58 300 67Z"/>{['M300 67V250','M505 210L300 250','M411 414L300 250','M177 414L300 250','M95 210L300 250'].map((d,i)=><path key={d} className={selection===stages[i].id?'selected-connection':''} d={d}/>)}</svg>
        <div className="theater-stage-art" key={selection}><StageArtwork stage={selection}/></div><div className="universe-coordinate" aria-hidden="true">{selected.short.toUpperCase()} / CONTEXT ENGINE</div>
        <div className="theater-nodes" role="group" aria-label="Explore investigation stages">{stages.map((stage,index)=>{const Icon=stage.icon;return <button key={stage.id} type="button" className={`theater-node node-${stage.id} node-state-${statusFor(stage.id)} ${selection===stage.id?'node-selected':''}`} aria-pressed={selection===stage.id} aria-controls={labelId} onClick={()=>setChosen(stage.id)}><span className="theater-node-glyph"><Icon size={18}/><i/></span><span className="theater-node-copy"><small>0{index+1} / {stage.short}</small><strong>{stage.title}</strong><em>{labelFor(stage.id)}</em></span></button>;})}</div>
        <div className="theater-universe-footer"><span><CircleDot size={11}/> Ambient visualization</span><span>Progress reflects saved records</span></div>
      </div>
      <section className="theater-inspector" id={labelId} aria-label={`${selected.title} stage details`}><div className="inspector-stage-label"><span>0{stages.findIndex(stage=>stage.id===selection)+1} / {selected.short.toUpperCase()}</span><span className={`inspector-status inspector-${statusFor(selection)}`}><i/>{labelFor(selection)}</span></div><div className="inspector-intro" key={selection}><h2>{selected.heading}</h2><p>{selected.description}</p></div>
        <div className="inspector-facts"><span className="inspector-eyebrow">WHAT THE RECORDS SHOW</span><dl>{facts[selection].map(([name,value])=><div key={name}><dt>{name}</dt><dd>{value==='—'?'Not recorded':value}</dd></div>)}</dl></div>
        {selection==='analysis'&&job&&<div className="inspector-progress"><div><span><Activity size={12}/>Worker-reported progress</span><strong>{job.progress_percent}%</strong></div><progress value={job.progress_percent} max={100} aria-label="Overall investigation progress"/></div>}
        {summary&&<p className="inspector-observation">{summary}</p>}
        <details className="inspector-method" key={`method-${selection}`} open><summary>How this stage works <ChevronRight size={13}/></summary><div>{selected.method.map(([title,text],index)=><article key={title}><span>0{index+1}</span><div><h3>{title}</h3><p>{text}</p></div></article>)}</div></details>
        <div className="inspector-actions">{selection==='evidence'&&result&&onInspect&&<><button type="button" onClick={()=>onInspect('Evidence')}>Inspect sources <ArrowRight size={13}/></button><button type="button" onClick={()=>onInspect('Operational records')}>Tool output <ArrowRight size={13}/></button></>}{selection==='review'&&approval&&<Link href={`/app/approvals/${incident.id}/${approval.id}`}>Open approval request <ArrowRight size={13}/></Link>}{selection==='outcome'&&onInspect&&<button type="button" onClick={()=>onInspect('Activity')}>Recorded activity <ArrowRight size={13}/></button>}</div>
      </section>
    </div>
    <footer className="theater-footer"><span><ShieldCheck size={12}/>Organization-scoped records · Human approval for sensitive actions</span><span>{job?`RUN / ${job.id.slice(0,8)}`:'READY FOR INVESTIGATION'}</span></footer>
  </section>;
}
