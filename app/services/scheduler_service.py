"""Background scheduler for automatic NetBird image update checks.

No external scheduler dependency (APScheduler etc.) — a single asyncio task
started at app startup wakes up once a minute, and only actually does
anything once per day at the configured HH:MM, controlled entirely by
SystemConfig.auto_update_check_enabled / auto_update_check_time.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import Deployment, SystemConfig
from app.services import image_service, netbird_client_update_service, update_log_service
from app.utils.security import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 60
_task: asyncio.Task | None = None

# NetBird PATs we mint are issued for 365 days; renew well before that so a
# missed tick or a slow rollout never risks the token actually expiring.
_TOKEN_RENEW_AFTER_DAYS = 300
_TOKEN_RENEW_CHECK_HOUR = 4  # run once per day, distinct from the image-check hour


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


_last_token_renewal_date = None


async def _poll_loop() -> None:
    while True:
        try:
            await _tick()
        except Exception:
            logger.exception("Scheduler tick failed")
        try:
            await _token_renewal_tick()
        except Exception:
            logger.exception("Token renewal tick failed")
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def _token_renewal_tick() -> None:
    """Once a day, renew any NetBird client-update API token nearing its
    365-day expiry — keeps central update control working indefinitely
    without anyone needing to notice or act.
    """
    global _last_token_renewal_date
    now = datetime.now()
    if now.hour != _TOKEN_RENEW_CHECK_HOUR:
        return
    if _last_token_renewal_date == now.date():
        return
    _last_token_renewal_date = now.date()

    db = SessionLocal()
    try:
        cutoff = now - timedelta(days=_TOKEN_RENEW_AFTER_DAYS)
        deployments = (
            db.query(Deployment)
            .filter(Deployment.netbird_api_token_encrypted.isnot(None))
            .all()
        )
        due = [
            d for d in deployments
            if d.netbird_api_token_renewed_at is None or d.netbird_api_token_renewed_at < cutoff
        ]
        if not due:
            return
        logger.info("Renewing NetBird API token for %d customer(s)...", len(due))
        for d in due:
            token = decrypt_value(d.netbird_api_token_encrypted)
            result = await netbird_client_update_service.renew_token(d.container_prefix, token)
            if result["ok"]:
                d.netbird_api_token_encrypted = encrypt_value(result["token"])
                d.netbird_api_token_renewed_at = now
                db.commit()
                logger.info("Renewed NetBird API token for %s.", d.container_prefix)
            else:
                logger.warning("Failed to renew NetBird API token for %s: %s", d.container_prefix, result.get("error"))
    finally:
        db.close()


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
        await _run_check_and_optionally_apply(config, apply_enabled, started_at=now)
    finally:
        db.close()


async def _run_check_and_optionally_apply(config: SystemConfig, apply_enabled: bool, started_at: datetime) -> None:
    """Check Docker Hub, pull if needed, then (if enabled) recreate any
    customer container that isn't running the locally-pulled image yet.

    The "recreate" step is intentionally NOT gated on a Hub update having
    just been found: a customer can already be behind the *locally pulled*
    image from an earlier check/pull that was never applied (e.g. auto-apply
    was off at the time, or a previous run failed) — that backlog must keep
    being cleared on every run, not just on runs that also found something
    new on Hub, otherwise it silently never happens.
    """
    log_db = SessionLocal()
    try:
        hub_status = await image_service.check_all_images(config)
        any_update = hub_status["any_update_available"]

        pull_attempted = False
        pull_results = None
        if any_update:
            logger.info("Scheduled check: new NetBird image(s) available — pulling.")
            pull_attempted = True
            pull_result = await image_service.pull_all_images(config)
            pull_results = pull_result["results"]
            if not pull_result["all_success"]:
                logger.error("Scheduled image pull had failures: %s", pull_results)
        else:
            logger.info("Scheduled check: all NetBird images already up to date on Docker Hub.")

        if not apply_enabled:
            logger.info("Auto-apply disabled — customer containers left untouched.")
            update_log_service.record_run(
                log_db, run_type="scheduled", trigger="scheduler",
                started_at=started_at, any_update_available=any_update,
                pull_attempted=pull_attempted, pull_results=pull_results,
            )
            return

        deployments = log_db.query(Deployment).all()
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
        customer_results = []
        for entry in to_update:
            try:
                res = await image_service.update_customer_containers(
                    entry["instance_dir"], entry["project_name"]
                )
                ok = res["success"]
                err = res.get("error")
            except Exception as exc:
                logger.exception("Scheduled update failed for %s", entry["customer_name"])
                ok = False
                err = str(exc)
            logger.info("Scheduled update for %s: %s", entry["customer_name"], "OK" if ok else err)
            customer_results.append({"customer_name": entry["customer_name"], "success": ok, "error": err})

        update_log_service.record_run(
            log_db, run_type="scheduled", trigger="scheduler",
            started_at=started_at, any_update_available=any_update,
            pull_attempted=pull_attempted, pull_results=pull_results,
            apply_attempted=True, customer_results=customer_results,
        )
    except Exception as exc:
        logger.exception("Scheduled update run failed")
        update_log_service.record_run(
            log_db, run_type="scheduled", trigger="scheduler",
            started_at=started_at, error=str(exc),
        )
    finally:
        log_db.close()
