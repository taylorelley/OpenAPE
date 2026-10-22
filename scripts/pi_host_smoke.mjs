/** Real Pi SDK + native extension lifecycle, synthetic model transport. NOT live LLM evidence. */
import assert from 'node:assert/strict';
import {mkdtempSync} from 'node:fs';import {tmpdir} from 'node:os';import {join} from 'node:path';
import {createAgentSession,DefaultResourceLoader,SessionManager,SettingsManager,ModelRuntime} from '../.host-test/node_modules/@earendil-works/pi-coding-agent/dist/index.js';
import {createAssistantMessageEventStream} from '../.host-test/node_modules/@earendil-works/pi-ai/dist/compat.js';
import {install} from '../adapters/pi/index.ts';
const config={url:process.env.OPENAPE_URL,token:process.env.OPENAPE_TOKEN,tenant:'local',persona:'host-smoke',mode:'active',hostVersion:'1.3.0'};
const root=mkdtempSync(join(tmpdir(),'openape-pi-host-'));
const modelRuntime=await ModelRuntime.create({authPath:join(root,'auth.json'),modelsPath:null,modelsStorePath:join(root,'models'),refreshOnCreate:false});
await modelRuntime.setRuntimeApiKey('anthropic','synthetic-transport-not-a-provider-key');
const model={id:'synthetic-transport',name:'Synthetic test',api:'anthropic-messages',provider:'anthropic',baseUrl:'http://127.0.0.1:1',reasoning:false,input:['text'],cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:100000,maxTokens:1000};
const loader=new DefaultResourceLoader({cwd:root,agentDir:root,extensionFactories:[pi=>install(pi,config)],noSkills:true,noPromptTemplates:true,noThemes:true});
await loader.reload();
// Tiny keepRecentTokens so a short fixture session is eligible for manual compaction.
const settingsManager=SettingsManager.inMemory({compaction:{enabled:true,reserveTokens:16,keepRecentTokens:1}});
const {session}=await createAgentSession({cwd:root,agentDir:root,modelRuntime,model,thinkingLevel:'off',tools:['persona_feedback'],resourceLoader:loader,settingsManager,sessionManager:SessionManager.inMemory()});
const seen=[];
session.agent.streamFunction=(_model,context)=>{
 seen.push(context);
 const stream=createAssistantMessageEventStream();
 const message={role:'assistant',content:[{type:'text',text:'Synthetic host transport response.'}],api:model.api,provider:model.provider,model:model.id,usage:{input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}},stopReason:'stop',timestamp:Date.now()};
 queueMicrotask(()=>{stream.push({type:'done',reason:'stop',message});stream.end();});return stream;
};
try{
 await session.prompt('Fixture request; do not access files or tools.');
 assert.equal(seen.length,1);const prompt=JSON.stringify(seen[0]);
 assert(prompt.includes('Style preferences only.'));assert.equal((prompt.match(/Style preferences only\./g)||[]).length,1);
 // The only tool added is OpenAPE's own persona_feedback (active mode); it records a reflection.
 assert.deepEqual(session.agent.state.tools.map(t=>t.name),['persona_feedback']);
 const feedback=await session.agent.state.tools[0].execute('fixture-call',{adjustments:{verbosity:'less'},reason:'user_requested'});
 assert.match(feedback.content[0].text,/^Recorded/,feedback.content[0].text);
 await session.prompt('Second synthetic request.');
 assert.equal((JSON.stringify(seen[1]).match(/Style preferences only\./g)||[]).length,1,'historical style deduplicated');
 const count=i=>(JSON.stringify(seen[i]).match(/Style preferences only\./g)||[]).length;
 // Model switch: provider changes rendering inputs only; persona binding is unchanged.
 await modelRuntime.setRuntimeApiKey('openai','synthetic-transport-not-a-provider-key');
 await session.setModel({...model,id:'synthetic-transport-2',provider:'openai',api:'openai-completions'});
 await session.prompt('Request after model switch.');
 assert.equal(count(seen.length-1),1,'single style block after model switch');
 // Manual compaction then another turn: still exactly one style block.
 await session.compact();
 await session.prompt('Request after compaction.');
 assert.equal(count(seen.length-1),1,'single style block after compaction');
 // Independent concurrent session: separate host session id, same persona.
 const other=(await createAgentSession({cwd:root,agentDir:root,modelRuntime,model,thinkingLevel:'off',tools:[],resourceLoader:loader,sessionManager:SessionManager.inMemory()})).session;
 other.agent.streamFunction=session.agent.streamFunction;
 await other.prompt('Second session request.');
 assert.equal(count(seen.length-1),1,'second session receives its own single style block');
 other.dispose();
 if(process.env.OPENAPE_SMOKE_ENGINE_PID){
  process.kill(Number(process.env.OPENAPE_SMOKE_ENGINE_PID),'SIGTERM');
  await new Promise(resolve=>setTimeout(resolve,200));
  const before=seen.length;
  await session.prompt('Engine outage fixture request.');
  assert.equal(seen.length,before+1);
  assert(!JSON.stringify(seen[seen.length-1]).includes('Style preferences only.'),'no stale style during outage');
 }
 console.log(JSON.stringify({host:'Pi',version:'1.3.0',native_lifecycle:true,controls_reached_model_transport:true,tools_unchanged_except_persona_feedback:true,persona_feedback_recorded:true,historical_injection_deduplicated:true,model_switch:true,compaction:true,multi_session:true,engine_outage_continues:true,model:'synthetic transport; no provider API call',status:'PASS'}));
}finally{session.dispose();}
