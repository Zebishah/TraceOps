import { z } from 'zod';

const pendingVerificationSchema = z.object({ email: z.string().email().max(320), resendAt: z.number().nonnegative() });
const key = 'opspilot.pending-verification';
export type PendingVerification = z.infer<typeof pendingVerificationSchema>;

// Only the address and resend timer survive a reload. Never store passwords or codes.
export function rememberVerification(email: string, resendAt = 0): void {
  try { window.sessionStorage.setItem(key, JSON.stringify({ email, resendAt })); } catch { /* The current screen still works without storage. */ }
}
export function readVerification(): PendingVerification | null {
  try {
    const result = pendingVerificationSchema.safeParse(JSON.parse(window.sessionStorage.getItem(key) ?? 'null'));
    return result.success ? result.data : null;
  } catch { return null; }
}
export function clearVerification(): void {
  try { window.sessionStorage.removeItem(key); } catch { /* Storage may be disabled. */ }
}
