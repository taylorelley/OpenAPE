"""Host-independent CPU policy. Latent coordinates carry no assigned meanings."""
import hashlib
import json
from pathlib import Path
import torch
from torch import nn
from safetensors.torch import load_file

torch.set_num_threads(1)
from protocol.catalogue import CATALOGUE

CORE_DIM, REL_DIM, SESSION_DIM, CONTEXT_DIM, PROVIDER_DIM = 64, 32, 16, 64, 16
INPUT_DIM = CORE_DIM + REL_DIM + SESSION_DIM + CONTEXT_DIM + PROVIDER_DIM
ACTIONS = len(CATALOGUE)
ENCODER = 'encoder/2'
# encoder/2: explicit one-hot slots (no hash collisions). Unused slots are reserved
# zeros so later encoder versions can add features without reshaping the decoder.
VOCAB = {
    'task_type': ('general', 'code_review', 'coding', 'support', 'creative', 'research'),
    'channel': ('terminal', 'chat', 'voice', 'background'),
    'stakes': ('low', 'medium', 'high'),
    'turn_origin': ('user', 'system', 'tool', 'subagent'),
    'tags': ('technical', 'review', 'sensitive', 'urgent', 'beginner', 'expert'),
}
PROVIDERS = ('openai', 'anthropic', 'google', 'qwen', 'other')
ADAPTER_BUCKETS = 8

class Policy(nn.Module):
    def __init__(self):
        super().__init__()
        self.network = nn.Sequential(nn.Linear(INPUT_DIM,128),nn.GELU(),nn.Linear(128,64),nn.GELU(),nn.Linear(64,ACTIONS))
    def forward(self,x):
        return self.network(x)

def context_features(context):
    x=torch.zeros(CONTEXT_DIM); offset=0
    for key,values in VOCAB.items():
        val=context.get(key)
        for v in val if isinstance(val,list) else [val]:
            if v in values: x[offset+values.index(v)]=1
        offset+=len(values)
    return x

def adapter_bucket(adapter_id):
    return int.from_bytes(hashlib.sha256(f'adapter:{adapter_id}'.encode()).digest()[:4],'big')%ADAPTER_BUCKETS

def provider_features(host):
    """Provider family and adapter are data features only; no host special cases."""
    x=torch.zeros(PROVIDER_DIM)
    family=host.get('provider_family','other')
    x[PROVIDERS.index(family if family in PROVIDERS else 'other')]=1
    x[len(PROVIDERS)+adapter_bucket(host.get('adapter_id','other'))]=1
    return x

def features(context,host):
    return torch.cat((context_features(context),provider_features(host)))

def inputs(core,rel,context,host,session=None):
    return torch.cat((core,rel,session if session is not None else torch.zeros(SESSION_DIM),features(context,host)))

def mask(context):
    """Fixed constraint layer. Index 0 (neutral fallback) is never masked."""
    m=torch.ones(ACTIONS,dtype=torch.bool); tags=context.get('tags',[])
    for i,c in enumerate(CATALOGUE):
        if (context.get('stakes')=='high' or 'sensitive' in tags) and c['humour']!='low': m[i]=False
        if 'urgent' in tags and c['verbosity']=='high': m[i]=False
    return m

def mask_reason(context):
    tags=context.get('tags',[]); reasons=[]
    if context.get('stakes')=='high' or 'sensitive' in tags: reasons.append('high_stakes_or_sensitive')
    if 'urgent' in tags: reasons.append('urgent')
    return ','.join(reasons) or None

def digest(path):
    return 'sha256:'+hashlib.sha256(Path(path).read_bytes()).hexdigest()

class Decoder:
    def __init__(self,path):
        self.path=Path(path); self.model=None; self.hash='untrained'; self.meta={}
        manifest=self.path.with_suffix('.json')
        if self.path.exists() and manifest.exists():
            meta=json.loads(manifest.read_text())
            if meta['hash']!=digest(self.path): raise ValueError('decoder checksum mismatch')
            if meta.get('encoder')!=ENCODER or meta.get('actions')!=ACTIONS: raise ValueError('decoder incompatible with encoder/catalogue')
            self.model=Policy(); self.model.load_state_dict(load_file(str(self.path))); self.model.eval()
            for p in self.model.parameters(): p.requires_grad_(False)
            self.hash=meta['hash']; self.meta=meta
    def logits(self,core,rel,context,host):
        if self.model is None: return torch.zeros(ACTIONS).masked_fill(~mask(context),float('-inf'))
        return self.model(inputs(core,rel,context,host)).masked_fill(~mask(context),float('-inf'))
    def diagnostics(self,core,rel,context,host):
        """Probability-weighted trait levels (0=low..2=high). Decoder outputs, not latent axes."""
        probs=torch.softmax(self.logits(core,rel,context,host),0)
        level={'low':0.0,'moderate':1.0,'high':2.0}
        return {t:round(float(sum(probs[i]*level[c[t]] for i,c in enumerate(CATALOGUE))),3) for t in CATALOGUE[0]}
