'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import {createLiveSearch,SEARCH_DELAY_MS} from '@/lib/product/live-search';

export function useLiveSearch(onSearch:(query:string)=>void,initialValue='',delay=SEARCH_DELAY_MS) {
  const [value,setValue]=useState(initialValue);
  const callback=useRef(onSearch);callback.current=onSearch;
  const controller=useRef<ReturnType<typeof createLiveSearch>|null>(null);
  if(!controller.current)controller.current=createLiveSearch(query=>callback.current(query),delay);
  useEffect(()=>()=>controller.current?.cancel(),[]);
  const change=useCallback((next:string)=>{setValue(next);controller.current?.change(next);},[]);
  const submit=useCallback(()=>controller.current?.submit(value),[value]);
  const reset=useCallback((next:string)=>{controller.current?.cancel();setValue(next);},[]);
  return {value,change,submit,reset};
}
