import assert from 'node:assert/strict';
import {test} from 'node:test';
import {resolutionRequestSchema, resolutionOutcomes} from '../lib/product/incident-resolution.ts';

const valid = {
  outcome: 'no_issue_found',
  reason: '  Checked the ledger and found one settled payment.  ',
  customer_message: '  We reviewed the payment records and found one settled payment.  ',
  next_steps: '  Contact support if another settled payment appears.  ',
};

test('every offered outcome can be saved with complete customer context', () => {
  for (const [outcome] of resolutionOutcomes) {
    const request = resolutionRequestSchema.parse({...valid, outcome});
    assert.equal(request.reason, valid.reason.trim());
    assert.equal(request.customer_message, valid.customer_message.trim());
    assert.equal(request.next_steps, valid.next_steps.trim());
  }
});

test('unsupported actions and incomplete explanations cannot close an incident', () => {
  assert.equal(resolutionRequestSchema.safeParse({...valid, outcome: 'refund_executed'}).success, false);
  for (const field of ['reason', 'customer_message', 'next_steps']) {
    assert.equal(resolutionRequestSchema.safeParse({...valid, [field]: ' '.repeat(30)}).success, false);
  }
});

test('field lengths match the backend request limits', () => {
  for (const [field, length] of [['reason', 1000], ['customer_message', 1000], ['next_steps', 500]] as const) {
    assert.equal(resolutionRequestSchema.safeParse({...valid, [field]: 'a'.repeat(length)}).success, true);
    assert.equal(resolutionRequestSchema.safeParse({...valid, [field]: 'a'.repeat(length + 1)}).success, false);
  }
});
