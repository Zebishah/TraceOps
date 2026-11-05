import { cookies } from 'next/headers';
import { sameRequestOrigin, SESSION_COOKIE } from '@/lib/product/proxy-policy';
export async function DELETE(request: Request) {
  if (!sameRequestOrigin(request)) return Response.json({ detail: 'Request origin rejected' }, { status: 403, headers: { 'Cache-Control': 'no-store' } });
  (await cookies()).set(SESSION_COOKIE, '', {
    path: '/', httpOnly: true, sameSite: 'strict', maxAge: 0, expires: new Date(0),
    secure: process.env.NODE_ENV === 'production' || new URL(request.url).protocol === 'https:',
  });
  return Response.json({ signed_out: true }, { headers: { 'Cache-Control': 'no-store' } });
}
