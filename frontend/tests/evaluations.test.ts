import test from 'node:test';
import assert from 'node:assert/strict';
import { formatEvaluationRate, publishedEvaluationSchema, suiteDescription } from '../lib/product/evaluations.ts';

function report() {
  return {
    generated_at: 1_793_685_600,
    report: {
      passed: true, total_suites: 1, passed_suites: 1, failed_suites: 0,
      suites: [{
        suite_name: 'incident_classification', total_cases: 8, passed_cases: 7, failed_cases: 1,
        pass_rate: 0.875, threshold: 0.875, meets_threshold: true,
        cases: Array.from({ length: 8 }, (_, index) => ({
          case_id: `classification_${index}`, status: index === 7 ? 'failed' : 'passed',
          checks: [{ name: 'category', passed: index !== 7, details: index === 7 ? 'expected=payment, actual=access' : null }],
        })),
      }],
    },
  };
}

test('a suite can meet its threshold while individual cases fail', () => {
  const parsed = publishedEvaluationSchema.parse(report());
  assert.equal(parsed.report.passed, true);
  assert.equal(parsed.report.suites[0].failed_cases, 1);
  assert.equal(parsed.report.suites[0].cases[7].status, 'failed');
  assert.equal(formatEvaluationRate(parsed.report.suites[0].threshold), '87.5%');
});

test('invalid API counts, pass rates, and statuses cannot produce misleading charts', () => {
  const negative = report(); negative.report.suites[0].failed_cases = -1;
  assert.equal(publishedEvaluationSchema.safeParse(negative).success, false);
  const inflated = report(); inflated.report.suites[0].pass_rate = 4;
  assert.equal(publishedEvaluationSchema.safeParse(inflated).success, false);
  const unknownStatus = report(); unknownStatus.report.suites[0].cases[0].status = 'unknown';
  assert.equal(publishedEvaluationSchema.safeParse(unknownStatus).success, false);
  const invalidDate = report(); invalidDate.generated_at = Infinity;
  assert.equal(publishedEvaluationSchema.safeParse(invalidDate).success, false);
});

test('suite names are readable and future suites have a safe fallback', () => {
  assert.equal(suiteDescription('hitl_dangerous_action_safety').title, 'Human-approval safety');
  assert.equal(suiteDescription('new_safety_suite').title, 'New safety suite');
});
