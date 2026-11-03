import assert from 'node:assert/strict';
import test from 'node:test';
import { workflowStageStates, savedResultLabel } from '../lib/product/workflow-view.ts';

test('queued work never implies retrieved evidence or completed resolution', () => {
  assert.deepEqual(workflowStageStates({incidentStatus:'investigating',jobStatus:'queued',hasResult:false}), {investigation:'active',evidence:'waiting',review:'waiting',outcome:'waiting'});
});
test('a successful investigation pauses at an actual human approval gate', () => {
  const states=workflowStageStates({incidentStatus:'awaiting_approval',jobStatus:'succeeded',hasResult:true,approvalRequired:true,approvalStatus:'pending'});
  assert.equal(states.investigation,'done');assert.equal(states.review,'review');assert.equal(states.outcome,'waiting');
});
test('executed action does not imply the incident has been resolved', () => {
  const states=workflowStageStates({incidentStatus:'investigating',jobStatus:'succeeded',hasResult:true,approvalRequired:true,approvalStatus:'executed'});
  assert.equal(states.review,'done');assert.equal(states.outcome,'waiting');
  assert.equal(savedResultLabel(false,true,'executed'),'Approved action executed');
});
test('no-action and rejected workflows retain their distinct outcomes', () => {
  assert.equal(workflowStageStates({incidentStatus:'resolved',hasResult:true,approvalRequired:false}).review,'not-required');
  assert.equal(workflowStageStates({incidentStatus:'resolved',hasResult:true,approvalRequired:false}).outcome,'done');
  assert.equal(workflowStageStates({incidentStatus:'investigating',hasResult:true,approvalRequired:true,approvalStatus:'rejected'}).review,'failed');
  assert.equal(savedResultLabel(true,false),'Customer context needed');
});
