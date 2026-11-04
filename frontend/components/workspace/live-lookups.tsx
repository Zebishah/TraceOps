'use client';
import {useState} from 'react';
import {z} from 'zod';
import {Search} from 'lucide-react';
import {api} from '@/lib/product/client';
import {rowSchema,searchSchema,stringValue,type Evidence} from '@/lib/product/contracts';
import {useLiveSearch} from '@/hooks/use-live-search';
import {useResource} from '@/hooks/use-resource';
import {useSession} from './context';
import {Panel,State} from './ui';

export function KnowledgeSearch({onSource}:{onSource:(evidence:Evidence)=>void}) {
  const {organizationId}=useSession();const [query,setQuery]=useState('');
  const input=useLiveSearch(setQuery,'',500);
  const result=useResource(query?signal=>api(`organizations/${organizationId}/retrieval/search`,searchSchema,{method:'POST',body:JSON.stringify({query,limit:5}),signal}):null,[organizationId,query]);
  return <><Panel title="Search company evidence"><form className="inline-form" onSubmit={event=>{event.preventDefault();input.submit();}}><Search size={16}/><label className="sr-only" htmlFor="evidence-query">Search company evidence</label><input type="search" id="evidence-query" value={input.value} onChange={event=>input.change(event.target.value)} maxLength={2000} placeholder="Search policies, procedures, and relevant passages…"/><button className="btn secondary">Search</button></form><p className="context-note">Results update as you type. Source passages stay linked to their documents.</p></Panel>{query&&<Panel title="Matching source passages"><State emptyTitle="No matching results" emptyDescription="Try different words or clear the search to start again." loading={result.loading} error={result.error} empty={result.data?.results.length===0} onRetry={result.refresh}>{result.data?.results.map((item,index)=><button className="evidence-card source-button" key={item.chunk_id} onClick={()=>onSource(item)}><strong>[SOURCE {index+1}] {item.source_filename} · Page {item.page_number}</strong><p>{item.text}</p><small>Inspect source and relevance scores ↗</small></button>)}</State></Panel>}</>;
}

export function ProjectKnowledgeSearch() {
  const {organizationId}=useSession();const [query,setQuery]=useState('');const input=useLiveSearch(setQuery,'',500);
  const result=useResource(query?signal=>api(`organizations/${organizationId}/dashboard/project-knowledge`,z.array(rowSchema),{method:'POST',body:JSON.stringify({query,limit:5}),signal}):null,[organizationId,query]);
  return <Panel title="Search project knowledge"><p>Search curated project documentation, separately from your organization’s uploaded documents.</p><form className="inline-form" onSubmit={event=>{event.preventDefault();input.submit();}}><Search size={15}/><label className="sr-only" htmlFor="project-query">Search project knowledge</label><input type="search" id="project-query" value={input.value} onChange={event=>input.change(event.target.value)} maxLength={2000} placeholder="How does approval recovery work?"/><button className="btn secondary">Search</button></form><p className="context-note">Results update after you pause typing.</p>{query&&<State emptyTitle="No matching results" emptyDescription="Try different words or clear the search to start again." loading={result.loading} error={result.error} empty={result.data?.length===0} onRetry={result.refresh}>{result.data?.map((row,index)=><article className="evidence-card" key={index}><strong>{stringValue(row.source)} / {stringValue(row.section)}</strong><p>{stringValue(row.text)}</p></article>)}</State>}</Panel>;
}
