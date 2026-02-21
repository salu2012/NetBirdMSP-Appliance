"""Windows DNS Server integration via WinRM + PowerShell.

Uses pywinrm to execute PowerShell DNS cmdlets on a remote Windows DNS server.
All WinRM operations run in a thread executor since pywinrm is synchronous.

Typical usage:
    config = get_system_config(db)
    result = await create_dns_record("kunde1", config)
    # result == {"ok": True, "message": "A-record 'kunde1.example.com → 10.0.0.5' created."}
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _winrm_run(server: str, username: str, password: str, ps_script: str) -> tuple[int, str, str]:
    """Execute a PowerShell script via WinRM and return (status_code, stdout, stderr).

    Runs synchronously — must be called via run_in_executor.
    """
    import winrm  # imported here so the app starts even without pywinrm installed

    session = winrm.Session(
        target=server,
        auth=(username, password),
        transport="ntlm",
    )
    result = session.run_ps(ps_script)
    stdout = result.std_out.decode("utf-8", errors="replace").strip()
    stderr = result.std_err.decode("utf-8", errors="replace").strip()
    return result.status_code, stdout, stderr


async def _run_ps(server: str, username: str, password: str, ps_script: str) -> tuple[int, str, str]:
    """Async wrapper: runs _winrm_run in a thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _winrm_run, server, username, password, ps_script)


async def test_dns_connection(config: Any) -> dict:
    """Test WinRM connectivity to the Windows DNS server.

    Runs 'Get-DnsServerZone' to verify the configured zone exists.

    Args:
        config: AppConfig with dns_server, dns_username, dns_password, dns_zone.

    Returns:
        Dict with ``ok`` (bool) and ``message`` (str).
    """
    zone = config.dns_zone.strip()
    ps = f"Get-DnsServerZone -Name '{zone}' | Select-Object ZoneName, ZoneType"
    try:
        code, stdout, stderr = await _run_ps(
            config.dns_server, config.dns_username, config.dns_password, ps
        )
        if code == 0 and zone.lower() in stdout.lower():
            return {"ok": True, "message": f"Connected. Zone '{zone}' found on {config.dns_server}."}
        err = stderr or stdout or "Unknown error"
        return {"ok": False, "message": f"Zone '{zone}' not found or access denied: {err[:300]}"}
    except ImportError:
        return {"ok": False, "message": "pywinrm is not installed. Add 'pywinrm' to requirements.txt."}
    except Exception as exc:
        logger.error("DNS connection test failed: %s", exc)
        return {"ok": False, "message": f"Connection failed: {exc}"}


async def create_dns_record(subdomain: str, config: Any) -> dict:
    """Create an A-record in the Windows DNS server.

    Record: {subdomain}.{zone} → {dns_record_ip}

    If a record already exists for the subdomain, it is removed first to avoid
    duplicate-record errors (idempotent behaviour for re-deployments).

    Args:
        subdomain: The customer subdomain (e.g. ``kunde1``).
        config: AppConfig with DNS settings.

    Returns:
        Dict with ``ok`` (bool) and ``message`` (str).
    """
    zone = config.dns_zone.strip()
    ip = config.dns_record_ip.strip()
    name = subdomain.strip()

    # Remove existing record first (idempotent — ignore errors)
    ps_remove = (
        f"Try {{"
        f"  Remove-DnsServerResourceRecord -ZoneName '{zone}' -RRType 'A' -Name '{name}' -Force -ErrorAction SilentlyContinue"
        f"}} Catch {{}}"
    )
    # Create new A-record
    ps_add = f"Add-DnsServerResourceRecordA -ZoneName '{zone}' -Name '{name}' -IPv4Address '{ip}' -TimeToLive 00:05:00"

    ps_script = f"{ps_remove}\n{ps_add}"

    try:
        code, stdout, stderr = await _run_ps(
            config.dns_server, config.dns_username, config.dns_password, ps_script
        )
        if code == 0:
            logger.info("DNS A-record created: %s.%s → %s", name, zone, ip)
            return {"ok": True, "message": f"A-record '{name}.{zone} → {ip}' created successfully."}
        err = stderr or stdout or "Unknown error"
        logger.warning("DNS A-record creation failed for %s.%s: %s", name, zone, err)
        return {"ok": False, "message": f"Failed to create DNS record: {err[:300]}"}
    except ImportError:
        return {"ok": False, "message": "pywinrm is not installed. Add 'pywinrm' to requirements.txt."}
    except Exception as exc:
        logger.error("DNS create_record error for %s.%s: %s", name, zone, exc)
        return {"ok": False, "message": f"DNS error: {exc}"}


async def delete_dns_record(subdomain: str, config: Any) -> dict:
    """Delete the A-record for a customer subdomain from the Windows DNS server.

    Args:
        subdomain: The customer subdomain (e.g. ``kunde1``).
        config: AppConfig with DNS settings.

    Returns:
        Dict with ``ok`` (bool) and ``message`` (str).
    """
    zone = config.dns_zone.strip()
    name = subdomain.strip()

    ps_script = (
        f"Remove-DnsServerResourceRecord -ZoneName '{zone}' -RRType 'A' -Name '{name}' -Force"
    )

    try:
        code, stdout, stderr = await _run_ps(
            config.dns_server, config.dns_username, config.dns_password, ps_script
        )
        if code == 0:
            logger.info("DNS A-record deleted: %s.%s", name, zone)
            return {"ok": True, "message": f"A-record '{name}.{zone}' deleted successfully."}
        err = stderr or stdout or "Unknown error"
        # Record not found is acceptable during deletion
        if "not found" in err.lower() or "does not exist" in err.lower():
            logger.info("DNS A-record %s.%s not found (already deleted).", name, zone)
            return {"ok": True, "message": f"A-record '{name}.{zone}' not found (already deleted)."}
        logger.warning("DNS A-record deletion failed for %s.%s: %s", name, zone, err)
        return {"ok": False, "message": f"Failed to delete DNS record: {err[:300]}"}
    except ImportError:
        return {"ok": False, "message": "pywinrm is not installed. Add 'pywinrm' to requirements.txt."}
    except Exception as exc:
        logger.error("DNS delete_record error for %s.%s: %s", name, zone, exc)
        return {"ok": False, "message": f"DNS error: {exc}"}
