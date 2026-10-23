"""The ledger and content-addressed safetensors artifacts.

Two backends share one schema and the engine's SQL:

* SQLite (default): a WAL database and an artifacts directory under the data
  directory. One process.
* PostgreSQL (OPENAPE_DATABASE_URL=postgresql://...): several replicas share one
  database. Artifacts live in a table so every replica reads the same bytes, and each
  write transaction takes one transaction-scoped advisory lock, so writes serialize
  across replicas exactly as SQLite's BEGIN IMMEDIATE serializes them in one process.
  The engine's SQLite idioms (? placeholders, INSERT OR IGNORE/REPLACE, json_extract,
  json_each, IS ?, rowid) are translated once per statement by `translate`.
"""
import functools
import hashlib
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
import torch
from safetensors.torch import save, load

# Version 3 holds personas for behaviour-controls/2 and decoder-v3. Older stores hold
# latents for another decoder and must be reset (`openape migrate --reset`) first.
SCHEMA = 'openape-store/3'
# (table, [(column, declaration)], primary key). Columns added after 0.1.0 are in
# MIGRATIONS, appended in order, so both backends keep SQLite's column order.
TABLES = (
    ('personas', [('tenant', 'TEXT'), ('id', 'TEXT'), ('active', 'TEXT'), ('initialization', 'TEXT')], ('tenant', 'id')),
    ('versions', [('tenant', 'TEXT'), ('persona', 'TEXT'), ('id', 'TEXT'), ('hash', 'TEXT'), ('parent', 'TEXT'), ('scope', 'TEXT'), ('user_id', 'TEXT')], ('tenant', 'persona', 'id')),
    ('relationships', [('tenant', 'TEXT'), ('persona', 'TEXT'), ('user_id', 'TEXT'), ('active', 'TEXT')], ('tenant', 'persona', 'user_id')),
    ('sessions', [('tenant', 'TEXT'), ('persona', 'TEXT'), ('user_id', 'TEXT'), ('adapter', 'TEXT'), ('id', 'TEXT'), ('version', 'TEXT'), ('rel_version', 'TEXT'), ('decoder', 'TEXT')], ('tenant', 'persona', 'user_id', 'adapter', 'id')),
    ('decisions', [('tenant', 'TEXT'), ('id', 'TEXT'), ('persona', 'TEXT'), ('user_id', 'TEXT'), ('actor', 'TEXT'), ('data', 'TEXT')], ('tenant', 'id')),
    ('requests', [('tenant', 'TEXT'), ('persona', 'TEXT'), ('actor', 'TEXT'), ('id', 'TEXT'), ('decision', 'TEXT'), ('fingerprint', 'TEXT')], ('tenant', 'persona', 'actor', 'id')),
    ('feedback', [('tenant', 'TEXT'), ('id', 'TEXT'), ('persona', 'TEXT'), ('user_id', 'TEXT'), ('actor', 'TEXT'), ('data', 'TEXT'), ('valid', 'INTEGER DEFAULT 1')], ('tenant', 'id')),
    ('observations', [('tenant', 'TEXT'), ('adapter', 'TEXT'), ('id', 'TEXT'), ('persona', 'TEXT'), ('data', 'TEXT')], ('tenant', 'adapter', 'id')),
    ('jobs', [('tenant', 'TEXT'), ('id', 'TEXT'), ('persona', 'TEXT'), ('status', 'TEXT'), ('data', 'TEXT')], ('tenant', 'id')),
    ('audit', [('seq', 'INTEGER PRIMARY KEY'), ('tenant', 'TEXT'), ('persona', 'TEXT'), ('action', 'TEXT'), ('data', 'TEXT')], None),
    ('experience', [('tenant', 'TEXT'), ('persona', 'TEXT'), ('user_id', 'TEXT'), ('adapter', 'TEXT'), ('session', 'TEXT')], ('tenant', 'persona', 'user_id', 'adapter', 'session')),
    ('maturation', [('tenant', 'TEXT'), ('persona', 'TEXT'), ('user_id', 'TEXT'), ('experience', 'INTEGER DEFAULT 0'), ('last_m', 'REAL DEFAULT 0'), ('last_decision', 'INTEGER DEFAULT 0')], ('tenant', 'persona', 'user_id')),
    ('states', [('tenant', 'TEXT'), ('persona', 'TEXT'), ('user_id', 'TEXT'), ('adapter', 'TEXT'), ('session', 'TEXT'), ('delta', 'TEXT'), ('feedback', 'TEXT'), ('updates', 'INTEGER')], ('tenant', 'persona', 'user_id', 'adapter', 'session')),
    ('samples', [('tenant', 'TEXT'), ('persona', 'TEXT'), ('user_id', 'TEXT'), ('session', 'TEXT'), ('delta', 'TEXT'), ('feedback', 'TEXT'), ('consumed', 'INTEGER DEFAULT 0')], None),
    ('meta', [('key', 'TEXT PRIMARY KEY'), ('value', 'TEXT')], None),
    ('user_settings', [('tenant', 'TEXT'), ('persona', 'TEXT'), ('user_id', 'TEXT'), ('data', 'TEXT'), ('updated', 'TEXT')], ('tenant', 'persona', 'user_id')),
)
# Additive migrations from the 0.1.0 schema. Lineage columns drive revocation.
# Personas from 0.2.0 keep manual evolution and no agent feedback until changed.
MIGRATIONS = (('personas', 'parent', 'TEXT'), ('versions', 'job', 'TEXT'), ('versions', 'core_base', 'TEXT'), ('versions', 'revoked', 'INTEGER DEFAULT 0'),
    ('personas', 'archetype', 'TEXT'), ('personas', 'seeds', "TEXT DEFAULT '[]'"), ('personas', 'evolution', "TEXT DEFAULT 'manual'"), ('personas', 'maturation', 'TEXT'),
    ('personas', 'agent_feedback', 'INTEGER DEFAULT 0'), ('personas', 'temperament', 'TEXT'), ('personas', 'individuality', 'TEXT'), ('maturation', 'effective', 'REAL'),
    ('maturation', 'last_e', 'REAL DEFAULT 0'), ('maturation', 'life', 'TEXT'), ('maturation', 'anchor', 'TEXT'), ('sessions', 'turns', 'INTEGER DEFAULT 0'), ('states', 'habits', 'TEXT'))
COLUMNS = {t: [c for c, _ in cols] + [c for tt, c, _ in MIGRATIONS if tt == t] for t, cols, _ in TABLES}
KEYS = {t: list(pk) if pk else [cols[0][0]] for t, cols, pk in TABLES}

def pg_type(declaration):
    return declaration.replace('INTEGER PRIMARY KEY', 'BIGSERIAL PRIMARY KEY').replace('INTEGER', 'BIGINT').replace('REAL', 'DOUBLE PRECISION')

def ddl(table, cols, pk, postgres=False):
    body = [f'{c} {pg_type(d) if postgres else d}' for c, d in cols] + ([f'PRIMARY KEY({",".join(pk)})'] if pk else [])
    return f'CREATE TABLE IF NOT EXISTS {table}({",".join(body)})'

def _values_count(sql, start):
    depth, count, i = 0, 1, start
    while i < len(sql):
        ch = sql[i]
        if ch == '(': depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0: return count, i
        elif ch == ',' and depth == 1: count += 1
        elif ch == "'": i = sql.index("'", i + 1)
        i += 1
    raise ValueError('unbalanced VALUES')

@functools.lru_cache(maxsize=1024)
def translate(sql):
    """The engine's SQLite SQL as PostgreSQL (placeholders stay `?` until execute)."""
    q = re.sub(r"json_extract\(([\w.]+),\s*'\$\.([\w.]+)'\)", lambda m: f"({m.group(1)}::jsonb #>> '{{{m.group(2).replace('.', ',')}}}')", sql)
    q = re.sub(r'json_each\(([\w.]+)\)', r'jsonb_array_elements_text(\1::jsonb) AS je(value)', q)
    q = re.sub(r'\bIS \?', 'IS NOT DISTINCT FROM ?', q)
    m = re.match(r'\s*INSERT\s+(OR\s+(IGNORE|REPLACE)\s+)?INTO\s+(\w+)\s*(\(([^)]*)\))?\s*VALUES\s*', q, re.I)
    if m:
        table, mode = m.group(3), (m.group(2) or '').upper()
        n, end = _values_count(q, m.end())
        cols = [c.strip() for c in m.group(5).split(',')] if m.group(5) else COLUMNS[table][:n]
        q = f'INSERT INTO {table}({",".join(cols)}) VALUES' + q[m.end():end + 1] + q[end + 1:]
        if mode == 'IGNORE': q += ' ON CONFLICT DO NOTHING'
        elif mode == 'REPLACE':
            rest = [c for c in cols if c not in KEYS[table]]
            q += f' ON CONFLICT ({",".join(KEYS[table])}) ' + (f'DO UPDATE SET {",".join(f"{c}=EXCLUDED.{c}" for c in rest)}' if rest else 'DO NOTHING')
    return q

class Row(dict):
    """A result row readable by column name or position, like sqlite3.Row."""
    __slots__ = ('_values',)
    def __init__(self, names, values):
        super().__init__(zip(names, values)); self._values = tuple(values)
    def __getitem__(self, key):
        return self._values[key] if isinstance(key, int) else super().__getitem__(key)
    def keys(self): return list(super().keys())

class Postgres:
    """A psycopg connection with SQLite's execute() interface over the engine's SQL."""
    LOCK = 0x0a7e  # one advisory lock key serializes write transactions across replicas
    def __init__(self, url, schema):
        import psycopg
        if not re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', schema): raise ValueError('OPENAPE_DATABASE_SCHEMA must be a lower-case identifier')
        def rows(cursor):
            names = [c.name for c in cursor.description] if cursor.description else []
            return lambda values: Row(names, values)
        self.conn = psycopg.connect(url, autocommit=True, row_factory=rows)
        self.conn.execute(f'CREATE SCHEMA IF NOT EXISTS {schema}'); self.conn.execute(f'SET search_path TO {schema}')
    def execute(self, sql, args=()):
        q = translate(sql)
        if args: q = q.replace('%', '%%').replace('?', '%s')
        return self.conn.execute(q, tuple(args) if args else None)
    def begin(self):
        self.conn.execute('BEGIN'); self.conn.execute('SELECT pg_advisory_xact_lock(%s)', (self.LOCK,))
    def close(self): self.conn.close()

class Store:
    def __init__(self,root,database_url=None,schema=None):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        url=database_url or os.environ.get('OPENAPE_DATABASE_URL')
        self.postgres=bool(url)
        if self.postgres:
            self.db=Postgres(url,schema or os.environ.get('OPENAPE_DATABASE_SCHEMA','openape'));self.artifacts=None
            with self.lock:
                self.db.begin()
                try:
                    for table,cols,pk in TABLES:self.db.conn.execute(ddl(table,cols,pk,True))
                    for table,column,decl in MIGRATIONS:self.db.conn.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {pg_type(decl)}')
                    for table,_,_ in TABLES:
                        if table!='audit':self.db.conn.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS rowid BIGSERIAL')
                    self.db.conn.execute('CREATE TABLE IF NOT EXISTS artifacts(hash TEXT PRIMARY KEY,data BYTEA NOT NULL)')
                    self.db.conn.execute('COMMIT')
                except BaseException:
                    self.db.conn.execute('ROLLBACK');raise
        else:
            self.artifacts=self.root/'artifacts'; self.artifacts.mkdir(exist_ok=True)
            self.db=sqlite3.connect(self.root/'openape.sqlite',check_same_thread=False,isolation_level=None)
            self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA foreign_keys=ON')
            self.db.executescript(';\n'.join(ddl(t,c,k) for t,c,k in TABLES)+';')
            self.db.row_factory=sqlite3.Row
            for table,column,decl in MIGRATIONS:
                if column not in {r['name'] for r in self.db.execute(f'PRAGMA table_info({table})')}:
                    self.db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {decl}')
        # Experience recorded before effective experience counts one unit per session.
        self.db.execute('UPDATE maturation SET effective=experience WHERE effective IS NULL')
        row=self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if not row and not self.db.execute('SELECT 1 FROM personas LIMIT 1').fetchone():
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('schema',?)",(SCHEMA,));row={'value':SCHEMA}
        self.legacy=row is None or row['value']!=SCHEMA
    @contextmanager
    def tx(self):
        with self.lock:
            if self.postgres:self.db.begin()
            else:self.db.execute('BEGIN IMMEDIATE')
            try:
                yield self.db
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK'); raise
    def one(self,sql,args=()):
        with self.lock: return self.db.execute(sql,args).fetchone()
    def all(self,sql,args=()):
        with self.lock: return self.db.execute(sql,args).fetchall()
    def put(self,tensor,habit_bias=None):
        """Store a latent (and optionally the version's habit bias) content-addressed."""
        tensors={'latent':tensor.detach().float().contiguous()}
        if habit_bias is not None and bool(habit_bias.abs().sum()>0):tensors['habit_bias']=habit_bias.detach().float().contiguous()
        raw=save(tensors);h=hashlib.sha256(raw).hexdigest()
        if self.postgres:
            with self.lock:self.db.execute('INSERT OR IGNORE INTO artifacts(hash,data) VALUES(?,?)',(h,raw))
            return h
        p=self.artifacts/(h+'.safetensors')
        if not p.exists():
            tmp=self.artifacts/(h+f'.{os.getpid()}.{threading.get_ident()}.tmp'); tmp.write_bytes(raw); os.replace(tmp,p)
        return h
    def raw(self,h):
        """Verified artifact bytes."""
        if len(h)!=64 or any(c not in '0123456789abcdef' for c in h): raise ValueError('invalid artifact hash')
        if self.postgres:
            row=self.one('SELECT data FROM artifacts WHERE hash=?',(h,))
            if row is None:raise FileNotFoundError(h)
            raw=bytes(row['data'])
        else:raw=(self.artifacts/(h+'.safetensors')).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=h: raise ValueError('artifact checksum mismatch')
        return raw
    def get(self,h,dim):
        x=load(self.raw(h))['latent']
        if x.shape!=(dim,) or not torch.isfinite(x).all(): raise ValueError('invalid latent')
        return x
    def get_habit_bias(self,h,size):
        """The version's habit bias (zeros when it has none)."""
        b=load(self.raw(h)).get('habit_bias')
        if b is None: return torch.zeros(size)
        if b.shape!=(size,) or not torch.isfinite(b).all(): raise ValueError('invalid habit bias')
        return b
    def audit(self,db,tenant,persona,action,data):
        db.execute('INSERT INTO audit(tenant,persona,action,data) VALUES(?,?,?,?)',(tenant,persona,action,json.dumps(data)))
    def gc(self):
        """Only invoke while holding a write transaction."""
        used={r['hash'] for r in self.db.execute('SELECT hash FROM versions WHERE revoked=0')}
        for row in self.db.execute('SELECT data FROM jobs'):
            artifact=json.loads(row['data']).get('artifact')
            if artifact:used.add(artifact)
        if self.postgres:
            stale=[r['hash'] for r in self.db.execute('SELECT hash FROM artifacts') if r['hash'] not in used]
            if stale:self.db.conn.execute('DELETE FROM artifacts WHERE hash = ANY(%s)',(stale,))
            return
        for p in self.artifacts.glob('*.safetensors'):
            if p.stem not in used: p.unlink(missing_ok=True)
    def close(self):
        self.db.close()
