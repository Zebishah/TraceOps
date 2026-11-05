import test from 'node:test';
import assert from 'node:assert/strict';
import { voiceCapabilitiesSchema, voiceTranscriptionSchema } from '../lib/product/voice-contracts.ts';

test('frontend accepts disabled voice without assuming provider readiness', () => {
  const parsed = voiceCapabilitiesSchema.parse({
    enabled: false, speech_enabled: false, transcription_model: 'whisper-large-v3-turbo',
    max_audio_bytes: 10485760, requests_per_minute: 10, supported_containers: ['webm', 'wav'],
    max_speech_characters: 200, requires_confirmation: true,
  });
  assert.equal(parsed.enabled, false);
});

test('frontend requires real text and explicit human confirmation', () => {
  const response = {text: 'Customer reports two charges.', model: 'whisper-large-v3-turbo', requires_confirmation: true};
  assert.equal(voiceTranscriptionSchema.parse(response).text, response.text);
  assert.equal(voiceTranscriptionSchema.safeParse({...response, text: '   '}).success, false);
  assert.equal(voiceTranscriptionSchema.safeParse({...response, requires_confirmation: false}).success, false);
});

test('auto detection reports language and uncertainty while legacy responses remain accepted', () => {
  const result = voiceTranscriptionSchema.parse({ text: 'Hello, hello.', model: 'whisper-large-v3', requires_confirmation: true, detected_language: 'english', warning: 'Check the detected language for this short clip.' });
  assert.equal(result.detected_language, 'english');
  assert.match(result.warning ?? '', /short clip/);
});
