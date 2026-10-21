/** Source inspected at 56efa0e. Permission grants remain host-controlled. */
import {Binding,fromEnvironment,type Config} from '../common.ts';
export function install(api:any,config:Config,binding=new Binding(config,'upap.openclaw')){
 if(typeof api.on!=='function')throw Error('Missing native OpenClaw hook API');
 api.on('before_prompt_build',async(event:any,ctx:any)=>{
  // Native admission ID makes rebuilds idempotent. Do not infer a user from text,
  // sender name, cron or heartbeat; paths without a current textual request opt out.
  if(!event.currentUserMessage?.trim()||!event.currentUserMessageId||!ctx.sessionId||ctx.trigger==='heartbeat'||ctx.trigger==='cron')return;
  const r=await binding.express(ctx.sessionId,event.currentUserMessageId,ctx.modelProviderId,ctx.modelId);
  ctx.hookInvocation?.assertActive();
  return r.text?{appendContext:r.text}:undefined;
 });
 api.on('agent_end',async(event:any,ctx:any)=>{
  if(ctx.sessionId)await binding.observe(ctx.sessionId,event.success?'turn.completed':'turn.failed',event.success?'ok':'failed');
 });return binding;
}
export default {id:'openape',name:'OpenAPE',register(api:any){const config=fromEnvironment('2026.10.5');if(config)install(api,config);}};
