import { cookies } from 'next/headers';
import { sameOrigin, SESSION_COOKIE } from '@/lib/product/proxy-policy';
export async function DELETE(request: Request) {
  if (!sameOrigin(request.url, request.headers.get('origin'))) return Response.json({ detail: 'Request origin rejected' }, { status: 403 });
  (await cookies()).delete(SESSION_COOKIE);
  return Response.json({ signed_out: true }, { headers: { 'Cache-Control': 'no-store' } });
}
