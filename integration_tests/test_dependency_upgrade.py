"""Run only in a disposable, running app container with an empty test database.

Set SECURITY_UPGRADE_TEST=1 and run python -m pytest against this directory.
The Docker transport test uses a private Unix socket, never the host daemon.
"""

import base64
import json
import os
import secrets
import socketserver
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler

import docker
import pyotp
import pytest
import requests


@pytest.fixture(scope="module")
def api():
    if os.environ.get("SECURITY_UPGRADE_TEST") != "1":
        pytest.skip("Requires an explicitly enabled disposable test container")
    from app.database import SessionLocal
    from app.models import User
    from app.utils.security import hash_password

    username = "upgrade-" + secrets.token_hex(6)
    password = secrets.token_urlsafe(24)
    with SessionLocal() as db:
        db.add(User(username=username, password_hash=hash_password(password), role="admin"))
        db.commit()
    session = requests.Session()
    session.trust_env = False

    def call(method, path, **kwargs):
        return session.request(method, "http://127.0.0.1:8000" + path, timeout=15, **kwargs)

    credentials = {"username": username, "password": password}
    login = call("POST", "/api/auth/login", json=credentials)
    assert login.status_code == 200, login.text
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    yield call, credentials, headers
    session.close()


def test_startup_frontend_and_openapi(api):
    call, _, _ = api
    assert call("GET", "/api/health").json()["status"] == "ok"
    response = call("GET", "/")
    assert response.status_code == 200
    assert "window.STATIC_VERSION" in response.text
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert call("GET", "/static/js/app.js").status_code == 200
    schema = call("GET", "/api/openapi.json")
    assert schema.status_code == 200, schema.text
    assert "/api/auth/login" in schema.json()["paths"]


def test_authentication_and_invalid_tokens(api):
    from app.dependencies import create_access_token

    call, credentials, headers = api
    assert call("GET", "/api/auth/me").status_code == 401
    assert call("GET", "/api/auth/me", headers=headers).json()["username"] == credentials["username"]
    wrong = {**credentials, "password": "wrong-password"}
    assert call("POST", "/api/auth/login", json=wrong).status_code == 401
    expired = create_access_token(credentials["username"], timedelta(seconds=-60))
    for token in (expired, headers["Authorization"][7:] + "tampered", "invalid.token.value"):
        assert call("GET", "/api/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 401


def test_database_queries_validation_and_settings(api):
    call, _, headers = api
    response = call("GET", "/api/customers?sort_order=desc", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    assert call("GET", "/api/customers?per_page=0", headers=headers).status_code == 422
    assert call("GET", "/api/customers?sort_order=invalid", headers=headers).status_code == 422
    response = call("PUT", "/api/settings/system", headers=headers,
                    json={"branding_name": "Dependency upgrade test"})
    assert response.status_code == 200, response.text
    assert call("GET", "/api/settings/branding").json()["branding_name"] == "Dependency upgrade test"


def test_multipart_logo_upload(api):
    call, _, headers = api
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9uoAAAAASUVORK5CYII=")
    response = call("POST", "/api/settings/branding/logo", headers=headers,
                    files={"file": ("test.png", png, "image/png")})
    assert response.status_code == 200, response.text
    assert call("GET", response.json()["branding_logo_path"]).content == png
    oversized = call("POST", "/api/settings/branding/logo", headers=headers,
                     files={"file": ("large.png", b"x" * 600_000, "image/png")})
    assert oversized.status_code == 400
    assert call("DELETE", "/api/settings/branding/logo", headers=headers).status_code == 200


def test_mfa_enrollment_and_login(api):
    from app.database import SessionLocal
    from app.models import SystemConfig

    call, credentials, _ = api
    with SessionLocal() as db:
        db.get(SystemConfig, 1).mfa_enabled = True
        db.commit()
    try:
        login = call("POST", "/api/auth/login", json=credentials).json()
        assert login["mfa_required"] is True
        assert login["totp_setup_needed"] is True
        setup = call("POST", "/api/auth/mfa/setup", json={"mfa_token": login["mfa_token"]})
        assert setup.status_code == 200, setup.text
        totp = pyotp.TOTP(setup.json()["secret"])
        enrolled = call("POST", "/api/auth/mfa/setup/complete",
                        json={"mfa_token": login["mfa_token"], "totp_code": totp.now()})
        assert enrolled.status_code == 200, enrolled.text
        login = call("POST", "/api/auth/login", json=credentials).json()
        assert login["totp_setup_needed"] is False
        payload = {"mfa_token": login["mfa_token"], "totp_code": totp.now()}
        verified = call("POST", "/api/auth/mfa/verify", json=payload)
        assert verified.status_code == 200, verified.text
        payload["mfa_token"] += "tampered"
        assert call("POST", "/api/auth/mfa/verify", json=payload).status_code == 401
    finally:
        with SessionLocal() as db:
            db.get(SystemConfig, 1).mfa_enabled = False
            db.commit()


def test_rate_limit_still_enforced(api):
    call, credentials, _ = api
    statuses = [call("POST", "/api/auth/login",
                     json={**credentials, "password": "wrong"}).status_code for _ in range(11)]
    assert 429 in statuses
    assert set(statuses) <= {401, 429}


def test_urlencoded_form_resource_limits():
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    async def form(request):
        async with request.form(max_fields=2, max_part_size=16) as data:
            return JSONResponse(dict(data))

    with TestClient(Starlette(routes=[Route("/form", form, methods=["POST"])])) as client:
        assert client.post("/form", data={"a": "ok"}).status_code == 200
        assert client.post("/form", data={"a": "1", "b": "2", "c": "3"}).status_code == 400
        assert client.post("/form", data={"a": "x" * 32}).status_code == 400


def test_docker_sdk_unix_socket_transport(tmp_path):
    """Exercise real Requests/urllib3 Unix transport, using a fake Docker API."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_request(self):
            seen.append((self.command, self.path))
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            status, response = 200, {}
            if self.path == "/version":
                response = {"ApiVersion": "1.51", "MinAPIVersion": "1.24"}
            elif self.path == "/v1.51/containers/json?limit=-1&all=0&size=0&trunc_cmd=0":
                response = []
            elif self.path.startswith("/v1.51/containers/create?"):
                assert json.loads(body)["Image"] == "transport-test:local"
                status, response = 201, {"Id": "test-container", "Warnings": []}
            elif self.path == "/v1.51/containers/test-container/start":
                status = 204
            elif self.path.startswith("/v1.51/containers/test-container?") and self.command == "DELETE":
                status = 204
            else:
                status, response = 404, {"message": "Unexpected test endpoint"}
            content = json.dumps(response).encode() if status != 204 else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        do_GET = do_POST = do_DELETE = handle_request

    path = str(tmp_path / "docker.sock")
    with socketserver.UnixStreamServer(path, Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = docker.DockerClient(base_url="unix://" + path)
            try:
                assert client.containers.list() == []
                created = client.api.create_container("transport-test:local", command=["true"], name="transport-test")
                assert created["Id"] == "test-container"
                client.api.start(created["Id"])
                client.api.remove_container(created["Id"], force=True)
            finally:
                client.close()
            assert len(seen) == 5
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_live_docker_container_lifecycle():
    """Opt-in local Docker Desktop check; removes only the container it creates."""
    if os.environ.get("DOCKER_INTEGRATION_TEST") != "1":
        pytest.skip("Live Docker socket access requires explicit opt-in")
    from app.services.docker_service import _get_client

    client = _get_client()
    name = "netbird-msp-sdk-test-" + secrets.token_hex(6)
    container = None
    try:
        assert client.ping()
        container = client.containers.create(
            os.environ.get("DOCKER_TEST_IMAGE", "netbird-msp:security-test"),
            command=["python", "-c", "print('docker-sdk-upgrade-ok')"],
            name=name,
            labels={"netbird-msp-test": "dependency-upgrade"},
            network_disabled=True,
            user="65534:65534",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
        )
        assert client.containers.get(name).id == container.id
        container.start()
        assert container.wait(timeout=30)["StatusCode"] == 0
        assert b"docker-sdk-upgrade-ok" in container.logs()
        container.reload()
        assert container.status == "exited"
    finally:
        if container is not None:
            container.remove(force=True)
