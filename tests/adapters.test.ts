import {test} from 'node:test';import assert from 'node:assert/strict';
import {install as pi} from '../adapters/pi/index.ts';import {install as claw} from '../adapters/openclaw/index.ts';
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
  assert.equal(tool.name,'persona_feedback');assert.deepEqual(Object.keys(tool.parameters.properties),['adjustments','reason']);
  if(install===claw)assert.equal(opts.name,'persona_feedback');
  const result=await tool.execute('call',{adjustments:{humour:'less'},reason:'user_corrected'},undefined,undefined,{sessionManager:{getSessionId:()=> 's'}});
  assert.equal(result.content[0].text,'Recorded.');assert.equal(reflected[0][0],'s');assert.deepEqual(reflected[0][1].adjustments,{humour:'less'});
 }
});
