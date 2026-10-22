/** OpenAPE OpenClaw plugin. Verified against openclaw 2026.10.5 (embedded runner).
 * `before_prompt_build` -> `appendContext` only; never systemPrompt, tool policy or
 * SOUL.md. Prompt text is never read or transmitted. Permission grants
 * (allowPromptInjection / allowConversationAccess) remain host-controlled. */
import {Binding,fromEnvironment,type Config} from '../common.ts';
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
export function install(api:any,config:Config,binding=new Binding(config,'upap.openclaw')){
 if(typeof api.on!=='function')throw Error('Missing native OpenClaw hook API');
 api.on('before_prompt_build',async(event:any,ctx:any)=>{
  const turn=turnIdentity(event,ctx);if(!turn)return;
  const r=await binding.express(ctx.sessionId,turn,ctx.modelProviderId,ctx.modelId);
  ctx.hookInvocation?.assertActive();
  return r.text?{appendContext:r.text}:undefined;
 });
 api.on('agent_end',async(event:any,ctx:any)=>{
  if(ctx.sessionId)await binding.observe(ctx.sessionId,event.success?'turn.completed':'turn.failed',event.success?'ok':'failed');
 });return binding;
}
export default {id:'openape',name:'OpenAPE',register(api:any){const config=fromEnvironment(HOST_VERSION);if(config)install(api,config);}};
