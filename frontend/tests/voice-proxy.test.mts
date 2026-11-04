import test from 'node:test';
import assert from 'node:assert/strict';
import { isVoiceSpeechPath, MAX_SPEECH_RESPONSE_BYTES, proxyVoiceSpeechResponse } from '../lib/product/voice-proxy.ts';
import { allowedBackendPath } from '../lib/product/proxy-policy.ts';

const org = 'd5d2a37c-5538-4783-8f42-a285d8534b7a';
const wav = new TextEncoder().encode('RIFF0000WAVEfmt data');

test('permits only the three tenant voice paths', () => {
  for (const operation of ['capabilities', 'transcriptions', 'speech']) {
    assert.equal(allowedBackendPath(`organizations/${org}/voice/${operation}`), true);
  }
  for (const path of [`organizations/${org}/voice/admin`, 'organizations/not-a-uuid/voice/speech',
    `organizations/${org}/voice/speech/extra`, `organizations/${org}/voice/%2fspeech`, 'classify']) {
    assert.equal(allowedBackendPath(path), false);
  }
  assert.equal(isVoiceSpeechPath(`organizations/${org}/voice/speech`), true);
  assert.equal(isVoiceSpeechPath(`organizations/${org}/voice/transcriptions`), false);
});

test('forwards WAV as audio without exposing arbitrary upstream headers', async () => {
  const upstream = new Response(wav, {headers: {'Content-Type': 'audio/wav', 'x-request-id': 'request',
    'set-cookie': 'secret-cookie', 'Content-Disposition': 'attachment; filename="untrusted.exe"'}});
  const result = await proxyVoiceSpeechResponse(upstream);
  assert.equal(result.status, 200);
  assert.equal(result.headers.get('content-type'), 'audio/wav');
  assert.equal(result.headers.get('cache-control'), 'no-store');
  assert.equal(result.headers.get('x-request-id'), 'request');
  assert.equal(result.headers.get('set-cookie'), null);
  assert.match(result.headers.get('content-disposition') ?? '', /opspilot-speech.wav/);
  assert.deepEqual(new Uint8Array(await result.arrayBuffer()), wav);
});

test('rejects false audio content or unexpected successful status', async () => {
  for (const response of [
    new Response('not WAV', {headers: {'Content-Type': 'audio/wav'}}),
    new Response(wav, {headers: {'Content-Type': 'text/html'}}),
    new Response(wav, {status: 201, headers: {'Content-Type': 'audio/wav'}}),
  ]) assert.equal((await proxyVoiceSpeechResponse(response)).status, 502);
});

test('rejects declared oversize before consuming the response', async () => {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({cancel() {cancelled = true;}});
  const result = await proxyVoiceSpeechResponse(new Response(body, {headers: {
    'Content-Type': 'audio/wav', 'Content-Length': String(MAX_SPEECH_RESPONSE_BYTES + 1),
  }}));
  assert.equal(result.status, 502);
  assert.equal(cancelled, true);
});

test('bounds actual chunked bytes even when no size is declared', async () => {
  let chunk = 0;
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {controller.enqueue(new Uint8Array(1024 * 1024)); chunk += 1;},
    cancel() {cancelled = true;},
  });
  const result = await proxyVoiceSpeechResponse(new Response(body, {headers: {'Content-Type': 'audio/wav'}}));
  assert.equal(result.status, 502);
  assert.equal(cancelled, true);
  assert.ok(chunk <= 7);
});
