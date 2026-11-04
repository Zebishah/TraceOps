import test from 'node:test';
import assert from 'node:assert/strict';
import {activeTraining,checkTrainingDataset,trainingDownloadSchema,trainingCapabilitiesSchema} from '../lib/product/training.ts';
import {allowedBackendPath} from '../lib/product/proxy-policy.ts';
const org='d5d2a37c-5538-4783-8f42-a285d8534b7a';const run='0f41f7c5-f9e3-4086-a1e1-80982c6aef43';
const rows=Array.from({length:3},(_,i)=>({title:`Case ${i}`,description:`Issue ${i}`,category:'payment',priority:'high',group_id:`group-${i}`}));
test('training dataset checks byte budgets, independent groups and strict labels',()=>{
 const text=rows.map(row=>JSON.stringify(row)).join('\n');assert.deepEqual(checkTrainingDataset(text,200000),{examples:3,groups:3});
 assert.throws(()=>checkTrainingDataset(text,10),/UTF-8 bytes/);
 assert.throws(()=>checkTrainingDataset(rows.map(row=>JSON.stringify({...row,group_id:'same'})).join('\n'),200000),/independent/);
 assert.throws(()=>checkTrainingDataset(rows.map(row=>JSON.stringify({...row,category:'storage'})).join('\n'),200000),/Line 1/);
 assert.throws(()=>checkTrainingDataset('broken',200000),/valid JSON/);
});
test('proxy exposes organization controls but never the trusted worker API',()=>{
 for(const suffix of ['capabilities','runs',`runs/${run}`,`runs/${run}/cancel`,`runs/${run}/retry`,`runs/${run}/download`])assert.equal(allowedBackendPath(`organizations/${org}/training/${suffix}`),true);
 for(const path of ['internal/training/claim',`internal/training/runs/${run}/artifact`,`organizations/${org}/training/runs/${run}/approve`,`organizations/${org}/training/../internal`])assert.equal(allowedBackendPath(path),false);
});
test('training status and download validation do not invent completion or accept unsafe URLs',()=>{
 for(const value of ['queued','running','cancel_requested'])assert.equal(activeTraining(value),true);
 for(const value of ['succeeded','failed','cancelled'])assert.equal(activeTraining(value),false);
 assert.equal(trainingDownloadSchema.safeParse({url:'javascript:alert(1)',sha256:'a'.repeat(64),bytes:10,expires_in:60}).success,false);
 assert.equal(trainingDownloadSchema.safeParse({url:'https://storage.example.test/adapter.zip',sha256:'a'.repeat(64),bytes:10,expires_in:60}).success,true);
 assert.equal(trainingCapabilitiesSchema.safeParse({enabled:false}).success,false);
});
test('local HTTP compatibility uses crypto randomness for valid v4 request IDs',async()=>{
 const {newTrainingRequestId}=await import('../lib/product/training.ts');
 const fallback={getRandomValues:crypto.getRandomValues.bind(crypto)};
 const first=newTrainingRequestId(fallback);const second=newTrainingRequestId(fallback);
 assert.match(first,/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);assert.notEqual(first,second);
});
