import {createHash,randomUUID} from 'node:crypto';
import {Client,personaFeedbackTool,type Mode,type PersonalityContext,type Reflection,type RenderedExpression} from '../sdk/typescript/client.ts';
export {personaFeedbackTool};
export const stableId=(s:string)=>createHash('sha256').update(s).digest('hex').slice(0,48);
export type Config={url:string;token:string;tenant:string;persona:string;user?:string;mode?:Mode;hostVersion:string;agentFeedback?:boolean};
export function fromEnvironment(hostVersion:string):Config|null{
 if(!process.env.OPENAPE_TOKEN||!process.env.OPENAPE_PERSONA)return null;
 return {url:process.env.OPENAPE_URL??'http://127.0.0.1:8765',token:process.env.OPENAPE_TOKEN,tenant:process.env.OPENAPE_TENANT??'local',persona:process.env.OPENAPE_PERSONA,user:process.env.OPENAPE_LINKED_USER,mode:(process.env.OPENAPE_MODE??'shadow') as Mode,hostVersion,agentFeedback:process.env.OPENAPE_AGENT_FEEDBACK!=='0'};
}
export class Binding {
 client:Client;config:Config;adapter:string;last=new Map<string,RenderedExpression>();
 constructor(config:Config,adapter:string,client?:Client){this.config=config;this.adapter=adapter;this.client=client??new Client(config.url,config.token);}
 async express(session:string,turn:string,provider='other',model='unspecified'){
  const req:PersonalityContext={protocol_version:'upap/1',request_id:stableId(`${this.adapter}:${session}:${turn}`),identity:{tenant_id:this.config.tenant,persona_id:this.config.persona,...(this.config.user?{user_id:this.config.user}:{})},session:{id:stableId(`${this.adapter}:${session}:${this.config.persona}`),turn_id:stableId(turn)},host:{adapter_id:this.adapter,adapter_version:'0.2.0',host_version:this.config.hostVersion,provider_family:(['openai','anthropic','google','qwen'].includes(provider)?provider:'other') as any,model_id:stableId(model)},context:{task_type:'general',channel:'terminal',stakes:'medium',turn_origin:'user',tags:[]}};
  const result=await this.client.express(req,this.config.mode??'shadow');this.last.set(session,result);
  if(this.last.size>128)this.last.delete(this.last.keys().next().value!);return result;
 }
 async observe(session:string,type='turn.completed',status='ok'){
  if(this.config.mode==='disabled')return;
  const last=this.last.get(session);if(!last?.decision)return;
  try{await this.client.request('POST','/v1/observations',{adapter_id:this.adapter,events:[{event_id:randomUUID(),occurred_at:new Date().toISOString(),persona_id:this.config.persona,...(this.config.user?{user_id:this.config.user}:{}),session_id:stableId(`${this.adapter}:${session}:${this.config.persona}`),decision_id:last.decision.decision_id,type,status}]});}catch{/* Observation loss never blocks host. */}
 }
 /** persona_feedback tool call: attaches to this session's latest decision (active mode only). */
 async reflect(session:string|undefined,args:Reflection):Promise<string>{
  const last=session?this.last.get(session):undefined;
  if(this.config.mode!=='active'||!last?.decision)return 'Not recorded: no active persona decision for this turn.';
  return this.client.reflect(last.decision.decision_id,args);
 }
}
