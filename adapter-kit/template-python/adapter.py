"""Custom host callback example; not a native automatic lifecycle integration."""
from sdk.python.client import Client

def prepare(client:Client,canonical_request:dict,append_context,mode='shadow'):
    result=client.express(canonical_request,mode)
    if result['text']:append_context(result['text'])
    return result

# Offer sdk.python.lite.TOOL to the model in active mode; route its calls here.
def persona_feedback(client:Client,last_result:dict,arguments:dict):
    decision=(last_result or {}).get('decision') or {}
    if not decision.get('decision_id'):return 'Not recorded: no persona decision for this turn.'
    try:client.reflect(decision['decision_id'],arguments.get('adjustments'),arguments.get('reason'));return 'Recorded.'
    except Exception as exc:return f'Not recorded: {exc}'[:200]
