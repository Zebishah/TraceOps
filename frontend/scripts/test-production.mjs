import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath} from 'node:url';
const organization='d5d2a37c-5538-4783-8f42-a285d8534b7a';
const requests=[];const token='fixture.'+Buffer.from(JSON.stringify({exp:Math.floor(Date.now()/1000)+3600})).toString('base64url')+'.fixture';
const wave=Buffer.from('RIFF0000WAVEfixture');
let malformed=false;
const upstream=createServer(async(request,response)=>{
 let body='';for await(const chunk of request)body+=chunk;requests.push({url:request.url,method:request.method,authorization:request.headers.authorization,contentType:request.headers['content-type'],body});
 response.setHeader('content-type','application/json');response.setHeader('x-request-id','fixture-request');
 if(request.url==='/api/v1/auth/login')return response.end(JSON.stringify({access_token:token}));
 if(request.url==='/api/v1/health')return response.end(JSON.stringify({status:'ok'}));
 if(request.url?.endsWith('/voice/transcriptions'))return response.end(JSON.stringify({text:'Synthetic incident brief',model:'fixture',requires_confirmation:true}));
 if(request.url?.endsWith('/voice/speech')){response.setHeader('content-type','audio/wav');return response.end(malformed?'invalid wave':wave);}
 if(request.url?.includes('q=provider-error')){response.statusCode=429;response.setHeader('retry-after','10');return response.end(JSON.stringify({detail:'Try again later'}));}
 if(request.url?.includes('q=redirect')){response.statusCode=302;response.setHeader('location','https://must-not-follow.example');return response.end();}
 if(request.url?.startsWith('/api/v1/organizations/'))return response.end(JSON.stringify({items:[],total:0,limit:20,offset:0}));
 if(request.url==='/api/v1/auth/me')return response.end(JSON.stringify({user:{id:organization,email:'fixture@example.com',full_name:'Fixture'},memberships:[{organization_id:organization,role:'owner'}]}));
 response.statusCode=404;response.end(JSON.stringify({detail:'Not found'}));
});
upstream.listen(0,'127.0.0.1');await once(upstream,'listening');
const upstreamPort=upstream.address().port;
const reserve=createServer();reserve.listen(0,'127.0.0.1');await once(reserve,'listening');const port=reserve.address().port;await new Promise(resolve=>reserve.close(resolve));
let output='';
const child=spawn(process.execPath,[fileURLToPath(new URL('./run-framework.mjs',import.meta.url)),'start'],{cwd:fileURLToPath(new URL('..',import.meta.url)),env:{...process.env,NODE_ENV:'production',PORT:String(port),OPSPILOT_BACKEND_URL:`http://127.0.0.1:${upstreamPort}`},stdio:['ignore','pipe','pipe']});
child.stdout.on('data',chunk=>output+=chunk);child.stderr.on('data',chunk=>output+=chunk);
const base=`http://127.0.0.1:${port}`;
try{
 let ready=false;
 for(let attempt=0;attempt<150;attempt++){if(child.exitCode!==null)throw new Error(output);try{if((await fetch(base+'/login')).ok){ready=true;break;}}catch{}await new Promise(resolve=>setTimeout(resolve,200));}
 assert.ok(ready,output);
 assert.equal((await fetch(base)).status,200);
 const protectedPage=await fetch(base+'/app/incidents',{redirect:'manual'});assert.equal(protectedPage.status,307);assert.ok(protectedPage.headers.get('location')?.includes('/login'));
 assert.equal((await fetch(base+'/api/backend/health')).status,200);
 assert.equal((await fetch(base+'/api/backend/auth/me')).status,401);
 assert.equal((await fetch(base+'/api/backend/auth/login',{method:'POST',headers:{origin:'https://attacker.example','content-type':'application/json'},body:'{}'})).status,403);
 const session=await fetch(base+'/api/backend/auth/login',{method:'POST',headers:{origin:base,'content-type':'application/json'},body:JSON.stringify({email:'fixture@example.com',password:'fixture-password'})});
 assert.equal(session.status,200);assert.deepEqual(await session.json(),{authenticated:true});
 const cookie=session.headers.get('set-cookie');assert.match(cookie,/HttpOnly/i);assert.match(cookie,/Secure/i);assert.match(cookie,/SameSite=strict/i);assert.ok(!JSON.stringify(await fetch(base+'/login').then(r=>r.text())).includes(token));
 const sessionCookie=cookie.split(';')[0];const headers={cookie:sessionCookie,origin:base};
 const records=await fetch(base+`/api/backend/organizations/${organization}/dashboard/resources/incidents?limit=20&offset=0&q=duplicate`,{headers});assert.equal(records.status,200);assert.equal(records.headers.get('x-request-id'),'fixture-request');assert.equal(records.headers.get('cache-control'),'no-store');assert.equal(requests.at(-1).authorization,`Bearer ${token}`);assert.ok(requests.at(-1).url.endsWith('q=duplicate'));
 const providerError=await fetch(base+`/api/backend/organizations/${organization}/dashboard/resources/incidents?q=provider-error`,{headers});assert.equal(providerError.status,429);assert.equal(providerError.headers.get('retry-after'),'10');
 assert.equal((await fetch(base+`/api/backend/organizations/${organization}/dashboard/resources/incidents?q=redirect`,{headers})).status,502);
 const audio=new FormData();audio.set('file',new Blob([wave],{type:'audio/wav'}),'synthetic.wav');audio.set('language','en');
 const transcript=await fetch(base+`/api/backend/organizations/${organization}/voice/transcriptions`,{method:'POST',headers,body:audio});assert.equal(transcript.status,200);assert.equal((await transcript.json()).requires_confirmation,true);assert.match(requests.at(-1).contentType,/multipart\/form-data; boundary=/);assert.match(requests.at(-1).body,/synthetic.wav/);
 assert.equal((await fetch(base+`/api/backend/organizations/${organization}/voice/speech`,{headers})).status,405);
 const speech=()=>fetch(base+`/api/backend/organizations/${organization}/voice/speech`,{method:'POST',headers:{...headers,'content-type':'application/json'},body:JSON.stringify({text:'Synthetic decision brief'})});
 const spoken=await speech();assert.equal(spoken.status,200);assert.match(spoken.headers.get('content-type'),/audio\/wav/);assert.deepEqual(Buffer.from(await spoken.arrayBuffer()),wave);malformed=true;assert.equal((await speech()).status,502);
 const before=requests.length;assert.equal((await fetch(base+'/api/backend/admin/delete-all',{headers})).status,404);assert.equal(requests.length,before);
 assert.equal((await fetch(base+`/api/backend/organizations/${organization}/voice/transcriptions`,{method:'POST',headers,body:Buffer.alloc(11*1024*1024+1)})).status,413);
 const signedInPage=await fetch(base+'/app/incidents/new',{headers});assert.equal(signedInPage.status,200);assert.match(await signedInPage.text(),/opspilot/i);
 console.log('Production smoke passed: pages, auth, tenant forwarding, search, voice, CSRF, redirects, errors, and upload cap.');
}finally{
 child.kill('SIGTERM');await Promise.race([once(child,'exit'),new Promise(resolve=>setTimeout(resolve,5000))]);if(child.exitCode===null)child.kill('SIGKILL');await new Promise(resolve=>upstream.close(resolve));
}
