'use client';

import Image from 'next/image';
import { useState, type ReactNode } from 'react';
import { Activity, BookOpen, BrainCircuit, CheckCheck, Database, FileSearch, Fingerprint, GitBranch, Layers3, Network, Pause, Play, ScanText, ShieldCheck, Workflow } from 'lucide-react';
import { useMotionActivity } from '@/hooks/use-motion-activity';
import { artworkForContext, artworkScenes, BannerSurround } from './banner-artwork';
import './workspace-banner.css';

export const bannerContent = {
  incidents: { headline:'From signal to a grounded decision.', description:'Bring the report, company knowledge, and operational facts into one investigation. Inspect the evidence before deciding what happens next.', labels:['Capture the issue','Investigate with context','Review the evidence'], nodes:['Incident context','AI investigation','Source evidence'], icon:BrainCircuit },
  approvals: { headline:'AI proposes. You hold the decision.', description:'Review the exact action and its supporting context. Sensitive changes wait for an authorized person, with execution recorded separately.', labels:['Inspect the proposal','Record a decision','Track execution'], nodes:['Grounded proposal','Human judgment','Recorded outcome'], icon:ShieldCheck },
  knowledge: { headline:'Give every answer a source.', description:'Turn company documents into searchable context. Find relevant passages and ask questions with the source attached.', labels:['Company documents','Semantic retrieval','Cited answers'], nodes:['Document library','Relevant passages','Source citations'], icon:BookOpen },
  operations: { headline:'Connect the records behind the report.', description:'Move from a customer to their orders and payments. Check the current operational facts that support an investigation.', labels:['Customer context','Order relationships','Payment records'], nodes:['Customer','Order','Transactions'], icon:Database },
  memory: { headline:'Let past work inform the next.', description:'Explore saved incident context and recorded resolutions. Use history to guide your investigation, then verify the current facts.', labels:['Historical context','Recorded resolutions','Related incidents'], nodes:['Past investigations','Saved context','Next investigation'], icon:Layers3 },
  mcp: { headline:'Connect AI to the right context.', description:'Give an authorized AI client access to scoped knowledge and operational tools through the Model Context Protocol.', labels:['Authenticated clients','Scoped tools','Organization boundaries'], nodes:['Your AI client','MCP connection','TraceOps context'], icon:Network },
  automations: { headline:'Keep every handoff in view.', description:'Follow operational events from the durable queue to n8n. Inspect acceptance, retry attempts, and terminal delivery failures.', labels:['Persisted events','Delivery attempts','Controlled retries'], nodes:['Operational event','n8n handoff','Delivery record'], icon:Workflow },
  jobs: { headline:'Long-running work. Clear outcomes.', description:'Inspect background investigations, document processing, and approval recovery through the states recorded by your workers.', labels:['Worker progress','Failure visibility','Durable recovery'], nodes:['Queued work','Background worker','Saved result'], icon:Activity },
  quality: { headline:'Make model quality inspectable.', description:'Review published evaluation suites, acceptance targets, and individual checks for this workspace. See the evidence behind the result.', labels:['Published results','Suite thresholds','Individual checks'], nodes:['Evaluation suites','Acceptance targets','Measured results'], icon:CheckCheck },
  system: { headline:'Know what your workspace runs on.', description:'Inspect configured integrations and request dependency readiness when needed. Configuration and measured availability remain distinct.', labels:['Integration roles','On-demand readiness','Execution controls'], nodes:['Dependencies','AI integrations','Readiness checks'], icon:GitBranch },
  developer: { headline:'Inspect the intelligence underneath.', description:'Explore the API, workflow architecture, and project knowledge behind the interface. Trace how the pieces fit together.', labels:['API reference','Workflow architecture','Project knowledge'], nodes:['Authenticated API','Durable workflow','Developer context'], icon:GitBranch },
  settings: { headline:'Your workspace. Clear boundaries.', description:'See your authenticated identity, selected organization, and role permissions. Backend access checks remain authoritative.', labels:['Account identity','Organization scope','Role permissions'], nodes:['Your account','Organization','Permitted work'], icon:ShieldCheck },
} as const;
export type BannerKind = keyof typeof bannerContent;

/** Decorative context illustration; never substitutes for recorded job progress. */
export function WorkspaceBanner({ kind, variant, children }: { kind:BannerKind; variant?:string; children?:ReactNode }) {
  const [motion,setMotion] = useState(true);
  const { element,active } = useMotionActivity(motion);
  const content = bannerContent[kind];
  const Icon = content.icon;
  const artwork = artworkForContext(kind,variant);
  const scene = artworkScenes[artwork];
  return <section ref={element} className={`workspace-banner banner-${kind}`} data-motion={active?'running':'paused'} aria-label={`${kind} workflow overview`}>
    <div className="banner-grid" aria-hidden="true"/>
    <div className="banner-content"><span className="banner-eyebrow"><Fingerprint size={14}/> TRACEOPS / {kind==='approvals'?'HUMAN CONTROL':'WORKSPACE INTELLIGENCE'}</span><h2>{content.headline}</h2><p>{content.description}</p><div className="banner-capabilities">{content.labels.map((label,index)=><span key={label}>{index===0?<FileSearch size={12}/>:index===1?<ScanText size={12}/>:<ShieldCheck size={12}/>} {label}</span>)}</div>{children}</div>
    <div className={`banner-visual visual-${scene}`} data-artwork={artwork} aria-hidden="true"><BannerSurround scene={scene}/><Image unoptimized className="banner-core-image" src={`/images/workspace/art/${artwork}.webp`} width={480} height={480} alt="" decoding="async"/>{content.nodes.map((label,index)=><div key={label} className={`banner-context-node context-node-${index}`}><span>{index===0?<Database size={12}/>:index===1?<Icon size={12}/>:<BookOpen size={12}/>}</span><small>{label}</small><i/></div>)}<span className="banner-coordinate">{artwork.replaceAll('-',' / ').toUpperCase()} / ILLUSTRATED CONTEXT</span></div>
    <button type="button" className="banner-motion-control" onClick={()=>setMotion(value=>!value)} aria-label={`${motion?'Pause':'Resume'} ${kind} banner animation`}>{motion?<Pause size={12}/>:<Play size={12}/>}</button>
    <span className="banner-illustration-note">WORKFLOW VISUALIZATION</span>
  </section>;
}
