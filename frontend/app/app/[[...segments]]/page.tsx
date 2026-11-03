import {cookies} from 'next/headers';
import {redirect} from 'next/navigation';
import {WorkspaceApp} from '@/components/workspace/workspace-app';
import {SESSION_COOKIE} from '@/lib/product/proxy-policy';
export const dynamic='force-dynamic';
export default async function Page(){if(!(await cookies()).get(SESSION_COOKIE))redirect('/login');return <WorkspaceApp/>;}
