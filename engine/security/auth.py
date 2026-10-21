import hashlib
import hmac
import json
import os
from dataclasses import dataclass

SCOPES={'persona:express','observations:write','feedback:write','persona:admin','training:admin'}
@dataclass(frozen=True)
class Principal:
    tenant: str
    actor: str
    scopes: frozenset[str]
    personas: tuple[str,...]
    users: tuple[str,...]
    def allows(self,persona,user=None):
        return ('*' in self.personas or persona in self.personas) and (user is None or '*' in self.users or user in self.users)

class Auth:
    def __init__(self,credentials=None):
        records=credentials if credentials is not None else json.loads(os.environ.get('OPENAPE_CREDENTIALS','[]'))
        self.records=[]
        for r in records:
            token=r['token']
            if len(token)<24: raise ValueError('credentials need >=24 characters')
            self.records.append((hashlib.sha256(token.encode()).digest(), Principal(r['tenant'],r['actor'],frozenset(r['scopes']),tuple(r.get('personas',[])),tuple(r.get('users',[])))))
        if not self.records: raise ValueError('Configure OPENAPE_CREDENTIALS; refusing unauthenticated startup')
    def verify(self,token):
        h=hashlib.sha256(token.encode()).digest()
        for expected,p in self.records:
            if hmac.compare_digest(h,expected): return p
        return None
