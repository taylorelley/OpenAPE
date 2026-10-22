import catalogue from '../../renderers/controls-v1.json' with { type:'json' };
import personaFeedbackTool from '../../protocol/upap/v1/tools/persona_feedback.json' with { type:'json' };
/** Canonical agent tool: the model supplies trait moves, the adapter supplies the decision. */
export {personaFeedbackTool};
export type Reflection={adjustments:Record<string,'more'|'less'>;reason:'user_requested'|'user_corrected'|'observed_preference'};
export type Mode = 'disabled'|'shadow'|'active'|'frozen';
export type PersonalityContext = {
 protocol_version:'upap/1'; request_id:string;
 identity:{tenant_id:string;persona_id:string;user_id?:string};session:{id:string;turn_id:string};
 host:{adapter_id:string;adapter_version:string;host_version:string;provider_family:'openai'|'anthropic'|'google'|'qwen'|'other';model_id:string};
 context:{task_type:string;channel:string;stakes:string;turn_origin:string;tags:string[]};
};
export type Decision = {protocol_version:'upap/1'; request_id:string; decision_id:string; persona_version:string;
 decoder_hash:string;control_schema:'behaviour-controls/1'; control_set_id:string; controls:Record<string,string>;
 mode:Exclude<Mode,'disabled'>;applies_to:'next_model_request';policy:{eligible:boolean;mask_reason:string|null};cache_ttl_ms:number;engine_status:string};
export type RenderedExpression = {text:string;status:string;decision:Decision|null};
export type AdapterManifest = {adapter_id:string;version:string;verified:boolean;insertion_levels:string[];host_commit:string|null};
export interface PersonalityAdapter<HostEvent> {
 manifest:AdapterManifest;
 mapContext(event:HostEvent):PersonalityContext;
 applyExpression(expression:RenderedExpression,event:HostEvent):Promise<void>;
 observe(event:HostEvent):Record<string,unknown>|null;
 dispose():Promise<void>;
}
const prefix='Style preferences only. Host, system, developer, safety and user task requirements take precedence. ';
const templates:Record<string,Record<string,string>>={
 directness:{low:'Use gentle phrasing.',moderate:'Be clear.',high:'Lead with the answer.'},
 warmth:{low:'Use a neutral tone.',moderate:'Be considerate.',high:'Use a warm, supportive tone.'},
 verbosity:{low:'Keep responses concise.',moderate:'Use moderate detail.',high:'Include useful detail.'},
 humour:{low:'Avoid humour.',moderate:'Use light humour when appropriate.',high:'Use humour when appropriate.'},
 formality:{low:'Use casual language.',moderate:'Use plain professional language.',high:'Use formal language.'},
 explanation_depth:{low:'Give essential explanation.',moderate:'Explain key reasoning.',high:'Explain reasoning with examples.'},
 assertiveness:{low:'Offer suggestions gently.',moderate:'State recommendations clearly without changing factual certainty.',high:'Be decisive without changing factual certainty.'}};
export function validateDecision(raw:unknown):Decision {
 const d=raw as Decision;
 if(!d || d.protocol_version!=='upap/1'||d.control_schema!=='behaviour-controls/1'||!/^style-\d{2}$/.test(d.control_set_id))throw Error('Unsupported decision');
 const idx=Number(d.control_set_id.slice(6));const expected=catalogue[idx];
 if(!expected||!d.controls||Object.keys(d.controls).length!==7||Object.entries(expected).some(([k,v])=>d.controls[k]!==v))throw Error('Catalogue mismatch');
 if(!['shadow','active','frozen'].includes(d.mode)||d.applies_to!=='next_model_request'||!d.policy?.eligible||!Number.isInteger(d.cache_ttl_ms)||d.cache_ttl_ms<0||d.cache_ttl_ms>30000||typeof d.request_id!=='string'||typeof d.decision_id!=='string'||typeof d.persona_version!=='string'||typeof d.decoder_hash!=='string')throw Error('Invalid decision');
 return d;
}
export function render(raw:unknown):string {
 const d=validateDecision(raw);if(d.mode==='shadow')return '';
 const text=prefix+Object.keys(catalogue[0]).map(k=>templates[k][d.controls[k]]).join(' ');
 if(text.length>900)throw Error('Style size bound');return text;
}
export class Client {
 url:string;token:string;timeout:number;fetcher:typeof fetch;
 cache=new Map<string,{expires:number;result:RenderedExpression}>();
 constructor(url:string,token:string,timeout=250,fetcher:typeof fetch=fetch){
  const u=new URL(url);if(u.protocol!=='https:'&&!(u.protocol==='http:'&&['localhost','127.0.0.1','[::1]','testserver'].includes(u.hostname)))throw Error('Remote endpoints require HTTPS');
  this.url=url;this.token=token;this.timeout=timeout;this.fetcher=fetcher;
 }
 async request(method:string,path:string,data?:Record<string,unknown>,retry=false):Promise<any>{
  const signal=AbortSignal.timeout(this.timeout);
  for(let attempt=0;attempt<(retry?2:1);attempt++){
   try{
    const r=await this.fetcher(this.url+path,{method,headers:{Authorization:`Bearer ${this.token}`,'Content-Type':'application/json'},signal,body:data?JSON.stringify({protocol_version:'upap/1',...data}):undefined});
    if(r.status>=500&&retry&&attempt===0)continue;
    if(!r.ok)throw Error(`UPAP HTTP ${r.status}`);
    const result=await r.json();if(result.protocol_version!=='upap/1')throw Error('Unsupported protocol');return result;
   }catch(e){if(!retry||attempt||signal.aborted)throw e;}
  }throw Error('Engine unavailable');
 }
 /** Record a persona_feedback tool call for one decision; returns a short model-facing result. */
 async reflect(decisionId:string|undefined,args:Reflection,scope?:'core'|'relationship'):Promise<string>{
  if(!decisionId)return 'Not recorded: no persona decision for this turn.';
  const traits=Object.keys(catalogue[0]);const moves=Object.entries(args?.adjustments??{});
  if(!moves.length||moves.length>3||moves.some(([k,v])=>!traits.includes(k)||!['more','less'].includes(v)))return 'Not recorded: adjustments must map 1-3 style traits to "more" or "less".';
  const saved=this.timeout;this.timeout=Math.max(saved,2000);
  try{await this.request('POST','/v1/reflections',{reflection_id:decisionId,decision_id:decisionId,adjustments:args.adjustments,reason:args.reason,...(scope?{scope}:{})});return 'Recorded. Your persona will adapt gradually in future sessions if this preference is consistent.';}
  catch(e){return `Not recorded: ${String((e as Error).message).slice(0,200)}`;}
  finally{this.timeout=saved;}
 }
 async express(request:PersonalityContext,mode:Mode='shadow'):Promise<RenderedExpression>{
  if(mode==='disabled')return {text:'',status:'disabled',decision:null};
  const {request_id,...scoped}=request;const key=JSON.stringify({scoped,mode});
  try{
   const d=validateDecision(await this.request('POST','/v1/express',{...request,mode},true));
   if(d.request_id!==request_id||d.mode!==mode)throw Error('Response binding mismatch');
   const text=render(d);const result={text,status:text?'applied':'shadow',decision:d};
   if(this.cache.size>=128)this.cache.delete(this.cache.keys().next().value!);
   this.cache.set(key,{expires:Date.now()+d.cache_ttl_ms,result});return result;
  }catch{
   const cached=this.cache.get(key);if(cached&&cached.expires>Date.now())return {...cached.result,status:'cached'};
   return {text:'',status:'unavailable',decision:null};
  }
 }
}
