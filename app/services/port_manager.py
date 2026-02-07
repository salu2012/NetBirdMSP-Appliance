"""UDP port allocation service for NetBird relay/STUN ports.

Manages the range starting at relay_base_port (default 3478). Each customer
gets one unique UDP port. The manager checks both the database and the OS
to avoid collisions.
"""

import logging
import socket
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Deployment

logger = logging.getLogger(__name__)


def _is_udp_port_in_use(port: int) -> bool:
    """Check whether a UDP port is currently bound on the host.

    Args:
        port: UDP port number to probe.

    Returns:
        True if the port is in use.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("0.0.0.0", port))
        return False
    except OSError:
        return True
    finally:
        sock.close()


def get_allocated_ports(db: Session) -> set[int]:
    """Return the set of relay UDP ports already assigned in the database.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Set of port numbers.
    """
    rows = db.query(Deployment.relay_udp_port).all()
    return {r[0] for r in rows}


def allocate_port(db: Session, base_port: int = 3478, max_ports: int = 100) -> int:
    """Find and return the next available relay UDP port.

    Scans from *base_port* to *base_port + max_ports - 1*, skipping ports
    that are either already in the database or currently bound on the host.

    Args:
        db: Active SQLAlchemy session.
        base_port: Start of the port range.
        max_ports: Number of ports in the range.

    Returns:
        An available port number.

    Raises:
        RuntimeError: If no port in the range is available.
    """
    allocated = get_allocated_ports(db)
    for port in range(base_port, base_port + max_ports):
        if port in allocated:
            continue
        if _is_udp_port_in_use(port):
            logger.warning("Port %d is in use on the host, skipping.", port)
            continue
        logger.info("Allocated relay UDP port %d.", port)
        return port

    raise RuntimeError(
        f"No available relay ports in range {base_port}-{base_port + max_ports - 1}. "
        "All 100 ports are allocated."
    )


def release_port(db: Session, port: int) -> None:
    """Mark a port as released (informational logging only).

    The actual release happens when the Deployment row is deleted. This
    helper exists for explicit logging in rollback scenarios.

    Args:
        db: Active SQLAlchemy session.
        port: The port to release.
    """
    logger.info("Released relay UDP port %d.", port)


def validate_port_available(db: Session, port: int) -> bool:
    """Check if a specific port is available both in DB and on the host.

    Args:
        db: Active SQLAlchemy session.
        port: Port number to check.

    Returns:
        True if the port is available.
    """
    allocated = get_allocated_ports(db)
    if port in allocated:
        return False
    return not _is_udp_port_in_use(port)
