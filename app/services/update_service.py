"""Update management — version check and in-place update via git + docker compose."""

import json
import logging
import os
import shutil
import subprocess
import httpx
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

SOURCE_DIR = "/app-source"
VERSION_FILE = "/app/version.json"
BACKUP_DIR = "/app/backups"

logger = logging.getLogger(__name__)


def get_current_version() -> dict:
    """Read the version baked at build time from /app/version.json."""
    try:
        data = json.loads(Path(VERSION_FILE).read_text())
        return {
            "tag": data.get("tag", "unknown"),
            "commit": data.get("commit", "unknown"),
            "branch": data.get("branch", "unknown"),
            "date": data.get("date", "unknown"),
        }
    except Exception:
        return {"tag": "unknown", "commit": "unknown", "branch": "unknown", "date": "unknown"}


async def check_for_updates(config: Any) -> dict:
    """Query the Gitea API for the latest tag and commit on the configured branch.

    Parses the repo URL to build the Gitea API endpoint:
      https://git.example.com/owner/repo
      → https://git.example.com/api/v1/repos/owner/repo/...

    Uses tags for version comparison when available, falls back to commit SHAs.
    Returns dict with current, latest, needs_update, and optional error.
    """
    current = get_current_version()
    if not config.git_repo_url:
        return {
            "current": current,
            "latest": None,
            "needs_update": False,
            "error": "git_repo_url not configured",
        }

    repo_url = config.git_repo_url.rstrip("/")
    parts = repo_url.split("/")
    if len(parts) < 5:
        return {
            "current": current,
            "latest": None,
            "needs_update": False,
            "error": f"Cannot parse repo URL: {repo_url}",
        }

    base_url = "/".join(parts[:-2])
    owner = parts[-2]
    repo = parts[-1]
    branch = config.git_branch or "main"
    branch_api = f"{base_url}/api/v1/repos/{owner}/{repo}/branches/{branch}"
    tags_api = f"{base_url}/api/v1/repos/{owner}/{repo}/tags?limit=1"

    headers = {}
    if config.git_token:
        headers["Authorization"] = f"token {config.git_token}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Fetch branch info (latest commit)
            resp = await client.get(branch_api, headers=headers)
            if resp.status_code != 200:
                return {
                    "current": current,
                    "latest": None,
                    "needs_update": False,
                    "error": f"Gitea API returned HTTP {resp.status_code}",
                }
            data = resp.json()
            latest_commit = data.get("commit", {})
            full_sha = latest_commit.get("id", "unknown")
            short_sha = full_sha[:8] if full_sha != "unknown" else "unknown"

            # Fetch latest tag
            latest_tag = "unknown"
            try:
                tag_resp = await client.get(tags_api, headers=headers)
                if tag_resp.status_code == 200:
                    tags = tag_resp.json()
                    if tags and len(tags) > 0:
                        latest_tag = tags[0].get("name", "unknown")
            except Exception:
                pass  # Tag fetch is best-effort

            latest = {
                "tag": latest_tag,
                "commit": short_sha,
                "commit_full": full_sha,
                "message": latest_commit.get("commit", {}).get("message", "").split("\n")[0],
                "date": latest_commit.get("commit", {}).get("committer", {}).get("date", ""),
                "branch": branch,
            }

            # Determine if update is needed: prefer tag comparison, fallback to commit
            current_tag = current.get("tag", "unknown")
            current_sha = current.get("commit", "unknown")
            if current_tag != "unknown" and latest_tag != "unknown":
                needs_update = current_tag != latest_tag
            else:
                needs_update = (
                    current_sha != "unknown"
                    and short_sha != "unknown"
                    and current_sha != short_sha
                    and not full_sha.startswith(current_sha)
                )
            return {"current": current, "latest": latest, "needs_update": needs_update}
    except Exception as exc:
        return {
            "current": current,
            "latest": None,
            "needs_update": False,
            "error": str(exc),
        }


async def get_remote_branches(config: Any) -> list[str]:
    """Query the Gitea API for available branches on the configured repository.
    
    Returns a list of branch names (e.g., ['main', 'unstable', 'development']).
    If the repository URL is not configured or an error occurs, returns an empty list.
    """
    if not config.git_repo_url:
        return []

    repo_url = config.git_repo_url.rstrip("/")
    parts = repo_url.split("/")
    if len(parts) < 5:
        return []

    base_url = "/".join(parts[:-2])
    owner = parts[-2]
    repo = parts[-1]
    branches_api = f"{base_url}/api/v1/repos/{owner}/{repo}/branches?limit=100"

    headers = {}
    if config.git_token:
        headers["Authorization"] = f"token {config.git_token}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(branches_api, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return [branch.get("name") for branch in data if "name" in branch]
    except Exception as exc:
        logger.error("Error fetching branches: %s", exc)
        
    return []


def backup_database(db_path: str) -> str:
    """Create a timestamped backup of the SQLite database.

    Returns the backup file path.
    """
    Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{BACKUP_DIR}/netbird_msp_{timestamp}.db"
    shutil.copy2(db_path, backup_path)
    logger.info("Database backed up to %s", backup_path)
    return backup_path


def trigger_update(config: Any, db_path: str) -> dict:
    """Backup DB, git pull latest code, then fire-and-forget docker compose rebuild.

    Returns immediately after launching the rebuild. The container will restart
    in ~30-60 seconds causing a brief HTTP connection drop.

    Args:
        config: AppConfig with git_repo_url, git_branch, git_token.
        db_path: Absolute path to the SQLite database file.

    Returns:
        Dict with ok (bool), message, backup path, and pulled_branch.
    """
    # 1. Backup database before any changes
    try:
        backup_path = backup_database(db_path)
    except Exception as exc:
        logger.error("Database backup failed: %s", exc)
        return {"ok": False, "message": f"Database backup failed: {exc}", "backup": None}

    # 2. Build git pull command (embed token in URL if provided)
    branch = config.git_branch or "main"
    if config.git_token and config.git_repo_url:
        scheme_sep = config.git_repo_url.split("://", 1)
        if len(scheme_sep) == 2:
            auth_url = f"{scheme_sep[0]}://token:{config.git_token}@{scheme_sep[1]}"
        else:
            auth_url = config.git_repo_url
        pull_cmd = ["git", "-C", SOURCE_DIR, "pull", auth_url, branch]
    else:
        pull_cmd = ["git", "-C", SOURCE_DIR, "pull", "origin", branch]

    # 3. Git pull (synchronous — must complete before rebuild)
    try:
        result = subprocess.run(
            pull_cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "git pull timed out after 120s.", "backup": backup_path}
    except Exception as exc:
        return {"ok": False, "message": f"git pull error: {exc}", "backup": backup_path}

    if result.returncode != 0:
        stderr = result.stderr.strip()[:500]
        logger.error("git pull failed (exit %d): %s", result.returncode, stderr)
        return {
            "ok": False,
            "message": f"git pull failed: {stderr}",
            "backup": backup_path,
        }

    logger.info("git pull succeeded: %s", result.stdout.strip()[:200])

    # 4. Read version info from the freshly-pulled source
    build_env = os.environ.copy()
    try:
        build_env["GIT_COMMIT"] = subprocess.run(
            ["git", "-C", SOURCE_DIR, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or "unknown"

        build_env["GIT_BRANCH"] = subprocess.run(
            ["git", "-C", SOURCE_DIR, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or "unknown"

        build_env["GIT_COMMIT_DATE"] = subprocess.run(
            ["git", "-C", SOURCE_DIR, "log", "-1", "--format=%cI"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or "unknown"

        tag_result = subprocess.run(
            ["git", "-C", SOURCE_DIR, "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, timeout=10,
        )
        build_env["GIT_TAG"] = tag_result.stdout.strip() if tag_result.returncode == 0 else "unknown"
    except Exception as exc:
        logger.warning("Could not read version info from source: %s", exc)

    logger.info(
        "Rebuilding with GIT_TAG=%s GIT_COMMIT=%s GIT_BRANCH=%s",
        build_env.get("GIT_TAG", "?"),
        build_env.get("GIT_COMMIT", "?"),
        build_env.get("GIT_BRANCH", "?"),
    )

    # 5. Two-phase rebuild: Build image first, then swap container.
    #    The swap will kill this process (we ARE the container), so we must
    #    ensure the compose-up runs detached on the Docker host via a wrapper.
    log_path = Path(BACKUP_DIR) / "update_rebuild.log"

    # Phase A — build the new image (does NOT stop anything)
    build_cmd = [
        "docker", "compose",
        "-p", "netbirdmsp-appliance",
        "-f", f"{SOURCE_DIR}/docker-compose.yml",
        "build", "--no-cache",
        "netbird-msp-appliance",
    ]
    logger.info("Phase A: building new image …")
    try:
        build_result = subprocess.run(
            build_cmd,
            capture_output=True, text=True,
            timeout=600,
            env=build_env,
        )
        with open(log_path, "w") as f:
            f.write(build_result.stdout)
            f.write(build_result.stderr)
        if build_result.returncode != 0:
            logger.error("Image build failed: %s", build_result.stderr[:500])
            return {
                "ok": False,
                "message": f"Image build failed: {build_result.stderr[:300]}",
                "backup": backup_path,
            }
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Image build timed out after 600s.", "backup": backup_path}

    logger.info("Phase A complete — image built successfully.")

    # Phase B — swap the container using a helper container.
    #    When compose recreates our container, ALL processes inside die (PID namespace
    #    is destroyed). So we launch a *separate* helper container via 'docker run -d'
    #    that has access to the Docker socket and runs 'docker compose up -d'.
    #    This helper lives outside our container and survives our restart.

    # Discover the host-side path of /app-source (docker volumes use host paths)
    try:
        inspect_result = subprocess.run(
            ["docker", "inspect", "netbird-msp-appliance",
             "--format", '{{range .Mounts}}{{if eq .Destination "/app-source"}}{{.Source}}{{end}}{{end}}'],
            capture_output=True, text=True, timeout=10,
        )
        host_source_dir = inspect_result.stdout.strip()
        if not host_source_dir:
            raise ValueError("Could not find /app-source mount")
    except Exception as exc:
        logger.error("Failed to discover host source path: %s", exc)
        return {"ok": False, "message": f"Could not find host source path: {exc}", "backup": backup_path}

    logger.info("Host source directory: %s", host_source_dir)

    env_flags = []
    for key in ("GIT_TAG", "GIT_COMMIT", "GIT_BRANCH", "GIT_COMMIT_DATE"):
        val = build_env.get(key, "unknown")
        env_flags.extend(["-e", f"{key}={val}"])

    # Use the same image we're already running (it has docker CLI + compose plugin)
    own_image = "netbirdmsp-appliance-netbird-msp-appliance:latest"

    helper_cmd = [
        "docker", "run", "--rm", "-d", "--privileged",
        "--name", "msp-updater",
        "-v", "/var/run/docker.sock:/var/run/docker.sock:z",
        "-v", f"{host_source_dir}:{host_source_dir}:ro,z",
        *env_flags,
        own_image,
        "sh", "-c",
        (
            "sleep 3 && "
            "docker compose -p netbirdmsp-appliance "
            f"-f {host_source_dir}/docker-compose.yml "
            "up --force-recreate --no-deps -d netbird-msp-appliance"
        ),
    ]
    try:
        # Remove stale updater container if any
        subprocess.run(
            ["docker", "rm", "-f", "msp-updater"],
            capture_output=True, timeout=10,
        )
        result = subprocess.run(
            helper_cmd,
            capture_output=True, text=True,
            timeout=30,
            env=build_env,
        )
        if result.returncode != 0:
            logger.error("Failed to start updater container: %s", result.stderr.strip())
            return {
                "ok": False,
                "message": f"Update-Container konnte nicht gestartet werden: {result.stderr.strip()[:200]}",
                "backup": backup_path,
            }
        logger.info("Phase B: updater container started — this container will restart in ~5s.")
    except Exception as exc:
        logger.error("Failed to launch updater: %s", exc)
        return {"ok": False, "message": f"Updater launch failed: {exc}", "backup": backup_path}

    return {
        "ok": True,
        "message": (
            "Update gestartet. Die App wird in ca. 60 Sekunden mit der neuen Version verfügbar sein."
        ),
        "backup": backup_path,
        "pulled_branch": branch,
    }
