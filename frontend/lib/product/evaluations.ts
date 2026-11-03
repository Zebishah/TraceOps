import { z } from 'zod';

const count = z.number().int().nonnegative();
const fraction = z.number().finite().min(0).max(1);
export const evaluationCheckSchema = z.object({
  name: z.string(),
  passed: z.boolean(),
  details: z.string().nullable().optional(),
});
export const evaluationCaseSchema = z.object({
  case_id: z.string(),
  status: z.enum(['passed', 'failed']),
  checks: z.array(evaluationCheckSchema),
});
export const evaluationSuiteSchema = z.object({
  suite_name: z.string(),
  total_cases: count,
  passed_cases: count,
  failed_cases: count,
  pass_rate: fraction,
  threshold: fraction,
  meets_threshold: z.boolean(),
  cases: z.array(evaluationCaseSchema),
});
export const evaluationReportSchema = z.object({
  passed: z.boolean(),
  total_suites: count,
  passed_suites: count,
  failed_suites: count,
  suites: z.array(evaluationSuiteSchema),
});
export const publishedEvaluationSchema = z.object({
  report: evaluationReportSchema,
  generated_at: z.number().finite().nonnegative().max(8_640_000_000_000),
});
export type EvaluationReportData = z.infer<typeof evaluationReportSchema>;
export type EvaluationSuite = z.infer<typeof evaluationSuiteSchema>;
export type PublishedEvaluation = z.infer<typeof publishedEvaluationSchema>;

const labels: Record<string, { title: string; description: string }> = {
  duplicate_payment_detection: { title: 'Duplicate-payment detection', description: 'Matching charges, timing windows, providers, and ambiguous payment candidates.' },
  tool_selection: { title: 'Tool selection', description: 'The right operational tools, arguments, and investigation sequence.' },
  hitl_dangerous_action_safety: { title: 'Human-approval safety', description: 'Approval requirements and validation of sensitive action proposals.' },
  incident_classification: { title: 'Incident classification', description: 'Category, priority, confidence, and resistance to injected instructions.' },
  document_retrieval: { title: 'Document retrieval', description: 'Relevant evidence, expected terms, and reranked result ordering.' },
  recommendation_groundedness: { title: 'Recommendation groundedness', description: 'Evidence-aware recommendations and safe next steps when facts are uncertain.' },
};
export function readableEvaluationName(name: string): string {
  const text = name.replaceAll('_', ' ').trim();
  return text ? text[0].toUpperCase() + text.slice(1) : 'Unnamed check';
}
export function suiteDescription(name: string): { title: string; description: string } {
  return labels[name] ?? { title: readableEvaluationName(name), description: 'Published checks and configured acceptance criteria for this evaluation suite.' };
}
export function formatEvaluationRate(value: number): string {
  return `${new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1 }).format(value * 100)}%`;
}
