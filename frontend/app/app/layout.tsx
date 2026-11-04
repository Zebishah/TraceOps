import type { ReactNode } from 'react';
import { frontendUploadLimit, backendOrigin } from '@/lib/product/backend-config';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { WorkspaceApp } from '@/components/workspace/workspace-app';
import { SESSION_COOKIE } from '@/lib/product/proxy-policy';

export const dynamic = 'force-dynamic';

export default async function WorkspaceLayout({ children }: { children: ReactNode }) {
  if (!(await cookies()).get(SESSION_COOKIE)) redirect('/login');
  let origin: string | null = null;
  try { origin = backendOrigin(process.env.OPSPILOT_BACKEND_URL); } catch { /* The connection panel reports missing configuration. */ }
  return <WorkspaceApp backendOrigin={origin} uploadLimitBytes={frontendUploadLimit(process.env.VERCEL)}>{children}</WorkspaceApp>;
}
