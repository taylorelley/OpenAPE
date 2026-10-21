/** Source inspected at 7f225f2, Pi 1.3.0. No tools or system prompt replacement. */
import {randomUUID} from 'node:crypto';
import {Binding,fromEnvironment,type Config} from '../common.ts';
export function install(pi:any,config:Config,binding=new Binding(config,'upap.pi')){
 if(typeof pi.on!=='function')throw Error('Missing Pi extension event API');
 pi.on('before_agent_start',async(event:any,ctx:any)=>{
  if(event.messageType!=='user')return; // Custom/background triggers opt out. Child-process lineage is unverified.
  const session=ctx.sessionManager?.getSessionId?.();if(!session)return;
  const r=await binding.express(session,randomUUID(),ctx.model?.provider,ctx.model?.id);
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
 pi.on('session_shutdown',async(_event:any,ctx:any)=>{
  const session=ctx.sessionManager?.getSessionId?.();if(session){await binding.observe(session,'session.ended');binding.last.delete(session);}
 });
 return binding;
}
export default function(pi:any){const config=fromEnvironment('1.3.0');if(config)install(pi,config);}
