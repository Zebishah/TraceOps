import {ApiError,api} from './client.ts';
import {voiceTranscriptionSchema} from './voice-contracts.ts';
export const SPEECH_MAX_CHARACTERS=200;
export const MAX_SPEECH_BYTES=4*1024*1024;
export function validateIncidentAudio(file:{name:string;size:number},limit:number,containers:readonly string[]):string|null {
 if(!file.size)return 'This audio file is empty. Choose another recording.';
 if(file.size>limit)return `This file is too large. The upload limit is ${(limit/1024/1024).toFixed(0)} MB. Choose a shorter recording.`;
 const extension=file.name.split('.').pop()?.toLowerCase();
 if(!extension||!containers.includes(extension==='mp4'?'m4a':extension))return 'Choose WAV, WebM, Ogg, FLAC, MP3, or M4A audio.';
 return null;
}
export async function requestTranscription(organizationId:string,file:File,language:string,signal:AbortSignal){
 const body=new FormData();body.set('file',file);if(language)body.set('language',language);
 return api(`organizations/${organizationId}/voice/transcriptions`,voiceTranscriptionSchema,{method:'POST',body,signal});
}
export function speechText(value:string):string {
 const text=value.trim();
 if(!text||Array.from(text).length>SPEECH_MAX_CHARACTERS)throw new Error('Choose a spoken excerpt between 1 and 200 characters.');
 return text;
}
export function isWave(bytes:Uint8Array):boolean {
 return bytes.length>=12&&String.fromCharCode(...bytes.slice(0,4))==='RIFF'&&String.fromCharCode(...bytes.slice(8,12))==='WAVE';
}
export async function requestSpeech(organizationId:string,text:string,signal:AbortSignal):Promise<Blob>{
 const response=await fetch(`/api/backend/organizations/${organizationId}/voice/speech`,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:speechText(text)}),signal});
 if(!response.ok){let detail=`Speech request failed (${response.status})`;try{const data=await response.json();if(typeof data==='object'&&data!==null&&'detail' in data&&typeof data.detail==='string')detail=data.detail;}catch{}throw new ApiError(detail,response.status,response.headers.get('x-request-id'));}
 if(!(response.headers.get('content-type')??'').includes('audio/wav'))throw new Error('The server did not return WAV audio.');
 const bytes=new Uint8Array(await response.arrayBuffer());
 if(bytes.length>MAX_SPEECH_BYTES||!isWave(bytes))throw new Error('The server returned invalid or oversized audio.');
 return new Blob([bytes],{type:'audio/wav'});
}
