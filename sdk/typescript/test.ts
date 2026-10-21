import {test} from 'node:test';import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';import {Client,render,validateDecision} from './client.ts';
const fixtures=JSON.parse(readFileSync(new URL('../../protocol/upap/v1/conformance.json',import.meta.url),'utf8'));
for(const f of fixtures.decisions)test(f.name,()=>{if(f.valid)assert.doesNotThrow(()=>validateDecision(f.value));else assert.throws(()=>validateDecision(f.value));});
test('shadow is empty',()=>assert.equal(render({...fixtures.decisions[0].value,mode:'shadow'}),''));
test('offline and disabled do not block',async()=>{let calls=0;const c=new Client('http://127.0.0.1','test',10,async()=>{calls++;throw Error('offline')});assert.equal((await c.express(fixtures.request,'disabled')).status,'disabled');assert.equal(calls,0);assert.equal((await c.express(fixtures.request,'active')).text,'');});
