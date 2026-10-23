"""Reset a pre-0.3 store for behaviour-controls/2 and decoder-v3 (clean break).

Persona latents belong to the decoder that produced them, so learned state cannot be
carried across. Each persona is re-created as a new temperament version from its
recorded archetype, seed preferences and individuality seed (snapshot personas from
their parent's recorded archetype; imported personas start from the neutral prior).
Persona settings (evolution, maturation rate, agent feedback) are kept. Old
decisions, feedback, observations and the audit log stay as history; feedback is
marked invalid so it can never train the new decoder. Versions, relationships,
sessions, jobs, maturation records and session states are dropped.
"""
import json
import uuid
from engine.storage.store import Store, SCHEMA
from engine.neural.policy import Decoder, CORE_DIM
from engine.neural.profiles import fit_seed_latent, seed_profile
from engine.learning import development as dev

DROPPED = ('versions', 'relationships', 'sessions', 'requests', 'jobs', 'experience', 'maturation', 'states', 'samples')

def reset(data_dir, decoder_path):
    store = Store(data_dir)
    if not store.legacy:
        store.db.close(); return {'reset': False, 'reason': f'store already at {SCHEMA}', 'personas': []}
    decoder = Decoder(decoder_path)
    if decoder.model is None: raise ValueError('decoder-v3 weights required to re-create personas')
    personas = [dict(r) for r in store.all('SELECT * FROM personas')]
    latents = {}
    for r in personas:
        seeds = json.loads(r['seeds'] or '[]'); ind = json.loads(r['individuality'] or 'null')
        if r['archetype'] or seeds:
            profile = seed_profile(seeds, r['archetype'])
            if ind: profile = dev.individual_profile(profile, ind['seed'], ind['amount'])
            latents[(r['tenant'], r['id'])] = fit_seed_latent(decoder, seeds, profile=profile)
        else:
            latents[(r['tenant'], r['id'])] = fit_seed_latent(decoder, [])  # neutral prior
    report = []
    with store.tx() as db:
        for table in DROPPED: db.execute(f'DELETE FROM {table}')
        db.execute('UPDATE feedback SET valid=0')
        for r in personas:
            v = str(uuid.uuid4()); h = store.put(latents[(r['tenant'], r['id'])])
            db.execute('INSERT INTO versions(tenant,persona,id,hash,parent,scope,user_id,job,core_base) VALUES(?,?,?,?,?,?,?,?,?)', (r['tenant'], r['id'], v, h, None, 'core', None, None, None))
            db.execute('UPDATE personas SET active=?,temperament=? WHERE tenant=? AND id=?', (v, v, r['tenant'], r['id']))
            basis = 'archetype' if r['archetype'] else 'seed_preferences' if json.loads(r['seeds'] or '[]') else 'neutral_prior'
            store.audit(db, r['tenant'], r['id'], 'reset_for_decoder_v3', {'version': v, 'basis': basis, 'archetype': r['archetype'], 'decoder_hash': decoder.hash,
                'note': 'learned state from behaviour-controls/1 dropped; feedback kept as history only'})
            report.append({'tenant': r['tenant'], 'persona_id': r['id'], 'version': v, 'basis': basis})
        db.execute("INSERT OR REPLACE INTO meta VALUES('schema',?)", (SCHEMA,))
        store.gc()
    store.db.close()
    assert all(x.shape == (CORE_DIM,) for x in latents.values())
    return {'reset': True, 'schema': SCHEMA, 'decoder_hash': decoder.hash, 'personas': report}
