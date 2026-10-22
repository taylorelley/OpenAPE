"""Deadline-bounded UPAP client and audited renderer. Default mode is shadow.

Standalone: depends only on httpx and the stdlib renderer in `lite.py`, never on the engine,
so a custom harness can use it without importing server or host-specific code.
"""
import hashlib
import json
import time
import httpx
from sdk.python.lite import validate_decision, render, check_endpoint, LOOPBACK

class UPAPError(Exception):
    def __init__(self,status,code,message,retryable=False):
        super().__init__(f'{status} {code}: {message}');self.status,self.code,self.retryable=status,code,retryable

class Client:
    def __init__(self,url,token,timeout=.25,transport=None):
        parsed=check_endpoint(url)
        self.http=httpx.Client(base_url=url,headers={'Authorization':'Bearer '+token},timeout=timeout,transport=transport,trust_env=parsed.hostname not in LOOPBACK)
        self.cache={}; self.timeout=timeout
    def close(self): self.http.close()
    def request(self,method,path,data=None,retry=False):
        """Retries once only for idempotent/transient failures, within one deadline."""
        start=time.monotonic()
        for attempt in range(2 if retry else 1):
            try:
                response=self.http.request(method,path,json={'protocol_version':'upap/1',**data} if data is not None else None,timeout=max(.001,self.timeout-(time.monotonic()-start)))
                if response.status_code>=500 and retry and attempt==0:continue
                try:result=response.json()
                except ValueError:result={}
                if response.status_code>=400:
                    err=result.get('error') or {}
                    raise UPAPError(response.status_code,err.get('code','HTTP_ERROR'),err.get('message',response.reason_phrase),bool(err.get('retryable')))
                if result.get('protocol_version')!='upap/1':raise ValueError('Unsupported response protocol')
                return result
            except (httpx.TransportError,httpx.TimeoutException):
                if not retry or attempt or time.monotonic()-start>=self.timeout:raise
        raise UPAPError(503,'ENGINE_UNAVAILABLE','Request failed',True)
    def express(self,request,mode='shadow'):
        if mode=='disabled':return {'text':'','status':'disabled','decision':None}
        req={**request,'mode':mode,'protocol_version':'upap/1'}
        # Cache key covers user, persona, provider, context, session and mode; never another user's scope.
        scoped={k:v for k,v in req.items() if k!='request_id'}
        key=hashlib.sha256(json.dumps(scoped,sort_keys=True).encode()).hexdigest()
        try:
            d=validate_decision(self.request('POST','/v1/express',req,retry=True))
            if d['request_id']!=req['request_id'] or d['mode']!=mode:raise ValueError('Response binding mismatch')
            text=render(d)
            if len(self.cache)>=128:self.cache.pop(next(iter(self.cache)))
            self.cache[key]=(time.monotonic()+min(d['cache_ttl_ms'],30000)/1000,text,d)
            return {'text':text,'status':'applied' if text else 'shadow','decision':d}
        except (httpx.HTTPError,UPAPError,ValueError,KeyError,TypeError):
            old=self.cache.get(key)
            if old and old[0]>time.monotonic():return {'text':old[1],'status':'cached','decision':old[2]}
            return {'text':'','status':'unavailable','decision':None}
