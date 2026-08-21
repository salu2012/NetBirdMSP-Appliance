"""Persists the outcome of every NetBird Docker image update run.

Both the automatic scheduler and the manual "Check/Pull/Update" buttons in
the UI write here, so it's visible afterwards which run pulled which image
successfully, and which customer container recreate failed — instead of
that information only existing in container logs.
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import UpdateRunLog

logger = logging.getLogger(__name__)


def record_run(
    db: Session,
    *,
    run_type: str,
    trigger: Optional[str],
    started_at: datetime,
    any_update_available: Optional[bool] = None,
    pull_attempted: bool = False,
    pull_results: Optional[dict[str, Any]] = None,
    apply_attempted: bool = False,
    customer_results: Optional[list[dict[str, Any]]] = None,
    error: Optional[str] = None,
) -> UpdateRunLog:
    """Write one completed update-run entry.

    Args:
        run_type: "scheduled" or "manual".
        trigger: username for manual runs, "scheduler" for automatic ones.
        pull_results: {image: {"success": bool, "error": str|None}} as returned
            by image_service.pull_all_images()["results"].
        customer_results: list of {"customer_name", "success", "error"} as
            returned by the update-all / update-customer flows.
    """
    pull_success = None
    if pull_results:
        pull_success = all(r.get("success") for r in pull_results.values())

    customers_total = len(customer_results) if customer_results is not None else None
    customers_updated = (
        sum(1 for r in customer_results if r.get("success")) if customer_results is not None else None
    )

    if error:
        status = "failed"
    elif pull_attempted and pull_success is False:
        status = "failed"
    elif apply_attempted and customers_total and customers_updated != customers_total:
        status = "partial"
    elif not pull_attempted and not customers_total:
        # Nothing to pull (Hub already matched local) and no customer
        # container was behind the locally pulled image either.
        status = "no_update"
    else:
        status = "success"

    log = UpdateRunLog(
        run_type=run_type,
        trigger=trigger,
        started_at=started_at,
        finished_at=datetime.utcnow(),
        status=status,
        any_update_available=any_update_available,
        pull_attempted=pull_attempted,
        pull_success=pull_success,
        pull_details=json.dumps(pull_results) if pull_results is not None else None,
        apply_attempted=apply_attempted,
        customers_updated=customers_updated,
        customers_total=customers_total,
        customer_details=json.dumps(customer_results) if customer_results is not None else None,
        error=error,
    )
    db.add(log)
    db.commit()
    return log
