/** OpenAPE companion for OpenCogni (Cordis). Verified against opencogni 833f4e6 plus
 * the separately reviewable boundary change in ./upstream (HttpPlannerOptions.
 * presentationStyle). The style only shapes summary/rationale wording; actions,
 * permission checks, routing, usage accounting and the evaluator are untouched.
 * Without the upstream change this module has no planner effect. */
import {createHash} from 'node:crypto';
import {Client,type Mode,type RenderedExpression} from '../../sdk/typescript/client.ts';
export const HOST_COMMIT='833f4e6bb77c35f87c139e4944f80424f2ff8a30';
const stable=(s:string)=>createHash('sha256').update(s).digest('hex').slice(0,48);
export type OpenCogniConfig={tenant:string;persona:string;mode?:Mode;user?:string};
export type StyleRecord={goalId:string;decisionId:string|null;personaVersion:string|null;decoderHash:string|null;status:string};

/** Returns an `HttpPlannerOptions.presentationStyle` provider plus an audit trail of
 * decision IDs / pinned versions / application status per planning call. */
export function presentationStyle(client:Client,config:OpenCogniConfig,audit:(r:StyleRecord)=>void=()=>{}){
 return async(input:{goal:{id:string};state:{simulationTimeMs:number};history:unknown[]})=>{
  const goal=String(input.goal?.id??'unknown');
  const request={protocol_version:'upap/1' as const,request_id:stable(`opencogni:${goal}:${input.state?.simulationTimeMs}:${input.history?.length??0}`),
   identity:{tenant_id:config.tenant,persona_id:config.persona,...(config.user?{user_id:config.user}:{})},
   session:{id:stable(`opencogni:${goal}:${config.persona}`),turn_id:stable(`${input.state?.simulationTimeMs}:${input.history?.length??0}`)},
   host:{adapter_id:'upap.opencogni',adapter_version:'0.2.0',host_version:HOST_COMMIT.slice(0,12),provider_family:'other' as const,model_id:'planner-http'},
   // Operations planning: machine-initiated, background channel, medium stakes.
   context:{task_type:'general',channel:'background',stakes:'medium',turn_origin:'system',tags:['technical']}};
  const r:RenderedExpression=await client.express(request,config.mode??'shadow');
  audit({goalId:goal,decisionId:r.decision?.decision_id??null,personaVersion:r.decision?.persona_version??null,decoderHash:r.decision?.decoder_hash??null,status:r.status});
  return r.text||null;
 };
}

/** Cordis plugin exposing `brain.personality`. Default shadow mode. */
export function personalityPlugin(client:Client,config:OpenCogniConfig){
 const records:StyleRecord[]=[];
 const provider=presentationStyle(client,config,r=>{records.push(r);if(records.length>256)records.shift();});
 return {name:'brain.personality',version:'0.2.0',apply(ctx:any){
  if(typeof ctx.provide!=='function')throw Error('Cordis service API unavailable');
  ctx.provide('brain.personality',{protocol:'upap/1',mode:config.mode??'shadow',presentationStyle:provider,records:()=>[...records]});
 },presentationStyle:provider,records:()=>[...records]};
}
