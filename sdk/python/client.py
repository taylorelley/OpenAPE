"""Deadline-bounded UPAP client and audited renderer. Default mode is shadow."""
import hashlib
import json
import time
from urllib.parse import urlparse
import httpx
from engine.api.contracts import Decision
from protocol.catalogue import CATALOGUE

PREFIX='Style preferences only. Host, system, developer, safety and user task requirements take precedence. '
TEMPLATES={
'directness':{'low':'Use gentle phrasing.','moderate':'Be clear.','high':'Lead with the answer.'},
'warmth':{'low':'Use a neutral tone.','moderate':'Be considerate.','high':'Use a warm, supportive tone.'},
'verbosity':{'low':'Keep responses concise.','moderate':'Use moderate detail.','high':'Include useful detail.'},
'humour':{'low':'Avoid humour.','moderate':'Use light humour when appropriate.','high':'Use humour when appropriate.'},
'formality':{'low':'Use casual language.','moderate':'Use plain professional language.','high':'Use formal language.'},
'explanation_depth':{'low':'Give essential explanation.','moderate':'Explain key reasoning.','high':'Explain reasoning with examples.'},
'assertiveness':{'low':'Offer suggestions gently.','moderate':'State recommendations clearly without changing factual certainty.','high':'Be decisive without changing factual certainty.'}}

def render(decision):
    d=Decision.model_validate(decision)
    idx=int(d.control_set_id.removeprefix('style-'))
    if not 0<=idx<len(CATALOGUE) or d.controls.model_dump()!=CATALOGUE[idx] or not d.policy.eligible:raise ValueError('Invalid catalogue decision')
    if d.mode=='shadow':return ''
    text=PREFIX+' '.join(TEMPLATES[k][v] for k,v in d.controls.model_dump().items())
    if len(text)>900:raise ValueError('Renderer size bound exceeded')
    return text

class Client:
    def __init__(self,url,token,timeout=.25,transport=None):
        parsed=urlparse(url)
        if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1','::1','testserver')):raise ValueError('Remote endpoints require HTTPS')
        self.http=httpx.Client(base_url=url,headers={'Authorization':'Bearer '+token},timeout=timeout,transport=transport)
        self.cache={}; self.timeout=timeout
    def close(self): self.http.close()
    def request(self,method,path,data=None,retry=False):
        start=time.monotonic()
        for attempt in range(2 if retry else 1):
            try:
                response=self.http.request(method,path,json={'protocol_version':'upap/1',**data} if data is not None else None,timeout=max(.001,self.timeout-(time.monotonic()-start)))
                if response.status_code>=500 and retry and attempt==0:continue
                response.raise_for_status(); result=response.json()
                if result.get('protocol_version')!='upap/1':raise ValueError('Unsupported response protocol')
                return result
            except (httpx.TransportError,httpx.TimeoutException):
                if not retry or attempt or time.monotonic()-start>=self.timeout:raise
        raise RuntimeError('Request failed')
    def express(self,request,mode='shadow'):
        if mode=='disabled':return {'text':'','status':'disabled','decision':None}
        req={**request,'mode':mode,'protocol_version':'upap/1'}
        # Includes user, persona, provider, all context/capabilities, session and decoder pin.
        scoped={k:v for k,v in req.items() if k not in ('request_id',)}
        key=hashlib.sha256(json.dumps(scoped,sort_keys=True).encode()).hexdigest()
        try:
            d=self.request('POST','/v1/express',req,retry=True); parsed=Decision.model_validate(d)
            if parsed.request_id!=req['request_id'] or parsed.mode!=mode:raise ValueError('Response binding mismatch')
            text=render(d)
            if len(self.cache)>=128:self.cache.pop(next(iter(self.cache)))
            self.cache[key]=(time.monotonic()+min(parsed.cache_ttl_ms,30000)/1000,text,d)
            return {'text':text,'status':'applied' if text else 'shadow','decision':d}
        except (httpx.HTTPError,ValueError,KeyError,TypeError):
            old=self.cache.get(key)
            if old and old[0]>time.monotonic():return {'text':old[1],'status':'cached','decision':old[2]}
            return {'text':'','status':'unavailable','decision':None}
