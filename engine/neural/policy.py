"""Host-independent CPU policy. Latent coordinates carry no assigned meanings."""
import hashlib
import json
from pathlib import Path
import torch
from torch import nn
from safetensors.torch import load_file, save_file

torch.set_num_threads(1)
from protocol.catalogue import CATALOGUE

class Policy(nn.Module):
    def __init__(self):
        super().__init__()
        self.network = nn.Sequential(nn.Linear(192,128),nn.GELU(),nn.Linear(128,64),nn.GELU(),nn.Linear(64,20))
    def forward(self,x):
        return self.network(x)

def features(context,host):
    """Stable categorical hashing; encoder/1. No transcript or model calls."""
    x=torch.zeros(80)
    for key,val in sorted(context.items()):
        for v in val if isinstance(val,list) else [val]:
            n=int.from_bytes(hashlib.sha256(f'{key}:{v}'.encode()).digest()[:4],'big')%64
            x[n]=1
    for key in ('provider_family','adapter_id'):
        n=int.from_bytes(hashlib.sha256(f'{key}:{host.get(key,"other")}'.encode()).digest()[:4],'big')%16
        x[64+n]=1
    return x

def inputs(core,rel,context,host):
    return torch.cat((core,rel,torch.zeros(16),features(context,host)))

def mask(context):
    m=torch.ones(20,dtype=torch.bool)
    if context.get('stakes')=='high' or 'sensitive' in context.get('tags',[]):
        for i,c in enumerate(CATALOGUE):
            if c['humour']!='low': m[i]=False
    return m

def digest(path):
    return 'sha256:'+hashlib.sha256(Path(path).read_bytes()).hexdigest()

class Decoder:
    def __init__(self,path):
        self.path=Path(path); self.model=None; self.hash='untrained'
        manifest=self.path.with_suffix('.json')
        if self.path.exists() and manifest.exists():
            meta=json.loads(manifest.read_text())
            if meta['hash']!=digest(self.path): raise ValueError('decoder checksum mismatch')
            self.model=Policy(); self.model.load_state_dict(load_file(str(self.path))); self.model.eval()
            for p in self.model.parameters(): p.requires_grad_(False)
            self.hash=meta['hash']
    def logits(self,core,rel,context,host):
        if self.model is None: return torch.zeros(20).masked_fill(~mask(context),float('-inf'))
        return self.model(inputs(core,rel,context,host)).masked_fill(~mask(context),float('-inf'))
