import {test} from 'node:test';import assert from 'node:assert/strict';
import {install as pi} from '../adapters/pi/index.ts';import {install as claw} from '../adapters/openclaw/index.ts';import {Binding} from '../adapters/common.ts';
const config={url:'http://127.0.0.1:1',token:'fixture',tenant:'local',persona:'ape',hostVersion:'fixture',mode:'active' as const};
function harness(install:any){
 const handlers=new Map<string,Function>();const calls:any[]=[];
 const binding={last:new Map(),express:async(...args:any[])=>{calls.push(args);return {text:'approved fixture style',decision:{decision_id:'d',persona_version:'v'}};},observe:async(...args:any[])=>{calls.push(args);}};
 install({on:(name:string,fn:Function)=>handlers.set(name,fn)},config,binding);return {handlers,calls};
}
test('Pi only returns context and never replaces host prompt',async()=>{
 const h=harness(pi);const ctx={sessionManager:{getSessionId:()=> 's'},model:{provider:'anthropic',id:'m'}};
 const event={messageType:'user',systemPrompt:'REQUIRED POLICY'};const result=await h.handlers.get('before_agent_start')!(event,ctx);
 assert(result.message);assert(!result.systemPrompt);assert.equal(event.systemPrompt,'REQUIRED POLICY');
 assert.equal(await h.handlers.get('before_agent_start')!({messageType:'custom'},ctx),undefined);
 await h.handlers.get('agent_end')!({},ctx);assert(h.calls.some(a=>a[0]==='s'));
});
test('OpenClaw skips heartbeat, cron and missing text/admission identity',async()=>{
 const h=harness(claw);const fn=h.handlers.get('before_prompt_build')!;
 for(const event of [{},{currentUserMessage:'hello'}])assert.equal(await fn(event,{sessionId:'s'}),undefined);
 const e={currentUserMessage:'hello',currentUserMessageId:'u'};
 assert.equal(await fn(e,{sessionId:'s',trigger:'heartbeat'}),undefined);
 assert.equal(await fn(e,{sessionId:'s',trigger:'cron'}),undefined);
 const r=await fn(e,{sessionId:'s'});assert.deepEqual(Object.keys(r),['appendContext']);
});
test('OpenClaw respects closed invocation lifetime',async()=>{
 const h=harness(claw);await assert.rejects(h.handlers.get('before_prompt_build')!({currentUserMessage:'hi',currentUserMessageId:'u'},{sessionId:'s',hookInvocation:{assertActive(){throw Error('closed')}}}));
});
test('Pi removes only its own stale custom style messages',()=>{
 const h=harness(pi);const ctx={sessionManager:{getSessionId:()=> 's'}};
 const messages=[{role:'system',content:'policy'},{role:'custom',customType:'openape-style',details:{decision_id:'old'},content:'stale'},{role:'custom',customType:'other',content:'retained'},{role:'user',content:'task'}];
 const result=h.handlers.get('context')!({messages},ctx);assert.equal(result.messages.length,3);assert(result.messages.some((m:any)=>m.content==='policy'));assert(result.messages.some((m:any)=>m.customType==='other'));
});
test('OpenClaw embedded runner: run id fallback, explicit empty request opts out',async()=>{
 const h=harness(claw);const fn=h.handlers.get('before_prompt_build')!;
 const r=await fn({prompt:'hi'},{sessionId:'s',runId:'r1',trigger:'user'});assert.deepEqual(Object.keys(r),['appendContext']);
 assert.equal(h.calls.at(-1)[1],'run:r1');
 assert.equal(await fn({currentUserMessage:'',currentUserMessageId:'u'},{sessionId:'s',runId:'r2'}),undefined);
 assert.equal(await fn({prompt:'tick'},{sessionId:'s',runId:'r3',trigger:'heartbeat'}),undefined);
});
test('Pi and OpenClaw register persona_feedback only in active mode',async()=>{
 for(const [install,mode,expected] of [[pi,'active',1],[pi,'shadow',0],[claw,'active',1],[claw,'shadow',0]] as const){
  const tools:any[]=[];const reflected:any[]=[];
  const binding={last:new Map(),express:async()=>({text:'',decision:null}),observe:async()=>{},reflect:async(...a:any[])=>{reflected.push(a);return 'Recorded.';}};
  install({on:()=>{},registerTool:(t:any,o?:any)=>tools.push([t,o])},{...config,mode},binding);
  assert.equal(tools.length,expected);if(!expected)continue;
  const [entry,opts]=tools[0];const tool=typeof entry==='function'?entry({sessionId:'s'}):entry;
  assert.equal(tool.name,'persona_feedback');assert.deepEqual(Object.keys(tool.parameters.properties),['adjustments','habits','reason']);
  if(install===claw)assert.equal(opts.name,'persona_feedback');
  const result=await tool.execute('call',{adjustments:{humour:'less'},reason:'user_corrected'},undefined,undefined,{sessionManager:{getSessionId:()=> 's'}});
  assert.equal(result.content[0].text,'Recorded.');assert.equal(reflected[0][0],'s');assert.deepEqual(reflected[0][1].adjustments,{humour:'less'});
 }
});
function recording(extra:Record<string,unknown>={}){
 const requests:any[]=[];
 const client={express:async(req:any)=>{requests.push(req);return {text:'approved fixture style',status:'applied',decision:{decision_id:'d',persona_version:'v'}};}} as any;
 return {requests,binding:new Binding({...config,...extra},'upap.test',client)};
}
test('OpenClaw derives context from tool metadata and never sends the message',async()=>{
 const {requests,binding}=recording({context:{tags:['expert']}});const handlers=new Map<string,Function>();
 claw({on:(name:string,fn:Function)=>handlers.set(name,fn)},config,binding);
 const ctx={sessionId:'s',trigger:'user',channel:'discord'};
 handlers.get('after_tool_call')!({toolName:'edit',params:{path:'zz-private'},result:'zz-private'},{sessionId:'s',toolName:'edit'});
 for(let i=0;i<2;i++)handlers.get('after_tool_call')!({toolName:'exec',params:{},error:'zz-private failure'},{sessionId:'s',toolName:'exec'});
 await handlers.get('before_prompt_build')!({currentUserMessage:'zz-private review this asap',currentUserMessageId:'u1'},ctx);
 assert.deepEqual(requests[0].context,{task_type:'debugging',channel:'chat',stakes:'high',turn_origin:'user',tags:['technical','expert','error_present'],language:'none',repo_kind:'unknown'});
 await handlers.get('before_prompt_build')!({currentUserMessage:'zz-private review this asap',currentUserMessageId:'u2'},{sessionId:'s',trigger:'user'});
 assert.deepEqual(requests[1].context,{task_type:'general',channel:'terminal',stakes:'medium',turn_origin:'user',tags:['expert'],language:'none',repo_kind:'unknown'});
 assert(!JSON.stringify(requests).includes('zz-private'));
});
test('Pi classifies the prompt locally only when opted in',async()=>{
 const ctx={sessionManager:{getSessionId:()=> 's'},model:{provider:'anthropic',id:'m'}};
 for(const [contextText,task] of [[false,'research'],[true,'code_review']] as const){
  const {requests,binding}=recording({contextText});const handlers=new Map<string,Function>();
  pi({on:(name:string,fn:Function)=>handlers.set(name,fn)},config,binding);
  handlers.get('tool_execution_end')!({toolName:'grep',isError:false,result:'zz-private'},ctx);
  await handlers.get('before_agent_start')!({messageType:'user',prompt:'zz-private please review this PR'},ctx);
  assert.equal(requests[0].context.task_type,task);assert(!JSON.stringify(requests).includes('zz-private'));
 }
});
