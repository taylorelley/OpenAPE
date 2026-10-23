import {createHash,randomUUID} from 'node:crypto';
import {readdirSync} from 'node:fs';
import {Client,deriveContext,extensionOf,parseDeclared,personaFeedbackTool,repoMarkers,type ContextSignals,type Mode,type PersonalityContext,type Reflection,type RenderedExpression} from '../sdk/typescript/client.ts';
export {personaFeedbackTool};
export const stableId=(s:string)=>createHash('sha256').update(s).digest('hex').slice(0,48);
/** `context`: the user's declared context (OPENAPE_CONTEXT). `contextText`: opt-in local
 * classification of the user's message (OPENAPE_CONTEXT_TEXT=local); the text is matched
 * in memory and never sent or stored, only the derived enum labels are. */
export type Config={url:string;token:string;tenant:string;persona:string;user?:string;mode?:Mode;hostVersion:string;agentFeedback?:boolean;context?:Partial<PersonalityContext['context']>;contextText?:boolean;example?:boolean};
/** Per-turn host metadata for context derivation. Tool names come from noteTool. */
export type TurnSignals=Omit<ContextSignals,'tools'|'failures'|'extensions'>&{text?:unknown};
/** Repository-marker file names in a directory (names only, contents never read). */
export function repoFiles(dir:unknown):string[]{try{return typeof dir==='string'?repoMarkers(readdirSync(dir).slice(0,5000)):[];}catch{return [];}}
export function fromEnvironment(hostVersion:string):Config|null{
 if(!process.env.OPENAPE_TOKEN||!process.env.OPENAPE_PERSONA)return null;
 return {url:process.env.OPENAPE_URL??'http://127.0.0.1:8765',token:process.env.OPENAPE_TOKEN,tenant:process.env.OPENAPE_TENANT??'local',persona:process.env.OPENAPE_PERSONA,user:process.env.OPENAPE_LINKED_USER,mode:(process.env.OPENAPE_MODE??'shadow') as Mode,hostVersion,agentFeedback:process.env.OPENAPE_AGENT_FEEDBACK!=='0',context:parseDeclared(process.env.OPENAPE_CONTEXT??'{}'),contextText:process.env.OPENAPE_CONTEXT_TEXT==='local',example:process.env.OPENAPE_STYLE_EXAMPLE==='1'};
}
export class Binding {
 client:Client;config:Config;adapter:string;last=new Map<string,RenderedExpression>();tools=new Map<string,{tools:string[];failures:number;extensions:string[]}>();
 constructor(config:Config,adapter:string,client?:Client){this.config=config;this.adapter=adapter;this.client=client??new Client(config.url,config.token);this.client.example=!!config.example;}
 /** Previous-turn signal for the next turn's context: a tool name, failure flag and the
  * mapped extension of a file it touched (never the path). */
 noteTool(session:string|undefined,name:unknown,failed=false,path?:unknown){
  if(!session)return;const seen=this.tools.get(session)??{tools:[],failures:0,extensions:[]};this.tools.delete(session);
  if(typeof name==='string'&&name&&!seen.tools.includes(name)&&seen.tools.length<32)seen.tools.push(name.slice(0,64));
  const ext=extensionOf(path);if(ext&&seen.extensions.length<64)seen.extensions.push(ext);
  if(failed)seen.failures++;this.tools.set(session,seen);if(this.tools.size>128)this.tools.delete(this.tools.keys().next().value!);
 }
 /** Consumes the session's tool signals; adds the declared context and the opt-in text. */
 context(session:string,turn:TurnSignals={}):PersonalityContext['context']{
  const {text,...signals}=turn;const seen=this.tools.get(session);this.tools.delete(session);
  return deriveContext({...seen,...signals},this.config.context??{},this.config.contextText?text:undefined);
 }
 async express(session:string,turn:string,provider='other',model='unspecified',signals:TurnSignals={}){
  const req:PersonalityContext={protocol_version:'upap/2',request_id:stableId(`${this.adapter}:${session}:${turn}`),identity:{tenant_id:this.config.tenant,persona_id:this.config.persona,...(this.config.user?{user_id:this.config.user}:{})},session:{id:stableId(`${this.adapter}:${session}:${this.config.persona}`),turn_id:stableId(turn)},host:{adapter_id:this.adapter,adapter_version:'0.3.0',host_version:this.config.hostVersion,provider_family:(['openai','anthropic','google','qwen'].includes(provider)?provider:'other') as any,model_id:stableId(model)},context:this.context(session,signals)};
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
