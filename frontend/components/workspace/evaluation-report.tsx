'use client';

import { useState } from 'react';
import { Check, ChevronDown, Search, X } from 'lucide-react';
import { formatEvaluationRate, readableEvaluationName, suiteDescription, type PublishedEvaluation } from '@/lib/product/evaluations';
import './evaluation-report.css';

export function EvaluationReport({ value }: { value: PublishedEvaluation }) {
  const { report, generated_at } = value;
  const [selection, setSelection] = useState(0);
  const [filter, setFilter] = useState<'all' | 'failed'>('all');
  const [query, setQuery] = useState('');
  const suite = report.suites[selection] ?? report.suites[0];
  const totals = report.suites.reduce((sum, item) => ({
    cases: sum.cases + item.total_cases,
    passed: sum.passed + item.passed_cases,
    failed: sum.failed + item.failed_cases,
  }), { cases: 0, passed: 0, failed: 0 });
  const published = new Date(generated_at * 1000);
  const phrase = query.trim().toLowerCase().replaceAll('_', ' ');
  const cases = suite?.cases.filter(item => (filter === 'all' || item.status === 'failed') &&
    `${item.case_id} ${item.checks.map(check => `${check.name} ${check.details ?? ''}`).join(' ')}`.replaceAll('_', ' ').toLowerCase().includes(phrase)) ?? [];

  function chooseSuite(index: number) {
    setSelection(index);
    setFilter('all');
    setQuery('');
  }

  return <div className="evaluation-view">
    <section className={`evaluation-snapshot ${report.passed ? 'targets-met' : 'targets-missed'}`} aria-label="Evaluation summary">
      <div className="evaluation-snapshot-top"><div className="evaluation-run-label"><span className="evaluation-signal" />PUBLISHED EVALUATION RUN</div><time dateTime={published.toISOString()}>{published.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }) + ' UTC'}</time></div>
      <div className="evaluation-snapshot-heading"><span className="evaluation-outcome-icon" aria-hidden="true">{report.passed ? <Check size={23} /> : <X size={23} />}</span><div><h2>{report.passed ? 'Evaluation targets met.' : 'Some targets need attention.'}</h2><p>{report.passed_suites} of {report.total_suites} suites reached their configured acceptance threshold.</p></div><span className="evaluation-overall-status">{report.passed ? 'Passed' : 'Needs review'}</span></div>
      <div className="evaluation-metrics">
        <div><span>Suites meeting target</span><strong>{report.passed_suites}<small> / {report.total_suites}</small></strong><p>{report.failed_suites === 0 ? 'All published suite targets met' : `${report.failed_suites} below threshold`}</p></div>
        <div><span>Cases evaluated</span><strong>{totals.cases}</strong><p>Across {report.total_suites} evaluation suites</p></div>
        <div><span>Passed cases</span><strong>{totals.passed}</strong><p>{totals.cases ? `${formatEvaluationRate(totals.passed / totals.cases)} of evaluated cases` : 'No cases were evaluated'}</p></div>
        <div className={totals.failed ? 'evaluation-failure-metric' : ''}><span>Failed cases</span><strong>{totals.failed}</strong><p>{totals.failed ? 'Inspect the failed checks below' : 'No failed cases in this report'}</p></div>
      </div>
    </section>

    <div className="evaluation-section-heading"><div><span className="app-eyebrow">SUITE BREAKDOWN</span><h2>Inspect what was tested.</h2></div><p>Select a suite to review its cases and acceptance criteria.</p></div>
    <div className="evaluation-suite-grid" role="group" aria-label="Select an evaluation suite">
      {report.suites.map((item, index) => {
        const description = suiteDescription(item.suite_name);
        return <button type="button" key={`${item.suite_name}-${index}`} className={`evaluation-suite-card ${selection === index ? 'selected' : ''}`} onClick={() => chooseSuite(index)} aria-pressed={selection === index} aria-controls="evaluation-case-panel">
          <div className="evaluation-suite-card-top"><span className="evaluation-suite-number">{String(index + 1).padStart(2, '0')}</span><span className={`evaluation-target-badge ${item.meets_threshold ? 'met' : 'missed'}`}>{item.meets_threshold ? <Check size={11} /> : <X size={11} />}{item.meets_threshold ? 'Target met' : 'Below target'}</span></div>
          <h3>{description.title}</h3><p>{description.description}</p>
          <div className="evaluation-suite-rate"><strong>{item.total_cases ? formatEvaluationRate(item.pass_rate) : '—'}</strong><span>{item.passed_cases} / {item.total_cases} cases passed</span></div>
          <div className="evaluation-rate-track" aria-hidden="true"><span className={item.meets_threshold ? 'met' : 'missed'} style={{ width: `${item.pass_rate * 100}%` }} /><i style={{ left: `${item.threshold * 100}%` }} /></div>
          <div className="evaluation-suite-card-bottom"><span>Required: {formatEvaluationRate(item.threshold)}</span><span>{selection === index ? 'Viewing cases' : 'Inspect cases'} ↗</span></div>
        </button>;
      })}
    </div>

    {suite ? <section className="evaluation-case-panel" id="evaluation-case-panel" aria-label={`${suiteDescription(suite.suite_name).title} cases`}>
      <div className="evaluation-case-panel-heading"><div><span className="app-eyebrow">CASE RESULTS</span><h2>{suiteDescription(suite.suite_name).title}</h2><p>{suite.passed_cases} passed · {suite.failed_cases} failed · Required pass rate {formatEvaluationRate(suite.threshold)}</p></div><span className={`evaluation-target-badge ${suite.meets_threshold ? 'met' : 'missed'}`}>{suite.meets_threshold ? <Check size={13} /> : <X size={13} />}{suite.meets_threshold ? 'Acceptance target met' : 'Below acceptance target'}</span></div>
      <div className="evaluation-case-toolbar"><div className="evaluation-case-filters" role="group" aria-label="Filter cases"><button type="button" aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All cases <span>{suite.cases.length}</span></button><button type="button" aria-pressed={filter === 'failed'} onClick={() => setFilter('failed')}>Failed <span>{suite.failed_cases}</span></button></div><label className="evaluation-case-search"><Search size={15} aria-hidden="true" /><span className="sr-only">Search evaluation cases and checks</span><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search cases or checks…" /></label></div>
      <div className="evaluation-case-list" key={suite.suite_name}>
        {cases.map((item, index) => <details className="evaluation-case" key={`${item.case_id}-${index}`} open={item.status === 'failed' ? true : undefined}>
          <summary><span className={`evaluation-case-icon ${item.status}`} aria-hidden="true">{item.status === 'passed' ? <Check size={14} /> : <X size={14} />}</span><div><strong>{readableEvaluationName(item.case_id)}</strong><span>{item.checks.length} {item.checks.length === 1 ? 'check' : 'checks'}</span></div><span className={`evaluation-case-status ${item.status}`}>{item.status === 'passed' ? 'Passed' : 'Failed'}</span><ChevronDown className="evaluation-case-chevron" size={16} aria-hidden="true" /></summary>
          <div className="evaluation-checks"><table><caption className="sr-only">Checks for {readableEvaluationName(item.case_id)}</caption><thead><tr><th scope="col">Check</th><th scope="col">Result</th><th scope="col">Observed details</th></tr></thead><tbody>{item.checks.map((check, checkIndex) => <tr key={`${check.name}-${checkIndex}`}><th scope="row">{readableEvaluationName(check.name)}</th><td><span className={`evaluation-check-result ${check.passed ? 'passed' : 'failed'}`}>{check.passed ? <Check size={12} aria-hidden="true" /> : <X size={12} aria-hidden="true" />}{check.passed ? 'Passed' : 'Failed'}</span></td><td><p>{check.details ? check.details.replaceAll('\\n', '\n') : 'No additional details were recorded.'}</p></td></tr>)}</tbody></table>{item.checks.length === 0 && <p className="evaluation-empty">No individual checks were recorded for this case.</p>}</div>
        </details>)}
        {cases.length === 0 && <div className="evaluation-empty"><strong>{filter === 'failed' && !phrase ? 'No failed cases in this suite.' : 'No cases match your filters.'}</strong><p>{filter === 'failed' && !phrase ? 'Every recorded case passed. Select All cases to inspect the checks.' : 'Try another search or switch to All cases.'}</p></div>}
      </div>
      <div className="evaluation-panel-footnote">Showing {cases.length} of {suite.cases.length} recorded cases · Published evaluation snapshot</div>
    </section> : <div className="evaluation-empty"><strong>No suites were recorded.</strong><p>This published report contains no suite results.</p></div>}
  </div>;
}
