import type { Metadata } from 'next';
import { AuthForm } from '@/components/workspace/auth-form';

export const metadata: Metadata = {
  title: 'Verify your email', robots: { index: false, follow: false }, referrer: 'no-referrer',
};
export default function Page() { return <AuthForm verification />; }
