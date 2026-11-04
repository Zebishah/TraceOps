'use client';
import {useEffect,useRef,useState} from 'react';
import {AudioLines,Check,FileAudio,LoaderCircle,Mic,Square,Volume2,Upload,X} from 'lucide-react';
import {voiceCapabilitiesSchema} from '@/lib/product/voice-contracts';
import {useResource} from '@/hooks/use-resource';
import {api} from '@/lib/product/client';
import {can} from '@/lib/product/contracts';
import {requestSpeech,requestTranscription,SPEECH_MAX_CHARACTERS,validateIncidentAudio} from '@/lib/product/voice';
import {useSession} from './context';
import './voice-studio.css';

export function useVoiceCapabilities(){const {organizationId,role}=useSession();return useResource(can(role,'create')?signal=>api(`organizations/${organizationId}/voice/capabilities`,voiceCapabilitiesSchema,{signal}):null,[organizationId,role]);}
const audioTypes=['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus','audio/mp4'];
const defaultContainers=['wav','webm','ogg','flac','mp3','m4a'];

/** Real microphone levels. The analyser never plays the microphone through speakers. */
function MicrophoneMeter({stream}:{stream:MediaStream|null}){
 const canvas=useRef<HTMLCanvasElement>(null);
 useEffect(()=>{
  if(!stream||!canvas.current||typeof AudioContext==='undefined')return;
  let context:AudioContext|undefined;let frame=0;let last=0;
  try{
   context=new AudioContext();const source=context.createMediaStreamSource(stream);const analyser=context.createAnalyser();analyser.fftSize=128;analyser.smoothingTimeConstant=.7;source.connect(analyser);const bins=new Uint8Array(analyser.frequencyBinCount);const surface=canvas.current;const paint=surface.getContext('2d');
   const draw=(time:number)=>{frame=requestAnimationFrame(draw);if(time-last<32||!paint)return;last=time;analyser.getByteFrequencyData(bins);paint.clearRect(0,0,640,112);paint.fillStyle='#d5b57c';for(let i=0;i<48;i++){const h=Math.max(4,bins[i]*.35);paint.beginPath();paint.roundRect(i*13+8,56-h/2,5,h,2.5);paint.fill();}};
   frame=requestAnimationFrame(draw);void context.resume().catch(()=>{});
  }catch{/* Recording remains usable when the browser cannot draw microphone levels. */}
  return()=>{cancelAnimationFrame(frame);void context?.close().catch(()=>{});};
 },[stream]);
 return <canvas ref={canvas} width={640} height={112} aria-label="Microphone audio level" role="img"/>;
}
function AudioPreview({file}:{file:File}){const audio=useRef<HTMLAudioElement>(null);useEffect(()=>{const url=URL.createObjectURL(file);const element=audio.current;if(element)element.src=url;return()=>{if(element){element.pause();element.removeAttribute('src');element.load();}URL.revokeObjectURL(url);};},[file]);return <audio ref={audio} controls preload="metadata" aria-label="Preview incident recording"/>;}
export function VoiceCapture({onConfirm}:{onConfirm:(text:string)=>void}){const {organizationId}=useSession();return <VoiceStudio key={organizationId} onConfirm={onConfirm}/>;}
function VoiceStudio({onConfirm}:{onConfirm:(text:string)=>void}){
 const {organizationId,uploadLimitBytes=10*1024*1024}=useSession();
 const [file,setFile]=useState<File|null>(null);const [text,setText]=useState('');const [model,setModel]=useState('');const [hasTranscript,setHasTranscript]=useState(false);const [confirmed,setConfirmed]=useState(false);const [language,setLanguage]=useState('');
 const [state,setState]=useState<'idle'|'permission'|'recording'|'transcribing'>('idle');const [error,setError]=useState('');const [elapsed,setElapsed]=useState(0);const [liveStream,setLiveStream]=useState<MediaStream|null>(null);
 const request=useRef<AbortController|null>(null);const recorder=useRef<MediaRecorder|null>(null);const stream=useRef<MediaStream|null>(null);const timer=useRef<ReturnType<typeof setTimeout>|null>(null);const generation=useRef(0);
 const capabilities=useVoiceCapabilities();const enabled=capabilities.data?.enabled===true;const limit=Math.min(uploadLimitBytes,capabilities.data?.max_audio_bytes??10*1024*1024);const containers=capabilities.data?.supported_containers??defaultContainers;
 useEffect(()=>()=>{generation.current++;request.current?.abort();if(timer.current)clearTimeout(timer.current);if(recorder.current){recorder.current.onstop=null;recorder.current.onerror=null;recorder.current.ondataavailable=null;if(recorder.current.state!=='inactive')recorder.current.stop();}stream.current?.getTracks().forEach(track=>track.stop());},[]);
 useEffect(()=>{if(state!=='recording')return;const start=Date.now();const interval=setInterval(()=>setElapsed(Math.min(90,Math.floor((Date.now()-start)/1000))),250);return()=>clearInterval(interval);},[state]);
 function choose(value:File|null){request.current?.abort();const issue=value?validateIncidentAudio(value,limit,containers):null;setFile(issue?null:value);setText('');setModel('');setHasTranscript(false);setConfirmed(false);setError(issue??'');setState('idle');}
 function stop(){if(recorder.current?.state==='recording')recorder.current.stop();}
 function cancel(){generation.current++;request.current?.abort();if(timer.current)clearTimeout(timer.current);stop();stream.current?.getTracks().forEach(track=>track.stop());setLiveStream(null);setState('idle');setError('');}
 async function record(){
  if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined'){setError('Recording is unavailable in this browser. Upload an audio file instead.');return;}
  const current=++generation.current;setState('permission');setError('');
  try{
   const tracks=await navigator.mediaDevices.getUserMedia({audio:true});
   if(current!==generation.current){tracks.getTracks().forEach(track=>track.stop());return;}
   stream.current=tracks;const mimeType=audioTypes.find(type=>MediaRecorder.isTypeSupported(type));const recording=new MediaRecorder(tracks,mimeType?{mimeType}:undefined);recorder.current=recording;
   const chunks:Blob[]=[];let bytes=0;let oversized=false;let failed=false;
   recording.ondataavailable=event=>{if(event.data.size){bytes+=event.data.size;if(bytes>limit){oversized=true;stop();}else chunks.push(event.data);}};
   recording.onerror=()=>{failed=true;tracks.getTracks().forEach(track=>track.stop());if(timer.current)clearTimeout(timer.current);if(current!==generation.current)return;setLiveStream(null);setError('Recording failed. Try uploading an audio file.');setState('idle');stop();};
   recording.onstop=()=>{tracks.getTracks().forEach(track=>track.stop());if(timer.current)clearTimeout(timer.current);if(current!==generation.current)return;setLiveStream(null);setState('idle');if(failed)return;if(oversized){setError('Recording reached the upload limit. Record a shorter clip.');return;}const type=recording.mimeType||chunks[0]?.type||'audio/webm';const extension=type.includes('mp4')?'m4a':type.includes('ogg')?'ogg':'webm';choose(new File(chunks,`incident-recording.${extension}`,{type}));};
   setFile(null);setText('');setHasTranscript(false);setConfirmed(false);setElapsed(0);recording.start(1000);setLiveStream(tracks);setState('recording');timer.current=setTimeout(stop,90000);
  }catch(cause){stream.current?.getTracks().forEach(track=>track.stop());if(current===generation.current){setState('idle');setLiveStream(null);setError(cause instanceof Error?cause.message:'Microphone access failed.');}}
 }
 async function transcribe(){
  if(!file)return;const issue=validateIncidentAudio(file,limit,containers);if(issue){setError(issue);return;}
  request.current?.abort();const controller=new AbortController();request.current=controller;setState('transcribing');setError('');setText('');setHasTranscript(false);setConfirmed(false);
  try{const result=await requestTranscription(organizationId,file,language,controller.signal);if(!controller.signal.aborted){setText(result.text);setModel(result.model);setHasTranscript(true);}}
  catch(cause){if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:'Transcription failed.');}
  finally{if(!controller.signal.aborted)setState('idle');}
 }
 const busy=state!=='idle';const stage=hasTranscript?2:state==='transcribing'?1:0;
 return <section className="voice-studio" aria-label="Voice incident intake">
  <div className="voice-studio-top"><span><AudioLines size={15}/> VOICE INTAKE</span><span className="voice-availability">{capabilities.loading?'Checking availability':enabled?'Backend enabled':'Unavailable'}</span></div>
  <div className="voice-studio-intro"><h3>Your voice. A clearer report.</h3><p>Speak naturally, then review the details before adding them to your incident.</p></div>
  <ol className="voice-flow">{['Capture audio','Transcribe','Review & add'].map((name,index)=><li key={name} aria-current={index===stage?'step':undefined}><span>{index<stage?<Check size={11}/>:index+1}</span>{name}</li>)}</ol>
  {capabilities.error?<p role="alert" className="notice">{capabilities.error.message} <button type="button" className="btn subtle" onClick={capabilities.refresh}>Retry voice settings</button></p>:!enabled&&!capabilities.loading&&<p className="notice">Voice is disabled on this backend. You can still type your report. An administrator can enable it in the backend configuration.</p>}
  <div className={`voice-capture-zone ${state==='recording'?'is-recording':''}`}>
   {state==='recording'?<MicrophoneMeter stream={liveStream}/>:<div className={`voice-idle-wave ${state==='transcribing'?'is-processing':''}`} aria-hidden="true">{Array.from({length:35},(_,i)=><i key={i} style={{height:8+Math.sin(i*1.35)**2*36,animationDelay:`${i*-.06}s`}}/>)}</div>}
   <div className="voice-capture-status" role="status">{state==='recording'?<><span className="voice-live-dot"/> Recording · {String(Math.floor(elapsed/60)).padStart(2,'0')}:{String(elapsed%60).padStart(2,'0')} / 01:30</>:state==='transcribing'?<><LoaderCircle size={14} className="voice-spinner"/> Transcribing your audio…</>:state==='permission'?'Waiting for microphone permission…':file?<><FileAudio size={15}/> {file.name} · {(file.size/1024).toFixed(0)} KB</>:'Record a brief or bring your own audio'}</div>
   <div className="button-row">{state==='recording'?<button type="button" className="btn primary-action" onClick={stop}><Square size={14}/> Stop recording</button>:<button type="button" className="btn primary-action" disabled={busy||!enabled} onClick={()=>void record()}><Mic size={15}/> {file?'Record again':'Start recording'}</button>}
   {!busy&&<label className={`btn secondary voice-upload ${!enabled?'voice-upload-disabled':''}`}><Upload size={14}/> Upload audio<input type="file" aria-label="Upload incident audio" accept="audio/wav,audio/webm,audio/ogg,audio/flac,audio/mpeg,audio/mp4,.wav,.webm,.ogg,.flac,.mp3,.m4a" disabled={!enabled} onChange={event=>{choose(event.target.files?.[0]??null);event.target.value='';}}/></label>}
   {(state==='permission'||state==='transcribing')&&<button type="button" className="btn secondary" onClick={cancel}><X size={14}/> Cancel</button>}</div>
   <small>90 seconds per recording · Up to {limit/1024/1024} MB · WAV, WebM, Ogg, FLAC, MP3, M4A</small>
  </div>
  {file&&<div className="voice-file-review"><AudioPreview file={file}/><div className="voice-transcribe-row"><label>Audio language<select value={language} disabled={busy} onChange={event=>{setLanguage(event.target.value);setHasTranscript(false);setConfirmed(false);}}><option value="">Detect automatically</option><option value="en">English</option><option value="ur">Urdu</option></select></label><button type="button" className="btn secondary" disabled={busy||!enabled} onClick={()=>void transcribe()}>{state==='transcribing'?'Transcribing…':'Transcribe audio'}</button><button type="button" className="btn subtle" disabled={busy} onClick={()=>choose(null)} aria-label="Remove audio"><X size={15}/></button></div></div>}
  {error&&<p role="alert" className="form-error">{error}</p>}
  {hasTranscript&&<div className="voice-transcript"><div className="voice-transcript-title"><span><Check size={14}/> Transcript ready</span><small>{model}</small></div><label>Review and edit the transcript<textarea aria-label="Review voice transcript" value={text} maxLength={50000} rows={5} onChange={event=>{setText(event.target.value);setConfirmed(false);}}/></label><label className="voice-confirm"><input type="checkbox" checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}/> I reviewed this transcript and want to add it to the description.</label><button type="button" className="btn primary-action" disabled={!confirmed||!text.trim()} onClick={()=>{onConfirm(text.trim());choose(null);}}>Add to incident draft <Check size={14}/></button></div>}
  <p className="voice-privacy">Audio is sent to the configured voice provider only when you choose Transcribe. Transcription never creates an incident or approves an action. Recordings are held in page memory and cleared when you leave.</p>
 </section>;
}

export function SpeechBrief({text}:{text:string}){
 const {organizationId,role}=useSession();return can(role,'create')?<SpeechBriefContent key={`${organizationId}:${text}`} text={text}/>:null;
}
function SpeechBriefContent({text}:{text:string}){
 const {organizationId}=useSession();const capabilities=useVoiceCapabilities();const [excerpt,setExcerpt]=useState(()=>Array.from(text.trim()).length<=SPEECH_MAX_CHARACTERS?text.trim():'');const [url,setUrl]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');const audioUrl=useRef('');const request=useRef<AbortController|null>(null);
 useEffect(()=>()=>{request.current?.abort();if(audioUrl.current)URL.revokeObjectURL(audioUrl.current);},[]);
 async function speak(){request.current?.abort();const controller=new AbortController();request.current=controller;setBusy(true);setError('');setUrl('');if(audioUrl.current){URL.revokeObjectURL(audioUrl.current);audioUrl.current='';}try{const blob=await requestSpeech(organizationId,excerpt,controller.signal);if(!controller.signal.aborted){audioUrl.current=URL.createObjectURL(blob);setUrl(audioUrl.current);}}catch(cause){if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:'Speech failed.');}finally{if(!controller.signal.aborted)setBusy(false);}}
 function cancel(){request.current?.abort();setBusy(false);}
 function editExcerpt(value:string){cancel();if(audioUrl.current){URL.revokeObjectURL(audioUrl.current);audioUrl.current='';}setUrl('');setError('');setExcerpt(value);}
 const length=Array.from(excerpt.trim()).length;
 return <details className="speech-brief"><summary><Volume2 size={14}/> Listen to a short brief</summary><p>Choose an English excerpt, up to 200 characters. It is sent to the voice provider only when you generate audio.</p>{capabilities.error?<p role="alert" className="context-note">{capabilities.error.message} <button type="button" className="btn subtle" onClick={capabilities.refresh}>Retry voice settings</button></p>:capabilities.data?.speech_enabled!==true&&<p className="context-note">Spoken briefs are unavailable until voice capabilities confirm they are enabled.</p>}<label>Spoken excerpt<textarea aria-label="Spoken excerpt" rows={3} value={excerpt} onChange={event=>editExcerpt(event.target.value)}/></label><small>{length} / 200 characters · No text is automatically shortened.</small><div className="button-row"><button type="button" className="btn secondary" disabled={busy||length<1||length>200||capabilities.data?.speech_enabled!==true} onClick={()=>void speak()}>{busy?'Generating audio…':'Generate spoken brief'}</button>{busy&&<button type="button" className="btn subtle" onClick={cancel}>Cancel</button>}</div>{error&&<p role="alert" className="form-error">{error}</p>}{url&&<audio controls src={url} preload="metadata" aria-label="Spoken investigation brief"/>}</details>;
}
