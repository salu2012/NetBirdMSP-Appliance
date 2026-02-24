"""Active Directory / LDAP authentication via ldap3.

Provides LDAP-based user authentication as an alternative to local password
authentication. Supports standard Active Directory via sAMAccountName lookup
and optional group membership restriction.

All ldap3 operations run in a thread executor since ldap3 is synchronous.

Authentication flow:
    1. Bind with service account (ldap_bind_dn + ldap_bind_password)
    2. Search for the user entry using ldap_user_filter
    3. If ldap_group_dn is set: verify group membership
    4. Re-bind with the user's own DN + supplied password to verify credentials
    5. Return user info dict on success

Raises:
    ValueError: If the user was found but the password is wrong.
    RuntimeError: If LDAP is misconfigured or the server is unreachable.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _ldap_test(server: str, port: int, use_ssl: bool, bind_dn: str, bind_password: str) -> dict:
    """Synchronous LDAP connectivity test — bind with service account.

    Returns dict with ``ok`` and ``message``.
    """
    from ldap3 import ALL, SIMPLE, Connection, Server as LdapServer, SUBTREE  # noqa: F401

    srv = LdapServer(server, port=port, use_ssl=use_ssl, get_info=ALL)
    try:
        conn = Connection(srv, user=bind_dn, password=bind_password, authentication=SIMPLE, auto_bind=True)
        conn.unbind()
        return {"ok": True, "message": f"Bind successful to {server}:{port} as '{bind_dn}'."}
    except Exception as exc:
        return {"ok": False, "message": f"LDAP bind failed: {exc}"}


def _ldap_authenticate(
    server: str,
    port: int,
    use_ssl: bool,
    bind_dn: str,
    bind_password: str,
    base_dn: str,
    user_filter: str,
    group_dn: str,
    username: str,
    password: str,
) -> dict | None:
    """Synchronous LDAP authentication.

    Returns:
        User info dict on success: {"username": ..., "email": ..., "display_name": ...}
        None if user was not found in LDAP (caller may fall back to local auth).

    Raises:
        ValueError: Correct username but wrong password.
        RuntimeError: LDAP server error / misconfiguration.
    """
    from ldap3 import ALL, SIMPLE, SUBTREE, Connection, Server as LdapServer

    srv = LdapServer(server, port=port, use_ssl=use_ssl, get_info=ALL)

    # Step 1: Bind with service account to search for the user
    try:
        conn = Connection(srv, user=bind_dn, password=bind_password, authentication=SIMPLE, auto_bind=True)
    except Exception as exc:
        raise RuntimeError(f"LDAP service account bind failed: {exc}") from exc

    # Step 2: Search for user
    safe_filter = user_filter.replace("{username}", username.replace("(", "").replace(")", "").replace("*", ""))
    conn.search(
        search_base=base_dn,
        search_filter=safe_filter,
        search_scope=SUBTREE,
        attributes=["distinguishedName", "mail", "displayName", "sAMAccountName", "memberOf"],
    )

    if not conn.entries:
        conn.unbind()
        return None  # User not found in LDAP — caller falls back to local auth

    entry = conn.entries[0]
    user_dn = entry.entry_dn
    email = str(entry.mail.value) if entry.mail else username
    display_name = str(entry.displayName.value) if entry.displayName else username

    # Step 3: Optional group membership check
    if group_dn:
        member_of = [str(g) for g in entry.memberOf] if entry.memberOf else []
        if not any(group_dn.lower() == g.lower() for g in member_of):
            conn.unbind()
            logger.warning(
                "LDAP login denied for '%s': not a member of required group '%s'.",
                username, group_dn,
            )
            raise ValueError(f"Access denied: not a member of the required AD group.")

    conn.unbind()

    # Step 4: Verify user's password by binding as the user
    try:
        user_conn = Connection(srv, user=user_dn, password=password, authentication=SIMPLE, auto_bind=True)
        user_conn.unbind()
    except Exception:
        raise ValueError("Invalid password.")

    return {
        "username": username.lower(),
        "email": email,
        "display_name": display_name,
    }


async def test_ldap_connection(config: Any) -> dict:
    """Test connectivity to the LDAP / Active Directory server.

    Attempts a service account bind to verify credentials and reachability.

    Args:
        config: AppConfig with LDAP settings.

    Returns:
        Dict with ``ok`` (bool) and ``message`` (str).
    """
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            _ldap_test,
            config.ldap_server,
            config.ldap_port,
            config.ldap_use_ssl,
            config.ldap_bind_dn,
            config.ldap_bind_password,
        )
    except ImportError:
        return {"ok": False, "message": "ldap3 is not installed. Add 'ldap3' to requirements.txt."}
    except Exception as exc:
        logger.error("LDAP test_connection error: %s", exc)
        return {"ok": False, "message": f"LDAP error: {exc}"}


async def authenticate_ldap(username: str, password: str, config: Any) -> dict | None:
    """Authenticate a user against LDAP / Active Directory.

    Args:
        username: The login username (matched via ldap_user_filter).
        password: The user's password.
        config: AppConfig with LDAP settings.

    Returns:
        User info dict on success: {"username": ..., "email": ..., "display_name": ...}
        None if the user was not found in LDAP.

    Raises:
        ValueError: User found but password incorrect, or group membership denied.
        RuntimeError: LDAP server unreachable or misconfigured.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _ldap_authenticate,
        config.ldap_server,
        config.ldap_port,
        config.ldap_use_ssl,
        config.ldap_bind_dn,
        config.ldap_bind_password,
        config.ldap_base_dn,
        config.ldap_user_filter,
        config.ldap_group_dn,
        username,
        password,
    )
