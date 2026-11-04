import test from 'node:test';
import assert from 'node:assert/strict';
import {isWave,speechText,requestSpeech} from '../lib/product/voice.ts';
import {frontendUploadLimit} from '../lib/product/backend-config.ts';
import {allowedBackendPath} from '../lib/product/proxy-policy.ts';
const org='d5d2a37c-5538-4783-8f42-a285d8534b7a';
test('voice proxy accepts only the three scoped operations',()=>{for(const name of ['capabilities','transcriptions','speech'])assert.equal(allowedBackendPath(`organizations/${org}/voice/${name}`),true);for(const path of ['voice/speech',`organizations/${org}/voice/admin`,`organizations/not-a-uuid/voice/speech`])assert.equal(allowedBackendPath(path),false);});
test('spoken text is validated without silently truncating',()=>{assert.equal(speechText('  short brief  '),'short brief');assert.equal(speechText('a'.repeat(200)).length,200);assert.equal(speechText('😀'.repeat(200)),'😀'.repeat(200));assert.throws(()=>speechText('a'.repeat(201)));assert.throws(()=>speechText('   '));});
test('WAV signature requires RIFF and WAVE',()=>{assert.equal(isWave(new TextEncoder().encode('RIFF0000WAVEdata')),true);assert.equal(isWave(new TextEncoder().encode('RIFF0000HTMLdata')),false);assert.equal(isWave(new Uint8Array(4)),false);});
test('host upload cap leaves multipart headroom on Vercel',()=>{assert.equal(frontendUploadLimit('1'),4*1024*1024);assert.equal(frontendUploadLimit(undefined),10*1024*1024);});
test('speech client rejects non-audio and preserves provider errors',async context=>{context.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({detail:'Voice is disabled'}),{status:503,headers:{'content-type':'application/json'}}));await assert.rejects(requestSpeech(org,'Brief',new AbortController().signal),/Voice is disabled/);context.mock.restoreAll();context.mock.method(globalThis,'fetch',async()=>new Response('not wave',{headers:{'content-type':'audio/wav'}}));await assert.rejects(requestSpeech(org,'Brief',new AbortController().signal),/invalid or oversized/);});

test('audio intake respects the effective host cap and backend formats',async()=>{
 const {validateIncidentAudio}=await import('../lib/product/voice.ts');
 const limit=4*1024*1024;const formats=['wav','webm','m4a'];
 assert.equal(validateIncidentAudio({name:'brief.WAV',size:limit},limit,formats),null);
 assert.equal(validateIncidentAudio({name:'brief.mp4',size:512},limit,formats),null);
 assert.match(validateIncidentAudio({name:'brief.wav',size:limit+1},limit,formats)??'',/too large/);
 assert.match(validateIncidentAudio({name:'brief.wav',size:0},limit,formats)??'',/empty/);
 assert.match(validateIncidentAudio({name:'brief.txt',size:100},limit,formats)??'',/Choose WAV/);
 assert.notEqual(validateIncidentAudio({name:'brief.webm',size:100},limit,['wav']),null);
});
test('transcription uses scoped multipart, a cancellable request and explicit confirmation',async context=>{
 const {requestTranscription}=await import('../lib/product/voice.ts');const controller=new AbortController();
 context.mock.method(globalThis,'fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{
  assert.equal(input,`/api/backend/organizations/${org}/voice/transcriptions`);assert.equal(init?.method,'POST');assert.equal(init?.signal,controller.signal);assert.equal(init?.credentials,'same-origin');assert.equal(init?.cache,'no-store');
  assert.ok(init?.body instanceof FormData);assert.equal(init.body.get('language'),'ur');assert.equal((init.body.get('file') as File).name,'brief.wav');assert.equal(new Headers(init.headers).has('content-type'),false);
  return Response.json({text:'  Two charges reported.  ',model:'whisper-large-v3-turbo',requires_confirmation:true});
 });
 const result=await requestTranscription(org,new File(['RIFF0000WAVE'], 'brief.wav',{type:'audio/wav'}),'ur',controller.signal);
 assert.equal(result.text,'Two charges reported.');assert.equal(result.requires_confirmation,true);
});
test('transcription detects disabled backend and invalid response contracts',async context=>{
 const {requestTranscription}=await import('../lib/product/voice.ts');const file=new File(['audio'],'brief.wav');
 context.mock.method(globalThis,'fetch',async()=>Response.json({detail:'Voice is disabled'},{status:503}));
 await assert.rejects(requestTranscription(org,file,'',new AbortController().signal),/Voice is disabled/);
 context.mock.restoreAll();context.mock.method(globalThis,'fetch',async()=>Response.json({text:'Unreviewed',model:'whisper',requires_confirmation:false}));
 await assert.rejects(requestTranscription(org,file,'',new AbortController().signal),/contract/);
});
