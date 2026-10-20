# Dependency upgrade verification

These tests mutate users, MFA settings and branding in a disposable local app
database. Never run them against an installation with real data. They do not
contact LDAP, Azure AD, NPM or customer instances.

From PowerShell, build and start a fresh container in Docker Desktop:

```powershell
docker build -t netbird-msp:security-test .
$testSecret = python -c 'import secrets; print(secrets.token_hex(32))'
docker run -d --name netbird-msp-security-test -p 127.0.0.1:18000:8000 -e "SECRET_KEY=$testSecret" netbird-msp:security-test
docker cp integration_tests netbird-msp-security-test:/tmp/integration_tests
docker exec netbird-msp-security-test curl -fsS http://localhost:8000/api/health
docker exec -e SECURITY_UPGRADE_TEST=1 netbird-msp-security-test python -m pytest -q /tmp/integration_tests
docker exec netbird-msp-security-test pip check
```

Wait for the HTTP healthcheck to succeed before running pytest. Restart the
container before repeating the suite so the login rate limiter resets. The
container has no application data mounts or host Docker socket. Its fresh
database is created by the real application startup and migration code.

The suite exercises HTTP login, token rejection, MFA enrollment and verification,
database-backed API queries, input validation, settings changes, multipart logo
uploads and size checks, static files, OpenAPI generation, rate limiting, and
urlencoded form resource limits. It also exercises the real Docker SDK and
Requests/urllib3 Unix socket transport against a private fake Docker API,
including container create/start/remove requests. That transport test does not
prove compatibility with a live Docker daemon or external integrations.

For an explicitly approved local Docker Desktop lifecycle check, use:

```powershell
docker run --rm -e DOCKER_INTEGRATION_TEST=1 -v /var/run/docker.sock:/var/run/docker.sock -v "${PWD}/integration_tests:/tmp/integration_tests:ro" netbird-msp:security-test python -m pytest -q -p no:cacheprovider /tmp/integration_tests -k live_docker
```

This opt-in test uses the application's Docker client to create, inspect, start,
wait for, read logs from and remove one uniquely named test container. That child
container has no network or host mounts and runs as an unprivileged user. The
test runner itself can control Docker through the host socket, so only run this
command against a local test daemon after approving that access. Leave
`DOCKER_INTEGRATION_TEST` unset for the regular suite.

Audit both the declared requirements and the exact installed package versions
with `pip-audit`. Keep the scanner outside the app container so its dependencies
cannot change the application environment. For example:

```powershell
docker run --rm -v "${PWD}:/src:ro" python:3.11-slim sh -c 'pip install -q pip-audit && pip-audit -r /src/requirements.txt --progress-spinner off'
$installedPackages = docker exec netbird-msp-security-test pip freeze
if ($LASTEXITCODE -ne 0) { throw 'Could not read installed packages' }
$installedPackages | docker run --rm -i python:3.11-slim sh -c 'cat > /tmp/installed.txt; pip install -q pip-audit && pip-audit -r /tmp/installed.txt --progress-spinner off'
```

When finished, remove only this test container:

```powershell
docker rm -f netbird-msp-security-test
```
