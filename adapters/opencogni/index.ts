/** Companion service only. No planner mutation: integration is unsupported pending
 * a separately reviewed host boundary change and upstream regression suite. */
import {Client} from '../../sdk/typescript/client.ts';
export function personalityPlugin(client:Client){
 return {name:'brain.personality',version:'0.1.0',apply(ctx:any){
  if(typeof ctx.provide!=='function')throw Error('Cordis service API unavailable');
  ctx.provide('brain.personality',{express:client.express.bind(client),protocol:'upap/1',mode:'shadow',plannerIntegrated:false});
 }};
}
