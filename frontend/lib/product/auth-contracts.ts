import { z } from 'zod';

export const credentialsSchema = z.object({ email: z.string().email().max(320), password: z.string().min(1).max(128) });
export const registrationSchema = credentialsSchema.extend({
  password: z.string().min(8).max(128), full_name: z.string().trim().min(1).max(200),
  organization_name: z.string().trim().min(1).max(200),
  organization_slug: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/).max(100),
});
export const verificationRequestSchema = z.object({ email: z.string().email().max(320) });
export const verificationConfirmSchema = z.object({ token: z.string().regex(/^[A-Za-z0-9_-]{43}$/) });
export const verificationCodeSchema = verificationRequestSchema.extend({ code: z.string().regex(/^[0-9]{6}$/) });
export const registrationResponseSchema = z.object({
  id: z.string(), verification_required: z.boolean().optional().default(false),
  verification_email_sent: z.boolean().optional().default(false),
});
export const verificationRequiredSchema = z.object({
  code: z.literal('email_verification_required'), message: z.string(), email: z.string().email(),
  verification_email_sent: z.boolean().optional(),
});
export function anonymousAuthPath(path: string): boolean {
  return ['auth/login', 'auth/register', 'auth/verification/request', 'auth/verification/confirm', 'auth/verification/code'].includes(path);
}
export function authInputSchema(path: string) {
  switch (path) {
    case 'auth/login': return credentialsSchema;
    case 'auth/register': return registrationSchema;
    case 'auth/verification/request': return verificationRequestSchema;
    case 'auth/verification/confirm': return verificationConfirmSchema;
    case 'auth/verification/code': return verificationCodeSchema;
    default: return null;
  }
}
/** Read a fragment only: verification tokens must not travel in URL query strings. */
export function verificationTokenFromFragment(fragment: string): string | null {
  if (!fragment.startsWith('#')) return null;
  const values = new URLSearchParams(fragment.slice(1));
  if (values.getAll('token').length !== 1) return null;
  const parsed = verificationConfirmSchema.safeParse({ token: values.get('token') });
  return parsed.success ? parsed.data.token : null;
}
