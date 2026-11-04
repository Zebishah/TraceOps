'use client';
import {useState} from 'react';
import {ArrowUpRight,Search,X} from 'lucide-react';
import {api} from '@/lib/product/client';
import {pageSchema,stringValue} from '@/lib/product/contracts';
import {useLiveSearch} from '@/hooks/use-live-search';
import {useResource} from '@/hooks/use-resource';
import {Badge,State} from './ui';

export function IncidentSearch({active,organizationId,onClose,onNavigate}:{active:boolean;organizationId:string;onClose:()=>void;onNavigate:(path:string)=>void}) {
  const [query,setQuery]=useState('');const input=useLiveSearch(setQuery);
  const results=useResource(active&&organizationId&&query?signal=>api(`organizations/${organizationId}/dashboard/resources/incidents?limit=6&offset=0&q=${encodeURIComponent(query)}`,pageSchema,{signal}):null,[active,organizationId,query]);
  return <form onSubmit={event=>{event.preventDefault();onNavigate(`/app/incidents?q=${encodeURIComponent(input.value.trim())}`);}}><div className="command-search-input"><Search size={20}/><label className="sr-only" htmlFor="command-search">Search incidents</label><input type="search" id="command-search" autoFocus value={input.value} onChange={event=>input.change(event.target.value)} placeholder="Find an incident…" maxLength={200}/><button type="button" aria-label="Close search" onClick={onClose}><X size={18}/></button></div><p>Results update as you type within your selected workspace.</p>{query&&<div className="command-search-results"><State emptyTitle="No matching results" emptyDescription="Try different words or clear the search to start again." loading={results.loading} error={results.error} empty={results.data?.items.length===0} onRetry={results.refresh}>{results.data?.items.map(row=><button type="button" key={stringValue(row.id)} onClick={()=>onNavigate(`/app/incidents/${stringValue(row.id)}`)}><span><strong>{stringValue(row.title)}</strong><small>INC-{stringValue(row.id).slice(0,8)}</small></span><Badge value={row.status}/><ArrowUpRight size={14}/></button>)}</State></div>}<div className="command-search-footer"><span>{results.data?`${results.data.total} matches`:'Organization-scoped search'}</span><button className="btn primary-action">View all results <ArrowUpRight size={14}/></button></div></form>;
}
