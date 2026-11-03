import test from 'node:test';
import assert from 'node:assert/strict';
import { backendOrigin } from '../lib/product/backend-config.ts';

test('accepts a backend root or API base and produces exactly one origin', () => {
  assert.equal(backendOrigin(' https://backend.example/ '), 'https://backend.example');
  assert.equal(backendOrigin('https://backend.example/api/v1/'), 'https://backend.example');
  assert.equal(backendOrigin('http://127.0.0.1:8000'), 'http://127.0.0.1:8000');
  assert.equal(backendOrigin('http://localhost:8000/'), 'http://localhost:8000');
});
test('requires explicit configuration and rejects ambiguous or unsafe origins', () => {
  for (const value of [undefined, '', 'backend.example', 'https://backend.example/docs', 'https://user:secret@backend.example', 'https://backend.example/?token=secret', 'https://backend.example/#section', 'http://public.example', 'file:///tmp/backend', '//public.example']) {
    assert.throws(() => backendOrigin(value));
  }
});
