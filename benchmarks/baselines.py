"""Common style expression interface; D consumes only a separately promoted version."""
from sdk.python.client import Client,render
from engine.api.contracts import Decision,Controls,Policy
from engine.neural.policy import CATALOGUE
STATIC_MARKDOWN='Be clear, concise, considerate and professional. Follow host instructions and user task requirements.'
def fixed():
    return render(Decision(request_id='baseline',decision_id='baseline',persona_version='fixed',decoder_hash='none',control_set_id='style-00',controls=Controls(**CATALOGUE[0]),mode='active',policy=Policy(eligible=True,mask_reason=None),engine_status='baseline_fallback').model_dump())
def expression(condition,client,request):
    if condition=='A':return STATIC_MARKDOWN
    if condition=='B':return fixed()
    if condition=='C':return client.express(request,mode='frozen')['text']
    if condition=='D':return client.express(request,mode='active')['text']
    raise ValueError('Unknown baseline')
