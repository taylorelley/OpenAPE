/** Custom host callback example. The host owns approval and context insertion. */
import {Client,type PersonalityContext,type Mode} from '../../sdk/typescript/client.ts';
export async function prepare(client:Client,request:PersonalityContext,appendContext:(text:string)=>void,mode:Mode='shadow'){
 const result=await client.express(request,mode);if(result.text)appendContext(result.text);return result;
}
/** Offer personaFeedbackTool to the model in active mode; route its calls here. */
export {personaFeedbackTool} from '../../sdk/typescript/client.ts';
export async function personaFeedback(client:Client,lastDecisionId:string|undefined,args:any){
 return client.reflect(lastDecisionId,args);
}
