'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
export function useResource<T>(loader:((signal:AbortSignal)=>Promise<T>)|null,deps:readonly unknown[],pollMs=0){
 const [data,setData]=useState<T|null>(null);const [error,setError]=useState<Error|null>(null);const [loading,setLoading]=useState(Boolean(loader));const [version,setVersion]=useState(0);const saved=useRef(loader);saved.current=loader;
 const refresh=useCallback(()=>setVersion(v=>v+1),[]);
 useEffect(()=>{const controller=new AbortController();let timer:ReturnType<typeof setTimeout>|undefined;let active=true;setData(null);setError(null);setLoading(Boolean(saved.current));
 async function run(){if(!saved.current)return;if(pollMs&&document.visibilityState==='hidden'){timer=setTimeout(run,pollMs);return;}try{const value=await saved.current(controller.signal);if(active){setData(value);setError(null);}}catch(cause){if(active&&!controller.signal.aborted)setError(cause instanceof Error?cause:new Error('Request failed'));}finally{if(active){setLoading(false);if(pollMs)timer=setTimeout(run,pollMs);}}}
 void run();return()=>{active=false;controller.abort();if(timer)clearTimeout(timer);};
 // Callers provide scalar dependencies for their resource identity.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[...deps,version,pollMs]);
 return {data,error,loading,refresh};
}
