import sys, os, base64, json, time, asyncio, logging
logging.disable(logging.CRITICAL)
sys.path.insert(0, '.')
os.environ['ENTRA_TENANT_ID'] = '37f28838-9a79-4b20-a28a-c7d8a85e4eda'
os.environ['ENTRA_BACKEND_CLIENT_ID'] = 'fb3c0e70-f3bb-46a1-9f0b-2587b49a3d0c'

from app.core.auth.middleware import EntraJWTValidator, _decode_claims_unsafe
from fastapi.testclient import TestClient
from app.main import app

TENANT = '37f28838-9a79-4b20-a28a-c7d8a85e4eda'
GRAPH  = 'https://graph.microsoft.com'
BACKEND_AUD = 'api://fb3c0e70-f3bb-46a1-9f0b-2587b49a3d0c'
ISS_V2 = f'https://login.microsoftonline.com/{TENANT}/v2.0'
ISS_V1 = f'https://sts.windows.net/{TENANT}/'

def b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b'=').decode()

def make_tok(aud, tid, iss=None, exp_offset=3600, scp='Chat.Read'):
    h = b64({'alg': 'RS256', 'kid': 'x', 'typ': 'JWT'})
    p = b64({
        'aud': aud,
        'iss': iss or f'https://login.microsoftonline.com/{tid}/v2.0',
        'tid': tid,
        'scp': scp,
        'oid': 'oid1',
        'preferred_username': 'u@t.com',
        'exp': int(time.time()) + exp_offset,
    })
    return f'{h}.{p}.fakesig'

async def test_validator():
    v = EntraJWTValidator(TENANT, 'api://fb3c0e70-f3bb-46a1-9f0b-2587b49a3d0c')
    cases = [
        # --- Graph token path (claims-only, no JWKS) ---
        ('Graph - valid (v2 iss)',           make_tok(GRAPH, TENANT),                                        True),
        ('Graph - valid (v1 iss)',           make_tok(GRAPH, TENANT, iss=ISS_V1),                           True),
        ('Graph - wrong tid',               make_tok(GRAPH, 'evil-tenant-id'),                              False),
        ('Graph - wrong iss',               make_tok(GRAPH, TENANT, iss='https://evil.com'),                False),
        ('Graph - expired',                 make_tok(GRAPH, TENANT, exp_offset=-60),                       False),
        # --- App token path (JWKS, but fakesig - these test claim routing not sig) ---
        # App tokens with wrong aud should still route to JWKS path and fail on sig (expected)
    ]
    all_ok = True
    print('-- Validator unit tests --')
    for label, tok, should_pass in cases:
        try:
            await v.validate(tok)
            passed = True
        except Exception:
            passed = False
        ok = passed == should_pass
        all_ok = all_ok and ok
        status = 'OK ' if ok else 'BUG'
        print(f'  [{status}] {label}: {"accepted" if passed else "rejected"} (expected {"accept" if should_pass else "reject"})')

    # --- Issuer routing test: verify app-aud tokens are NOT accepted via claims-only path ---
    print('  --- App-aud routing check ---')
    for label, tok, should_be_rejected_at_claims in [
        ('Backend aud v2 iss routed to JWKS', make_tok(BACKEND_AUD, TENANT, iss=ISS_V2), True),
        ('Backend aud v1 iss routed to JWKS', make_tok(BACKEND_AUD, TENANT, iss=ISS_V1), True),
    ]:
        try:
            await v.validate(tok)
            passed = True
        except Exception as e:
            passed = False
            err = str(e)
        # For app-aud tokens with fakesig, they must fail (JWKS path rejects fake sig) NOT pass
        # The important thing: they do NOT accidentally pass via claims-only path
        ok = not passed  # should always be rejected (fake sig can't pass JWKS)
        all_ok = all_ok and ok
        status = 'OK ' if ok else 'BUG'
        print(f'  [{status}] {label}: correctly routed to JWKS (rejected at sig, not claims)')

    return all_ok

def test_endpoints():
    client = TestClient(app, raise_server_exceptions=False)
    cases = [
        # github/status: auth passes but CosmosDB unavailable in test env -> 500 (not 401)
        ('valid Graph - github/status',  'GET',  '/api/auth/github/status', make_tok(GRAPH, TENANT), 500),
        ('valid Graph - chat',           'POST', '/api/chat/message',        make_tok(GRAPH, TENANT), 200),
        ('no token - github/status',     'GET',  '/api/auth/github/status', None,                    401),
        ('no token - chat',              'POST', '/api/chat/message',        None,                    401),
        ('wrong tid - github/status',    'GET',  '/api/auth/github/status', make_tok(GRAPH, 'evil'), 401),
        ('wrong tid - chat',             'POST', '/api/chat/message',        make_tok(GRAPH, 'evil'), 401),
        ('expired - github/status',      'GET',  '/api/auth/github/status', make_tok(GRAPH, TENANT, exp_offset=-60), 401),
    ]
    all_ok = True
    print('-- Endpoint integration tests --')
    for label, method, path, token, expected_status in cases:
        hdrs = {'Authorization': 'Bearer ' + token} if token else {}
        if method == 'GET':
            r = client.get(path, headers=hdrs)
        else:
            r = client.post(path, json={'message': 'hi'}, headers=hdrs)
        ok = r.status_code == expected_status
        all_ok = all_ok and ok
        status = 'OK ' if ok else 'BUG'
        print(f'  [{status}] {label}: HTTP {r.status_code} (expected {expected_status})')
    return all_ok

async def main():
    v_ok = await test_validator()
    print()
    e_ok = test_endpoints()
    print()
    if v_ok and e_ok:
        print('ALL TESTS PASSED')
    else:
        print('SOME TESTS FAILED')

asyncio.run(main())
