export type StageState = 'done' | 'active' | 'failed' | 'review' | 'waiting' | 'not-required';

export function workflowStageStates(input: {
  incidentStatus: string;
  jobStatus?: string | null;
  hasResult: boolean;
  approvalRequired?: boolean;
  approvalStatus?: string | null;
}): { investigation: StageState; evidence: StageState; review: StageState; outcome: StageState } {
  const { incidentStatus, jobStatus, hasResult, approvalRequired, approvalStatus } = input;
  return {
    investigation: jobStatus === 'succeeded' ? 'done' : jobStatus === 'failed' ? 'failed' : jobStatus === 'queued' || jobStatus === 'processing' ? 'active' : 'waiting',
    evidence: hasResult ? 'done' : 'waiting',
    review: approvalStatus === 'executed' || approvalStatus === 'approved' ? 'done'
      : approvalStatus === 'rejected' || approvalStatus === 'failed' ? 'failed'
      : approvalStatus === 'pending' || (hasResult && approvalRequired) ? 'review'
      : approvalStatus === 'superseded' || (hasResult && approvalRequired === false) ? 'not-required' : 'waiting',
    // A completed investigation or execution job does not establish incident resolution.
    outcome: incidentStatus === 'resolved' ? 'done' : 'waiting',
  };
}

export function savedResultLabel(needsMoreInformation: boolean, approvalRequired: boolean, approvalStatus?: string | null): string {
  if (approvalStatus === 'executed') return 'Approved action executed';
  if (approvalStatus === 'approved') return 'Approved · execution tracked separately';
  if (approvalStatus === 'rejected') return 'Proposed action rejected';
  if (approvalStatus === 'failed') return 'Action needs attention';
  if (approvalStatus === 'superseded') return 'Proposal superseded';
  if (needsMoreInformation) return 'Customer context needed';
  return approvalRequired ? 'Ready for human review' : 'Investigation available';
}
