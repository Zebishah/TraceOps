import type { ReactNode } from 'react';
import { env } from 'cloudflare:workers';
import { backendOrigin } from '@/lib/product/backend-config';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { WorkspaceApp } from '@/components/workspace/workspace-app';
import { SESSION_COOKIE } from '@/lib/product/proxy-policy';

export const dynamic = 'force-dynamic';

export default async function WorkspaceLayout({ children }: { children: ReactNode }) {
  if (!(await cookies()).get(SESSION_COOKIE)) redirect('/login');
  let origin: string | null = null;
  try { origin = backendOrigin(env.OPSPILOT_BACKEND_URL); } catch { /* The connection panel reports missing configuration. */ }
  return <WorkspaceApp backendOrigin={origin}>{children}</WorkspaceApp>;
}
