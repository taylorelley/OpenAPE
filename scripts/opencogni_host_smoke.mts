/** Real OpenCogni planner.http (with ./adapters/opencogni/upstream patch applied) +
 * OpenAPE companion against a synthetic chat endpoint. Run via
 * scripts/opencogni_host_smoke.py with OpenCogni's tsx. NOT live-model evidence. */
import assert from 'node:assert/strict';
const [opencogni,openape]=[process.env.OPENCOGNI_DIR!,process.env.OPENAPE_ROOT!];
const {HttpPlanner}=await import(`${opencogni}/packages/adapters/src/planner-http.ts`);
const {Client}=await import(`${openape}/sdk/typescript/client.ts`);
const {personalityPlugin}=await import(`${openape}/adapters/opencogni/index.ts`);
const client=new Client(process.env.OPENAPE_URL!,process.env.OPENAPE_TOKEN!,250);
const plugin=personalityPlugin(client,{tenant:'local',persona:'cogni',mode:'active'});
const provided:Record<string,any>={};plugin.apply({provide:(k:string,v:any)=>provided[k]=v});
const input={goal:{id:'g1',objective:'Restore service checkout to healthy',context:{},permittedActions:['restart_service'],successPredicate:{}},state:{simulationTimeMs:1000,entities:[],recentObservations:[]},actionCatalog:[{type:'restart_service',description:'restart',args:{service:'name'}}],history:[],memory:[],documentation:'doc'};
const req=()=>({input,signal:new AbortController().signal,deadlineMs:Date.now()+10000,snapshotRef:'snapshot:smoke',budget:{maxOutputTokens:400,maxInputTokens:20000}});
const planner=new HttpPlanner({baseUrl:process.env.MODEL_URL!,model:'synthetic-model',presentationStyle:provided['brain.personality'].presentationStyle});
const result=await planner.plan(req());
assert.equal(result.output.decision,'act');
console.log(JSON.stringify({phase:'active',plan:result.output.steps.map((s:any)=>s.actionType),records:plugin.records()}));
