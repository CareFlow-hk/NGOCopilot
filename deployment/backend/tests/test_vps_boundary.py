import pytest
from fastapi.testclient import TestClient
from ngopilot_gateway.config import Settings
from ngopilot_gateway.local import create_local_app, LOCAL_OWNER


def test_https_cookie_ticket_and_origin(tmp_path, monkeypatch):
    monkeypatch.setenv('NGOPILOT_HTTPS_DEPLOYMENT', 'true')
    monkeypatch.delenv('NGOPILOT_SCHEDULER_URL', raising=False)
    origin = 'https://pilot.example.org'
    settings = Settings(app_env='local', data_root=tmp_path, public_api_url=origin)
    app = create_local_app(settings, tmp_path)
    with TestClient(app, base_url=origin, headers={'Origin': origin}) as client:
        token = app.state.accounts.bootstrap('admin@example.org', 'Admin', LOCAL_OWNER)
        password = 'a sufficiently long test password'
        assert client.post('/api/auth/set-password', json={'token': token, 'password': password}).status_code == 200
        response = client.post('/api/auth/login', json={'email': 'admin@example.org', 'password': password})
        assert response.status_code == 200
        assert 'Secure' in response.headers['set-cookie']
        assert 'HttpOnly' in response.headers['set-cookie']
        assert response.headers['strict-transport-security'] == 'max-age=31536000'
        assert client.post('/api/ws-tickets').json()['url'].startswith('wss://pilot.example.org/acp?ticket=')
        assert client.post('/api/ws-tickets', headers={'Origin': 'https://evil.example'}).status_code == 403
        assert client.get('/api/auth/me', headers={'Host': 'evil.example'}).status_code == 403


def test_public_http_and_shared_scheduler_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('NGOPILOT_HTTPS_DEPLOYMENT', 'true')
    with pytest.raises(ValueError, match='HTTPS'):
        create_local_app(Settings(app_env='local', data_root=tmp_path, public_api_url='http://pilot.example.org'), tmp_path)
    monkeypatch.setenv('NGOPILOT_SCHEDULER_URL', 'http://scheduler:8311')
    with pytest.raises(ValueError, match='Shared Scheduler'):
        create_local_app(Settings(app_env='local', data_root=tmp_path, public_api_url='https://pilot.example.org'), tmp_path)
