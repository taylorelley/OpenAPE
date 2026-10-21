"""Custom host callback example; not a native automatic lifecycle integration."""
from sdk.python.client import Client

def prepare(client:Client,canonical_request:dict,append_context,mode='shadow'):
    result=client.express(canonical_request,mode)
    if result['text']:append_context(result['text'])
    return result
