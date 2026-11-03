import assert from 'node:assert/strict';
import test from 'node:test';
import { classificationConfidenceLabel, investigationSchema } from '../lib/product/contracts.ts';

const investigation = {
  incident_id: 'incident', workflow_thread_id: 'thread', status: 'investigating',
  category: 'payment', priority: 'high', classification_confidence: null,
  approval_required: false, approval_request_id: null, needs_more_information: false,
  clarification_question: null, analysis: null, recommended_action: null,
  retrieval_query: 'duplicate charge', evidence: [], similar_memories: [],
  tool_results: [], memory_id: null, memory_indexed: false,
};

test('unavailable confidence is accepted and displayed explicitly', () => {
  const parsed = investigationSchema.parse(investigation);
  assert.equal(parsed.classification_confidence, null);
  assert.equal(classificationConfidenceLabel(parsed.classification_confidence), 'Unavailable');
});

test('existing numeric confidence keeps its display and bounds', () => {
  assert.equal(classificationConfidenceLabel(0), '0%');
  assert.equal(classificationConfidenceLabel(0.98), '98%');
  assert.equal(investigationSchema.parse({ ...investigation, classification_confidence: 0.98 }).classification_confidence, 0.98);
  assert.equal(investigationSchema.safeParse({ ...investigation, classification_confidence: 2 }).success, false);
});
