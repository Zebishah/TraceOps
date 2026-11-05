import {z} from 'zod';

export const resolutionOutcomes = [
  ['no_issue_found', 'No issue found'],
  ['already_corrected', 'Already corrected'],
  ['guidance_provided', 'Guidance provided'],
  ['resolved_externally', 'Resolved outside OpsPilot'],
] as const;

export const resolutionRequestSchema = z.object({
  outcome: z.enum(['no_issue_found', 'already_corrected', 'guidance_provided', 'resolved_externally']),
  reason: z.string().trim().min(10, 'Explain the findings and why the incident can close.').max(1000),
  customer_message: z.string().trim().min(10, 'Write a clear customer-facing explanation.').max(1000),
  next_steps: z.string().trim().min(10, 'Record the next step or explain why none is needed.').max(500),
});

export type ResolutionRequest = z.infer<typeof resolutionRequestSchema>;
