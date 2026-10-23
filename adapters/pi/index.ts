/** Source inspected at 7f225f2, Pi 1.3.0. No system prompt replacement. In active mode it
 * registers one tool, persona_feedback (style feedback only; OPENAPE_AGENT_FEEDBACK=0 disables).
 * Turn context comes from metadata: tool names and errors from `tool_execution_end` (never
 * args or results) and the declared context (OPENAPE_CONTEXT). The prompt is read only with
 * OPENAPE_CONTEXT_TEXT=local, classified in memory and never transmitted. */
import {randomUUID} from 'node:crypto';
import {Binding,fromEnvironment,personaFeedbackTool,repoFiles,type Config} from '../common.ts';
export function install(pi:any,config:Config,binding=new Binding(config,'upap.pi')){
 if(typeof pi.on!=='function')throw Error('Missing Pi extension event API');
 // The touched file's extension comes from the call's arguments at start; status at end.
 pi.on('tool_execution_start',(event:any,ctx:any)=>{binding.noteTool(ctx?.sessionManager?.getSessionId?.(),undefined,false,event?.args?.path??event?.args?.file_path);});
 pi.on('tool_execution_end',(event:any,ctx:any)=>{binding.noteTool(ctx?.sessionManager?.getSessionId?.(),event?.toolName,event?.isError===true);});
 pi.on('before_agent_start',async(event:any,ctx:any)=>{
  if(event.messageType!=='user')return; // Custom/background triggers opt out. Child-process lineage is unverified.
  const session=ctx.sessionManager?.getSessionId?.();if(!session)return;
  const r=await binding.express(session,randomUUID(),ctx.model?.provider,ctx.model?.id,{text:event.prompt,repo_files:repoFiles(ctx?.cwd)});
  if(r.text)return {message:{customType:'openape-style',content:r.text,display:false,details:{decision_id:r.decision?.decision_id,persona_version:r.decision?.persona_version}}};
 });
 pi.on('context',(event:any,ctx:any)=>{
  const session=ctx.sessionManager?.getSessionId?.();
  const active=session?binding.last.get(session):null;
  const messages=event.messages??[];
  let keep=-1;
  if(active?.text&&active.decision){
   for(let i=messages.length-1;i>=0;i--){const m=messages[i];if(m.role==='custom'&&m.customType==='openape-style'&&m.details?.decision_id===active.decision.decision_id){keep=i;break;}}
  }
  return {messages:messages.filter((m:any,i:number)=>!(m.role==='custom'&&m.customType==='openape-style')||i===keep)};
 });
 pi.on('agent_end',async(_event:any,ctx:any)=>{
  const session=ctx.sessionManager?.getSessionId?.();if(session)await binding.observe(session);
 });
 if(config.mode==='active'&&config.agentFeedback!==false&&typeof pi.registerTool==='function')pi.registerTool({
  name:personaFeedbackTool.name,label:'Persona feedback',description:personaFeedbackTool.description,parameters:personaFeedbackTool.parameters,
  async execute(_id:string,params:any,_signal:any,_update:any,ctx:any){
   const text=await binding.reflect(ctx?.sessionManager?.getSessionId?.(),params);return {content:[{type:'text',text}],details:{}};
  }});
 pi.on('session_shutdown',async(_event:any,ctx:any)=>{
  const session=ctx.sessionManager?.getSessionId?.();if(session){await binding.observe(session,'session.ended');binding.last.delete(session);}
 });
 return binding;
}
export default function(pi:any){const config=fromEnvironment('1.3.0');if(config)install(pi,config);}
