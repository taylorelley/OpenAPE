import {createHash} from 'node:crypto';
import controls from '../../renderers/controls-v2.json' with { type:'json' };
import personaFeedbackTool from '../../protocol/upap/v2/tools/persona_feedback.json' with { type:'json' };
/** Canonical agent tool: the model supplies trait and habit moves, the adapter supplies the decision. */
import contextRules from '../../protocol/upap/v2/context-rules.json' with { type:'json' };
export {personaFeedbackTool};
export const PROTOCOL='upap/2';
/** Same canonical form as Python json.dumps(sort_keys=True, separators=(',',':')). */
const canonical=(v:any):string=>Array.isArray(v)?`[${v.map(canonical).join(',')}]`:v&&typeof v==='object'?`{${Object.keys(v).sort().map(k=>`${JSON.stringify(k)}:${canonical(v[k])}`).join(',')}}`:JSON.stringify(v);
export const CONTROLS_HASH='sha256:'+createHash('sha256').update(canonical(controls)).digest('hex');
const traits:string[]=controls.traits;const habits:Record<string,any>=Object.fromEntries(controls.habits.map((h:any)=>[h.id,h]));const habitIds=Object.keys(habits);
/** Host signals for context derivation: IDs, tool names and counts only, never text. */
export type ContextSignals={tools?:string[];failures?:number;plan_mode?:boolean;channel?:string;turn_origin?:string};
type Ctx=PersonalityContext['context'];
const labels=(v:unknown):string[]=>Array.isArray(v)?v.filter((x):x is string=>typeof x==='string'):[];
/** User-declared context (OPENAPE_CONTEXT): known enum values only; malformed input is dropped. */
export function parseDeclared(raw:unknown):Partial<Ctx>{
 let v:any=raw;if(typeof raw==='string'){try{v=JSON.parse(raw);}catch{return {};}}
 if(!v||typeof v!=='object'||Array.isArray(v))return {};
 const vocab:Record<string,string[]>=contextRules.vocab;const out:any={};
 for(const k of ['task_type','channel','stakes','turn_origin'])if(typeof v[k]==='string'&&vocab[k].includes(v[k]))out[k]=v[k];
 const tags=labels(v.tags).filter(t=>vocab.tags.includes(t)&&!contextRules.engine_tags.includes(t));if(tags.length)out.tags=tags;
 return out;
}
/** Mirror of sdk/python/lite.py derive_context (same rules file, same precedence). The
 * opt-in text is matched in memory on the host and never returned or kept. */
export function deriveContext(signals?:ContextSignals|null,declared?:unknown,text?:unknown,rules=contextRules):Ctx{
 const s:any=signals&&typeof signals==='object'?signals:{};const d:any=parseDeclared(declared??{});const vocab:Record<string,string[]>=rules.vocab;
 const ctx:any={...rules.defaults};const tags=new Set<string>();let task:string|undefined;
 const rise=(stakes?:string)=>{if(stakes&&vocab.stakes.includes(stakes)&&vocab.stakes.indexOf(stakes)>vocab.stakes.indexOf(ctx.stakes))ctx.stakes=stakes;};
 for(const k of ['channel','turn_origin'])if(vocab[k].includes(s[k]))ctx[k]=s[k];
 const names=new Set(labels(s.tools).map(n=>n.toLowerCase()));
 for(const r of rules.tools as any[])if(r.names.some((n:string)=>names.has(n))){task=task??r.task_type;for(const t of r.tags??[])tags.add(t);}
 for(const r of rules.failures as any[])if(Number.isInteger(s.failures)&&s.failures>=r.at_least){task=r.task_type??task;for(const t of r.tags??[])tags.add(t);rise(r.stakes);}
 if(s.plan_mode===true)task=rules.plan_mode.task_type;
 if(typeof text==='string'&&text){
  let found:string|undefined;
  for(const r of rules.text as any[])if(new RegExp(r.pattern,'i').test(text)){found=found??r.task_type;for(const t of r.tags??[])tags.add(t);rise(r.stakes);}
  task=found??task;
 }
 if(task)ctx.task_type=task;
 for(const [k,v] of Object.entries(d))if(k!=='tags')ctx[k]=v;for(const t of d.tags??[])tags.add(t);
 ctx.tags=vocab.tags.filter(t=>tags.has(t));
 return ctx;
}
export type Reflection={adjustments?:Record<string,'more'|'less'>;habits?:Record<string,'more_often'|'less_often'>;reason:'user_requested'|'user_corrected'|'observed_preference'};
export type Mode = 'disabled'|'shadow'|'active'|'frozen';
export type PersonalityContext = {
 protocol_version:'upap/2'; request_id:string;
 identity:{tenant_id:string;persona_id:string;user_id?:string};session:{id:string;turn_id:string};
 host:{adapter_id:string;adapter_version:string;host_version:string;provider_family:'openai'|'anthropic'|'google'|'qwen'|'other';model_id:string};
 context:{task_type:string;channel:string;stakes:string;turn_origin:string;tags:string[]};
};
export type Decision = {protocol_version:'upap/2'; request_id:string; decision_id:string; persona_version:string;
 decoder_hash:string;control_schema:'behaviour-controls/2';catalogue_hash:string;controls:Record<string,number>;habits:string[];
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
/** A complete, in-range configuration that passes the catalogue's coherence rules. */
export function coherent(c:any):boolean{
 if(!c||typeof c!=='object'||Array.isArray(c)||Object.keys(c).length!==traits.length||traits.some(t=>!Number.isInteger(c[t])||c[t]<0||c[t]>=controls.levels))return false;
 return !(controls.rules as any[]).some(([a,la,b,lb])=>la.includes(c[a])&&lb.includes(c[b]));
}
/** Known, unique, at most max_habits, in catalogue order, eligible and not mutually exclusive. */
export function habitsValid(ids:any,c:Record<string,number>):boolean{
 if(!Array.isArray(ids)||ids.length>controls.max_habits||ids.some(i=>typeof i!=='string'||!habitIds.includes(i)))return false;
 const ordered=habitIds.filter(i=>ids.includes(i));if(ordered.length!==ids.length||ordered.some((i,k)=>ids[k]!==i))return false;
 return ids.every((i:string)=>Object.entries(habits[i].requires as Record<string,number[]>).every(([t,[lo,hi]])=>c[t]>=lo&&c[t]<=hi)&&!habits[i].excludes.some((x:string)=>ids.includes(x)));
}
export function validateDecision(raw:unknown):Decision {
 const d=raw as Decision;
 if(!d||d.protocol_version!=='upap/2'||d.control_schema!==controls.schema||d.catalogue_hash!==CONTROLS_HASH)throw Error('Unsupported decision');
 if(!coherent(d.controls)||!habitsValid(d.habits,d.controls))throw Error('Catalogue mismatch');
 if(!['shadow','active','frozen'].includes(d.mode)||d.applies_to!=='next_model_request'||!d.policy?.eligible||!Number.isInteger(d.cache_ttl_ms)||d.cache_ttl_ms<0||d.cache_ttl_ms>30000||typeof d.request_id!=='string'||typeof d.decision_id!=='string'||typeof d.persona_version!=='string'||typeof d.decoder_hash!=='string')throw Error('Invalid decision');
 return d;
}
export function render(raw:unknown):string {
 const d=validateDecision(raw);if(d.mode==='shadow')return '';
 const text=[controls.prefix,...traits.map(t=>(controls.templates as Record<string,string[]>)[t][d.controls[t]]),...d.habits.map(h=>habits[h].text)].join(' ');
 if(text.length>controls.max_style_chars)throw Error('Style size bound');return text;
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
    const r=await this.fetcher(this.url+path,{method,headers:{Authorization:`Bearer ${this.token}`,'Content-Type':'application/json'},signal,body:data?JSON.stringify({protocol_version:'upap/2',...data}):undefined});
    if(r.status>=500&&retry&&attempt===0)continue;
    if(!r.ok)throw Error(`UPAP HTTP ${r.status}`);
    const result=await r.json();if(result.protocol_version!==PROTOCOL)throw Error('Unsupported protocol');return result;
   }catch(e){if(!retry||attempt||signal.aborted)throw e;}
  }throw Error('Engine unavailable');
 }
 /** Record a persona_feedback tool call for one decision; returns a short model-facing result. */
 async reflect(decisionId:string|undefined,args:Reflection,scope?:'core'|'relationship'):Promise<string>{
  if(!decisionId)return 'Not recorded: no persona decision for this turn.';
  const adjustments=args?.adjustments??{};const habitMoves=args?.habits??{};
  if(!adjustments||typeof adjustments!=='object'||Array.isArray(adjustments)||Object.keys(adjustments).length>3||Object.entries(adjustments).some(([k,v])=>!traits.includes(k)||!['more','less'].includes(v)))return 'Not recorded: adjustments must map up to 3 style traits to "more" or "less".';
  if(!habitMoves||typeof habitMoves!=='object'||Array.isArray(habitMoves)||Object.keys(habitMoves).length>2||Object.entries(habitMoves).some(([k,v])=>!habitIds.includes(k)||!['more_often','less_often'].includes(v)))return 'Not recorded: habits must map up to 2 known habits to "more_often" or "less_often".';
  if(!Object.keys(adjustments).length&&!Object.keys(habitMoves).length)return 'Not recorded: give at least one trait or habit move.';
  const saved=this.timeout;this.timeout=Math.max(saved,2000);
  try{await this.request('POST','/v1/reflections',{reflection_id:decisionId,decision_id:decisionId,adjustments,reason:args.reason,...(Object.keys(habitMoves).length?{habits:habitMoves}:{}),...(scope?{scope}:{})});return 'Recorded. Your persona will adapt gradually in future sessions if this preference is consistent.';}
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
