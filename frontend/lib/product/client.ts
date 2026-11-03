import { z } from 'zod';
export class ApiError extends Error { constructor(message:string,public status:number,public requestId:string|null=null){super(message);this.name='ApiError';} }
export async function api<T>(path:string,schema:z.ZodType<T,z.ZodTypeDef,unknown>,init:RequestInit={}):Promise<T>{
 const headers=new Headers(init.headers);
 if(init.body && !(init.body instanceof FormData))headers.set('Content-Type','application/json');
 const response=await fetch(`/api/backend/${path}`,{...init,headers,credentials:'same-origin',cache:'no-store'});
 let data:unknown;
 try{data=await response.json();}catch{throw new ApiError('The server returned an unexpected response',response.status);}
 if(!response.ok){let message=`Request failed (${response.status})`;if(typeof data==='object'&&data!==null&&'detail' in data){if(typeof data.detail==='string')message=data.detail;else if(Array.isArray(data.detail))message='Please check the submitted fields.';}throw new ApiError(message,response.status,response.headers.get('x-request-id'));}
 const parsed=schema.safeParse(data);
 if(!parsed.success)throw new ApiError('The backend response does not match this screen’s contract. Please refresh or check the deployment version.',502);
 return parsed.data;
}
export const post=<T>(path:string,schema:z.ZodType<T,z.ZodTypeDef,unknown>,payload:unknown={})=>api(path,schema,{method:'POST',body:JSON.stringify(payload)});
