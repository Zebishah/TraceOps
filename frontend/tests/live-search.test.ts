import assert from 'node:assert/strict';
import test from 'node:test';
import {createLiveSearch} from '../lib/product/live-search.ts';

test('typing a burst performs one search after the pause',context=>{
  context.mock.timers.enable({apis:['setTimeout']});
  const calls:string[]=[];const search=createLiveSearch(value=>calls.push(value));
  search.change('d');context.mock.timers.tick(200);search.change('du');context.mock.timers.tick(200);search.change('duplicate');
  context.mock.timers.tick(349);assert.deepEqual(calls,[]);context.mock.timers.tick(1);assert.deepEqual(calls,['duplicate']);
});
test('Enter flushes immediately and cancels the pending duplicate',context=>{
  context.mock.timers.enable({apis:['setTimeout']});const calls:string[]=[];const search=createLiveSearch(value=>calls.push(value));
  search.change(' payment ');search.submit();context.mock.timers.tick(1000);assert.deepEqual(calls,['payment']);
});
test('clearing resets immediately and removes the previous scheduled query',context=>{
  context.mock.timers.enable({apis:['setTimeout']});const calls:string[]=[];const search=createLiveSearch(value=>calls.push(value));
  search.change('stale');search.change('');context.mock.timers.tick(1000);assert.deepEqual(calls,['']);
});
test('leaving a search cancels pending work',context=>{
  context.mock.timers.enable({apis:['setTimeout']});const calls:string[]=[];const search=createLiveSearch(value=>calls.push(value));
  search.change('previous workspace');search.cancel();context.mock.timers.tick(1000);assert.deepEqual(calls,[]);
});
