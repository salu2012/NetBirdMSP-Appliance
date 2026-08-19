"""Background scheduler for automatic NetBird image update checks.

No external scheduler dependency (APScheduler etc.) — a single asyncio task
started at app startup wakes up once a minute, and only actually does
anything once per day at the configured HH:MM, controlled entirely by
SystemConfig.auto_update_check_enabled / auto_update_check_time.
"""

import asyncio
import logging
from datetime import datetime

from app.database import SessionLocal
from app.models import Deployment, SystemConfig
from app.services import image_service

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 60
_task: asyncio.Task | None = None


def start() -> None:
    """Start the background polling task. Safe to call once at app startup."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_poll_loop())
        logger.info("Automatic update scheduler started.")


def stop() -> None:
    """Cancel the background polling task."""
    global _task
    if _task is not None:
        _task.cancel()
        _task = None


async def _poll_loop() -> None:
    while True:
        try:
            await _tick()
        except Exception:
            logger.exception("Scheduler tick failed")
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def _tick() -> None:
    db = SessionLocal()
    try:
        config = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
        if not config or not config.auto_update_check_enabled:
            return

        now = datetime.now()
        target_time = config.auto_update_check_time or "03:00"
        current_hhmm = now.strftime("%H:%M")
        if current_hhmm != target_time:
            return

        last_run = config.auto_update_last_run_at
        if last_run and last_run.date() == now.date():
            return  # already ran today

        # Claim this run immediately so a slow run can't overlap the next tick.
        config.auto_update_last_run_at = now
        db.commit()

        apply_enabled = bool(config.auto_update_apply_enabled)
        logger.info(
            "Running scheduled NetBird image update check (auto-apply=%s)...", apply_enabled
        )
        await _run_check_and_optionally_apply(config, apply_enabled)
    finally:
        db.close()


async def _run_check_and_optionally_apply(config: SystemConfig, apply_enabled: bool) -> None:
    hub_status = await image_service.check_all_images(config)
    if not hub_status["any_update_available"]:
        logger.info("Scheduled check: all NetBird images already up to date.")
        return

    logger.info("Scheduled check: new NetBird image(s) available — pulling.")
    pull_result = await image_service.pull_all_images(config)
    if not pull_result["all_success"]:
        logger.error("Scheduled image pull had failures: %s", pull_result["results"])

    if not apply_enabled:
        logger.info("Auto-apply disabled — images pulled, customer containers left untouched.")
        return

    db = SessionLocal()
    try:
        deployments = db.query(Deployment).all()
        to_update = []
        for dep in deployments:
            cs = image_service.get_customer_container_image_status(dep.container_prefix, config)
            if cs["needs_update"]:
                customer = dep.customer
                to_update.append({
                    "instance_dir": f"{config.data_dir}/{customer.subdomain}",
                    "project_name": dep.container_prefix,
                    "customer_name": customer.name,
                })
        logger.info("Scheduled auto-apply: updating %d customer(s)...", len(to_update))
        for entry in to_update:
            try:
                res = await image_service.update_customer_containers(
                    entry["instance_dir"], entry["project_name"]
                )
                logger.info(
                    "Scheduled update for %s: %s",
                    entry["customer_name"], "OK" if res["success"] else res.get("error"),
                )
            except Exception:
                logger.exception("Scheduled update failed for %s", entry["customer_name"])
    finally:
        db.close()
