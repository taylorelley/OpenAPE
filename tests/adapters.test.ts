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
