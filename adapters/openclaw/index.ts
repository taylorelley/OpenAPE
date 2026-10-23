/** OpenAPE OpenClaw plugin. Verified against openclaw 2026.10.5 (embedded runner).
 * `before_prompt_build` -> `appendContext` only; never systemPrompt, tool policy or
 * SOUL.md. Turn context comes from metadata: tool names and errors from
 * `after_tool_call` (never params or results), the run's channel and the declared
 * context (OPENAPE_CONTEXT). The current user message is read only with
 * OPENAPE_CONTEXT_TEXT=local, classified in memory and never transmitted. Permission grants
 * (allowPromptInjection / allowConversationAccess) remain host-controlled.
 * In active mode it registers one tool, persona_feedback (declared in
 * contracts.tools; style feedback only; OPENAPE_AGENT_FEEDBACK=0 disables). */
import {Binding,fromEnvironment,personaFeedbackTool,repoFiles,type Config} from '../common.ts';
export const HOST_VERSION='2026.10.5';
export function turnIdentity(event:any,ctx:any):string|null{
 // Only user-initiated turns. Heartbeat, cron and other triggers opt out.
 if(!ctx.sessionId||(ctx.trigger&&ctx.trigger!=='user'))return null;
 // Explicit empty string means "no textual request" (image-only, continuation): opt out.
 if(event.currentUserMessage!==undefined&&!String(event.currentUserMessage).trim())return null;
 // Native admission identity when the harness supplies it (stable across rebuilds);
 // otherwise the run id, so rebuilds/retries within one run reuse one decision.
 return event.currentUserMessageId??(ctx.runId?`run:${ctx.runId}`:null);
}
const TERMINAL_CHANNELS=['cli','local','terminal','tui'];
export function channel(ctx:any):string|undefined{
 const id=String(ctx?.channel??ctx?.messageProvider??'').toLowerCase();
 return !id||TERMINAL_CHANNELS.includes(id)?undefined:'chat';
}
export function install(api:any,config:Config,binding=new Binding(config,'upap.openclaw')){
 if(typeof api.on!=='function')throw Error('Missing native OpenClaw hook API');
 api.on('after_tool_call',(event:any,ctx:any)=>{binding.noteTool(ctx?.sessionId,event?.toolName??ctx?.toolName,Boolean(event?.error),event?.params?.path??event?.params?.file_path);});
 api.on('before_prompt_build',async(event:any,ctx:any)=>{
  const turn=turnIdentity(event,ctx);if(!turn)return;
  const r=await binding.express(ctx.sessionId,turn,ctx.modelProviderId,ctx.modelId,{channel:channel(ctx),repo_files:repoFiles(ctx.workspaceDir),text:event.currentUserMessage??event.prompt});
  ctx.hookInvocation?.assertActive();
  return r.text?{appendContext:r.text}:undefined;
 });
 api.on('agent_end',async(event:any,ctx:any)=>{
  if(ctx.sessionId)await binding.observe(ctx.sessionId,event.success?'turn.completed':'turn.failed',event.success?'ok':'failed');
 });
 if(config.mode==='active'&&config.agentFeedback!==false&&typeof api.registerTool==='function')api.registerTool((ctx:any)=>({
  name:personaFeedbackTool.name,label:'Persona feedback',description:personaFeedbackTool.description,parameters:personaFeedbackTool.parameters,
  async execute(_id:string,params:any){const text=await binding.reflect(ctx?.sessionId,params);return {content:[{type:'text',text}],details:{}};}
 }),{name:personaFeedbackTool.name});
 return binding;
}
export default {id:'openape',name:'OpenAPE',register(api:any){const config=fromEnvironment(HOST_VERSION);if(config)install(api,config);}};
