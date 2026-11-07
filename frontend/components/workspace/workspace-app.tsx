'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Activity, BrainCircuit, ArrowUpRight, Shield, Plus, BookOpen, Boxes, CheckCheck, ChevronDown, ClipboardList, Command, FileCheck, LayoutDashboard, Menu, Search, Settings, ShieldCheck, Workflow, Wrench, X } from 'lucide-react';
import { api } from '@/lib/product/client';
import { can, meSchema, workspaceSchema } from '@/lib/product/contracts';
import { useResource } from '@/hooks/use-resource';
import { Session } from './context';
import './workspace-redesign.css';
import { State } from './ui';
import {IncidentSearch} from './incident-search';
import { OverviewPage, ResourcePage, OperationsPage, JobsPage, SystemPage, QualityPage, DeveloperPage, McpPage, SettingsPage } from './workspace-pages';
import { IncidentPage, CreateIncidentPage } from './incidents';
import { KnowledgePage, DocumentPage } from './knowledge';
import { ApprovalPage } from './approvals';
import { LogoutButton } from './logout-button';

const navigation = [
  { group: 'Workspace', items: [['Command center', '', LayoutDashboard], ['Incidents', 'incidents', ClipboardList], ['Approvals', 'approvals', CheckCheck], ['Knowledge', 'knowledge', BookOpen], ['Operations', 'operations', Boxes], ['Incident Memory', 'memory', Activity]] },
  { group: 'Platform', items: [['MCP Connections', 'mcp', Command], ['Automations', 'automations', Workflow], ['Jobs & Recovery', 'jobs', Wrench]] },
  { group: 'Engineering', items: [['Quality & Evaluations', 'quality', FileCheck], ['System & Integrations', 'system', ShieldCheck], ['Developer Hub', 'developer', Command], ['Settings', 'settings', Settings]] },
] as const;

export function WorkspaceApp({ children, backendOrigin = null, uploadLimitBytes = 10*1024*1024 }: { children?: ReactNode; backendOrigin?: string | null; uploadLimitBytes?:number }) {
  const pathname = usePathname();
  const router = useRouter();
  const auth = useResource(signal => api('auth/me', meSchema, { signal }), []);
  const [organization, setOrganization] = useState(() => {
    if (typeof window === 'undefined') return '';
    try { return localStorage.getItem('opspilot.organization') ?? ''; } catch { return ''; }
  });
  const [mobile, setMobile] = useState(false);
  const [message, setMessage] = useState('');
  const searchDialog = useRef<HTMLDialogElement>(null);
  const [searchOpen,setSearchOpen]=useState(false);
  useEffect(() => {
    const openSearch = (event: KeyboardEvent) => {
      if (document.querySelector('dialog[open]')) return;
      const target = event.target;
      const editing = target instanceof HTMLElement && (['INPUT','TEXTAREA','SELECT'].includes(target.tagName) || target.isContentEditable);
      if (!editing && (event.key === '/' || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k'))) { event.preventDefault(); setSearchOpen(true);searchDialog.current?.showModal(); }
    };
    document.addEventListener('keydown', openSearch);
    return () => document.removeEventListener('keydown', openSearch);
  }, []);
  const selectedOrganization = auth.data?.memberships.some(m => m.organization_id === organization)
    ? organization : auth.data?.memberships[0]?.organization_id ?? '';
  const membership = auth.data?.memberships.find(m => m.organization_id === selectedOrganization);
  const workspace = useResource(selectedOrganization ? signal => api(`organizations/${selectedOrganization}/dashboard/workspace`, workspaceSchema, { signal }) : null, [selectedOrganization]);

  useEffect(() => {
    if (!auth.data) return;
    try {
      const saved = localStorage.getItem('opspilot.organization');
      if (auth.data.memberships.some(m => m.organization_id === saved)) setOrganization(saved ?? '');
    } catch { /* Storage can be unavailable; the first authorized membership still works. */ }
  }, [auth.data]);
  useEffect(() => { setMobile(false); }, [pathname]);
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(''), 6000);
    return () => clearTimeout(timer);
  }, [message]);

  const parts = pathname.replace(/^\/app\/?/, '').split('/').filter(Boolean);
  const section = parts[0] ?? '';
  const id = parts[1];
  const name = navigation.map(group => group.items.find(item => item[1] === section)?.[0]).find(Boolean) ?? 'Workspace';
  function navigate(path: string) { router.push(`/app${path ? '/' + path : ''}`); }
  function selectOrganization(value: string) {
    setOrganization(value);
    try { localStorage.setItem('opspilot.organization', value); } catch { /* Selection still works for this session. */ }
    router.push('/app');
  }

  let content: ReactNode;
  if (auth.loading) {
    content = <><div className="page-heading"><div><span className="app-eyebrow">YOUR OPERATIONS WORKSPACE</span><h1>{name}</h1><p>Connecting to your organization…</p></div></div><State loading /></>;
  } else if (auth.error || !auth.data) {
    content = <section className="surface workspace-session-state"><h1>Your session needs attention.</h1><p>{auth.error?.message ?? 'Please sign in again.'}</p><div className="page-actions"><button className="btn secondary" onClick={auth.refresh}>Retry connection</button><a className="btn primary-action" href="/login">Sign in to TraceOps ↗</a></div></section>;
  } else if (!membership) {
    content = <section className="surface workspace-session-state"><h1>No workspace available.</h1><p>This account has no organization membership.</p><a href="/register" className="btn primary-action">Create a workspace ↗</a></section>;
  } else {
    const page = section === '' ? <OverviewPage />
      : section === 'incidents' ? (id === 'new' ? <CreateIncidentPage /> : id ? <IncidentPage id={id} /> : <ResourcePage resource="incidents" />)
      : section === 'approvals' ? (id && parts[2] ? <ApprovalPage incidentId={id} approvalId={parts[2]} /> : <ResourcePage resource="approvals" />)
      : section === 'knowledge' ? (id ? <DocumentPage id={id} /> : <KnowledgePage />)
      : section === 'operations' ? <OperationsPage /> : section === 'memory' ? <ResourcePage resource="memories" />
      : section === 'automations' ? <ResourcePage resource="automations" /> : section === 'jobs' ? <JobsPage />
      : section === 'mcp' ? <McpPage /> : section === 'quality' ? <QualityPage /> : section === 'system' ? <SystemPage />
      : section === 'developer' ? <DeveloperPage /> : section === 'settings' ? <SettingsPage />
      : <div className="state-panel"><h1>Page not found</h1><a href="/app">Return to overview</a></div>;
    content = <Session.Provider value={{ me: auth.data, organizationId: selectedOrganization, role: membership.role, workspace: workspace.data, backendOrigin, uploadLimitBytes, notify: setMessage }}>
      {workspace.error && <div className="workspace-connection-banner" role="status"><div><strong>Workspace metadata is unavailable</strong><p>{workspace.error.message}</p></div><button className="btn secondary" onClick={workspace.refresh}>Retry</button></div>}
      {page}
    </Session.Provider>;
  }

  return <div className="dashboard">
    <aside className={`workspace-sidebar ${mobile ? 'visible' : ''}`}>
      <div className="sidebar-brand"><a href="/"><span className="sidebar-logo"><BrainCircuit size={22}/></span><strong>TraceOps<span>INTELLIGENCE WORKSPACE</span></strong></a><button aria-label="Close navigation" className="mobile-only" onClick={() => setMobile(false)}><X size={18} /></button></div>
      <label className="workspace-selector"><span>WORKSPACE</span><select value={selectedOrganization} disabled={!membership} onChange={event => selectOrganization(event.target.value)} aria-label="Selected organization">{!auth.data?.memberships.length && <option value="">{auth.loading ? 'Connecting…' : 'Select a workspace'}</option>}{auth.data?.memberships.map(m => <option key={m.organization_id} value={m.organization_id}>{m.organization_id === selectedOrganization && workspace.data ? workspace.data.name : `Organization ${m.organization_id.slice(0, 8)}`}</option>)}</select><small>{membership ? `${membership.role} access` : 'Checking workspace access'} <ChevronDown size={12} /></small></label>
      {can(membership?.role,'create')&&<a className="sidebar-create" href="/app/incidents/new"><Plus size={15}/> New investigation <ArrowUpRight size={14}/></a>}
      {navigation.map(group => <div className="navigation-group" key={group.group}><span>{group.group}</span>{group.items.map(([label, path, Icon]) => <button key={path} className={section === path ? 'current' : ''} onClick={() => navigate(path)} aria-current={section === path ? 'page' : undefined}><Icon size={16} /><span>{label}</span>{section === path && <i />}</button>)}</div>)}
      <div className="sidebar-account"><div className="avatar">{auth.data ? auth.data.user.full_name.split(' ').map(n => n[0]).slice(0, 2).join('') : '◈'}</div><div><strong>{auth.data?.user.full_name ?? (auth.loading ? 'Loading account…' : 'Account unavailable')}</strong><small>{auth.data?.user.email ?? 'Your secure workspace'}</small></div><LogoutButton /></div>
    </aside>
    {mobile && <button className="sidebar-backdrop" aria-label="Close navigation" onClick={() => setMobile(false)} />}
    <div className="workspace-main"><header className="workspace-topbar"><div><button className="mobile-only" aria-label="Open navigation" onClick={() => setMobile(true)}><Menu size={20} /></button><span className="topbar-workspace-label"><Shield size={12}/> Workspace</span><span className="breadcrumb-slash">/</span><strong>{name}</strong></div><div className="topbar-actions"><button className="global-search" onClick={() => {setSearchOpen(true);searchDialog.current?.showModal();}}><Search size={14} /><span>Search incidents</span><kbd>⌘ K</kbd></button><a href="/">Product website <ArrowUpRight size={12}/></a></div></header>
      <main className="workspace-content" key={selectedOrganization + pathname}>{content}{children}</main>
      <footer className="workspace-footer"><span>TraceOps / Evidence · Oversight · Follow-through</span><span>{workspace.data?.environment ?? 'Backend workspace'} · Internal-ledger refund simulation</span></footer>
    </div>
    <dialog ref={searchDialog} className="workspace-dialog command-search-dialog" aria-label="Search incidents" onClose={()=>setSearchOpen(false)}><IncidentSearch key={selectedOrganization} active={searchOpen} organizationId={selectedOrganization} onClose={()=>searchDialog.current?.close()} onNavigate={path=>{searchDialog.current?.close();router.push(path);}}/></dialog>
    {message && <div className="toast" role="status">{message}<button aria-label="Dismiss notification" onClick={() => setMessage('')}>×</button></div>}
  </div>;
}
