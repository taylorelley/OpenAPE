"""SQLite WAL ledger and content-addressed safetensors. One process/replica only."""
import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
import torch
from safetensors.torch import save, load

class Store:
    def __init__(self,root):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.artifacts=self.root/'artifacts'; self.artifacts.mkdir(exist_ok=True)
        self.lock=threading.RLock()
        self.db=sqlite3.connect(self.root/'openape.sqlite',check_same_thread=False,isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS personas(tenant TEXT,id TEXT,active TEXT,initialization TEXT,PRIMARY KEY(tenant,id));
        CREATE TABLE IF NOT EXISTS versions(tenant TEXT,persona TEXT,id TEXT,hash TEXT,parent TEXT,scope TEXT,user_id TEXT,PRIMARY KEY(tenant,persona,id));
        CREATE TABLE IF NOT EXISTS relationships(tenant TEXT,persona TEXT,user_id TEXT,active TEXT,PRIMARY KEY(tenant,persona,user_id));
        CREATE TABLE IF NOT EXISTS sessions(tenant TEXT,persona TEXT,user_id TEXT,adapter TEXT,id TEXT,version TEXT,rel_version TEXT,decoder TEXT,PRIMARY KEY(tenant,persona,user_id,adapter,id));
        CREATE TABLE IF NOT EXISTS decisions(tenant TEXT,id TEXT,persona TEXT,user_id TEXT,actor TEXT,data TEXT,PRIMARY KEY(tenant,id));
        CREATE TABLE IF NOT EXISTS requests(tenant TEXT,persona TEXT,actor TEXT,id TEXT,decision TEXT,fingerprint TEXT,PRIMARY KEY(tenant,persona,actor,id));
        CREATE TABLE IF NOT EXISTS feedback(tenant TEXT,id TEXT,persona TEXT,user_id TEXT,actor TEXT,data TEXT,valid INTEGER DEFAULT 1,PRIMARY KEY(tenant,id));
        CREATE TABLE IF NOT EXISTS observations(tenant TEXT,adapter TEXT,id TEXT,persona TEXT,data TEXT,PRIMARY KEY(tenant,adapter,id));
        CREATE TABLE IF NOT EXISTS jobs(tenant TEXT,id TEXT,persona TEXT,status TEXT,data TEXT,PRIMARY KEY(tenant,id));
        CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY,tenant TEXT,persona TEXT,action TEXT,data TEXT);
        CREATE TABLE IF NOT EXISTS experience(tenant TEXT,persona TEXT,user_id TEXT,adapter TEXT,session TEXT,PRIMARY KEY(tenant,persona,user_id,adapter,session));
        CREATE TABLE IF NOT EXISTS maturation(tenant TEXT,persona TEXT,user_id TEXT,experience INTEGER DEFAULT 0,last_m REAL DEFAULT 0,last_decision INTEGER DEFAULT 0,PRIMARY KEY(tenant,persona,user_id));
        ''')
        self.db.row_factory=sqlite3.Row
        # Additive migrations from the 0.1.0 schema. Lineage columns drive revocation.
        # Personas from 0.2.0 keep manual evolution and no agent feedback until changed.
        for table,column,decl in (('personas','parent','TEXT'),('versions','job','TEXT'),('versions','core_base','TEXT'),('versions','revoked','INTEGER DEFAULT 0'),
                ('personas','archetype','TEXT'),('personas','seeds',"TEXT DEFAULT '[]'"),('personas','evolution',"TEXT DEFAULT 'manual'"),('personas','maturation','TEXT'),('personas','agent_feedback','INTEGER DEFAULT 0')):
            if column not in {r['name'] for r in self.db.execute(f'PRAGMA table_info({table})')}:
                self.db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {decl}')
    @contextmanager
    def tx(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield self.db
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK'); raise
    def one(self,sql,args=()):
        with self.lock: return self.db.execute(sql,args).fetchone()
    def all(self,sql,args=()):
        with self.lock: return self.db.execute(sql,args).fetchall()
    def put(self,tensor):
        raw=save({'latent':tensor.detach().float().contiguous()})
        h=hashlib.sha256(raw).hexdigest(); p=self.artifacts/(h+'.safetensors')
        if not p.exists():
            tmp=self.artifacts/(h+f'.{os.getpid()}.{threading.get_ident()}.tmp'); tmp.write_bytes(raw); os.replace(tmp,p)
        return h
    def get(self,h,dim):
        if len(h)!=64 or any(c not in '0123456789abcdef' for c in h): raise ValueError('invalid artifact hash')
        raw=(self.artifacts/(h+'.safetensors')).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=h: raise ValueError('artifact checksum mismatch')
        x=load(raw)['latent']
        if x.shape!=(dim,) or not torch.isfinite(x).all(): raise ValueError('invalid latent')
        return x
    def audit(self,db,tenant,persona,action,data):
        db.execute('INSERT INTO audit(tenant,persona,action,data) VALUES(?,?,?,?)',(tenant,persona,action,json.dumps(data)))
    def gc(self):
        """Only invoke while holding a write transaction."""
        used={r['hash'] for r in self.db.execute('SELECT hash FROM versions WHERE revoked=0')}
        for row in self.db.execute('SELECT data FROM jobs'):
            artifact=json.loads(row['data']).get('artifact')
            if artifact:used.add(artifact)
        for p in self.artifacts.glob('*.safetensors'):
            if p.stem not in used: p.unlink(missing_ok=True)
