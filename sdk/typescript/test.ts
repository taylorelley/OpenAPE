import {test} from 'node:test';import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';import {Client,classifyText,deriveContext,render,validateDecision} from './client.ts';
const fixtures=JSON.parse(readFileSync(new URL('../../protocol/upap/v2/conformance.json',import.meta.url),'utf8'));
for(const f of fixtures.decisions)test(f.name,()=>{if(f.valid){assert.equal(render(f.value),f.rendered);assert.equal(render(f.value,true),f.rendered_with_example);}else assert.throws(()=>validateDecision(f.value));});
test('shadow is empty',()=>assert.equal(render({...fixtures.decisions[0].value,mode:'shadow'}),''));
test('offline and disabled do not block',async()=>{let calls=0;const c=new Client('http://127.0.0.1','test',10,async()=>{calls++;throw Error('offline')});assert.equal((await c.express(fixtures.request,'disabled')).status,'disabled');assert.equal(calls,0);assert.equal((await c.express(fixtures.request,'active')).text,'');});
for(const f of fixtures.contexts)test(`context: ${f.name}`,()=>assert.deepEqual(deriveContext(f.signals,f.declared,f.text,undefined,undefined,f.project),f.context));
for(const f of fixtures.classifier)test(`classifier: ${f.text.slice(0,30)||'empty'}`,()=>assert.deepEqual(classifyText(f.text),f.result));
test('derived context never contains text',()=>assert(!JSON.stringify(deriveContext({tools:['Edit']},null,'zz-private-marker review this asap')).includes('zz-private-marker')));
