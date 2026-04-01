"""Locust stress test suite for TEREDACTA.

Run headless:
    locust -f stress/locustfile.py --headless -u 200 -r 10 -t 5m --host http://localhost:8000

Run with Web UI:
    locust -f stress/locustfile.py --host http://localhost:8000
"""

import logging
import math
import random
import time

import gevent
from locust import HttpUser, LoadTestShape, between, events, task

from stress_config import (
    ADMIN_PASSWORD,
    ADMIN_USER_WEIGHT,
    HEALTH_MONITOR_WEIGHT,
    RAMP_DOWN_SECONDS,
    RAMP_UP_SECONDS,
    READINESS_UNHEALTHY_SECONDS,
    RECOVERY_SECONDS,
    SSE_MAX_HOLD_SECONDS,
    SSE_MIN_HOLD_SECONDS,
    SSE_USER_WEIGHT,
    SUSTAINED_SECONDS,
    WEB_USER_WEIGHT,
)

logger = logging.getLogger(__name__)

# Track health status transitions globally.
# Safe under gevent: cooperative scheduling, no I/O between read-modify-write.
_health_tracker = {
    "last_healthy": time.monotonic(),
    "unhealthy_since": None,
    "liveness_failures": 0,
}


class StressTestShape(LoadTestShape):
    """Custom load shape with warm-up, sustained, cool-down, and recovery phases.

    Phase 1 (0-30s):      Ramp up from 0 to 200 users
    Phase 2 (30s-4m30s):  Sustained at 200 users
    Phase 3 (4m30s-5m):   Ramp down from 200 to 0
    Phase 4 (5m-5m15s):   Recovery — only HealthMonitor users remain
    """
    MAX_USERS = 200
    SPAWN_RATE = 10

    def tick(self):
        run_time = self.get_run_time()

        if run_time < RAMP_UP_SECONDS:
            # Phase 1: Ramp up
            users = min(self.MAX_USERS, math.ceil(run_time * self.SPAWN_RATE))
            return (users, self.SPAWN_RATE)

        elif run_time < RAMP_UP_SECONDS + SUSTAINED_SECONDS:
            # Phase 2: Sustained load
            return (self.MAX_USERS, self.SPAWN_RATE)

        elif run_time < RAMP_UP_SECONDS + SUSTAINED_SECONDS + RAMP_DOWN_SECONDS:
            # Phase 3: Ramp down
            elapsed_in_phase = run_time - RAMP_UP_SECONDS - SUSTAINED_SECONDS
            fraction_remaining = 1 - (elapsed_in_phase / RAMP_DOWN_SECONDS)
            users = max(1, math.ceil(self.MAX_USERS * fraction_remaining))
            return (users, self.SPAWN_RATE)

        elif run_time < RAMP_UP_SECONDS + SUSTAINED_SECONDS + RAMP_DOWN_SECONDS + RECOVERY_SECONDS:
            # Phase 4: Recovery — keep minimal users for health monitoring
            return (1, 1)

        else:
            # Done
            return None


class WebUser(HttpUser):
    """Simulates a visitor browsing public pages."""

    weight = WEB_USER_WEIGHT
    wait_time = between(1, 5)

    @task(5)
    def browse_documents(self):
        page = random.randint(1, 10)
        self.client.get(f"/documents?page={page}", name="/documents?page=[N]")

    @task(3)
    def browse_recoveries(self):
        self.client.get("/recoveries")

    @task(3)
    def browse_highlights(self):
        self.client.get("/highlights")

    @task(2)
    def browse_explore(self):
        self.client.get("/")

    @task(1)
    def view_document_detail(self):
        doc_id = f"doc-{random.randint(1, 100)}"
        self.client.get(f"/documents/{doc_id}", name="/documents/[id]")


class SSEUser(HttpUser):
    """Simulates an admin subscribing to SSE stats."""

    weight = SSE_USER_WEIGHT
    # Short wait between reconnections — hold time is inside the task
    wait_time = between(1, 3)

    def on_start(self):
        """Authenticate to get admin session cookie."""
        self.client.post(
            "/admin/login",
            data={"password": ADMIN_PASSWORD},
            name="/admin/login",
            allow_redirects=False,
        )

    @task
    def subscribe_sse(self):
        """Open SSE connection, hold it, then disconnect."""
        hold_time = random.uniform(SSE_MIN_HOLD_SECONDS, SSE_MAX_HOLD_SECONDS)
        start = time.monotonic()

        try:
            with self.client.get(
                "/sse/stats",
                stream=True,
                timeout=hold_time + 5,  # Hard timeout to prevent blocking beyond hold_time
                name="/sse/stats",
                catch_response=True,
            ) as resp:
                if resp.status_code == 403:
                    resp.failure("Not authenticated — SSE returned 403")
                    return
                resp.success()

                # Hold connection for the specified duration
                for line in resp.iter_lines():
                    if time.monotonic() - start > hold_time:
                        break
        except Exception as e:
            logger.debug("SSE connection ended: %s", e)


class AdminUser(HttpUser):
    """Simulates admin dashboard usage."""

    weight = ADMIN_USER_WEIGHT
    wait_time = between(2, 8)

    def on_start(self):
        self.client.post(
            "/admin/login",
            data={"password": ADMIN_PASSWORD},
            name="/admin/login",
            allow_redirects=False,
        )

    @task(3)
    def view_admin_dashboard(self):
        self.client.get("/admin/")

    @task(2)
    def check_daemon_status(self):
        self.client.get("/admin/daemon/status")

    @task(2)
    def view_entity_index_status(self):
        self.client.get("/admin/entity-index/status")

    @task(1)
    def view_config(self):
        self.client.get("/admin/config")

    @task(1)
    def view_logs(self):
        self.client.get("/admin/logs")


class HealthMonitor(HttpUser):
    """Continuously monitors health endpoints."""

    weight = HEALTH_MONITOR_WEIGHT
    wait_time = between(2, 5)

    @task(3)
    def check_liveness(self):
        with self.client.get("/health/live", catch_response=True, name="/health/live") as resp:
            if resp.status_code != 200:
                _health_tracker["liveness_failures"] += 1
                resp.failure(f"LIVENESS FAILURE: {resp.status_code}")
                logger.error("LIVENESS PROBE FAILED: status=%s", resp.status_code)
            else:
                resp.success()

    @task(1)
    def check_readiness(self):
        with self.client.get("/health/ready", catch_response=True, name="/health/ready") as resp:
            now = time.monotonic()

            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "unknown")

                if status == "healthy":
                    _health_tracker["last_healthy"] = now
                    _health_tracker["unhealthy_since"] = None
                    resp.success()
                elif status == "degraded":
                    # Expected under load — log but don't fail
                    resp.success()
                    logger.info("Health: degraded")
                else:
                    resp.failure(f"Unexpected status: {status}")
            elif resp.status_code == 503:
                if _health_tracker["unhealthy_since"] is None:
                    _health_tracker["unhealthy_since"] = now
                    logger.warning("Health: unhealthy (started)")

                duration = now - _health_tracker["unhealthy_since"]
                if duration > READINESS_UNHEALTHY_SECONDS:
                    resp.failure(
                        f"UNHEALTHY for {duration:.0f}s (threshold: {READINESS_UNHEALTHY_SECONDS}s)"
                    )
                else:
                    resp.success()
            else:
                resp.failure(f"Unexpected status code: {resp.status_code}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Report health summary at end of test. process_exit_code only works in headless mode."""
    tracker = _health_tracker
    logger.info("=== Health Summary ===")
    logger.info("Liveness failures: %d", tracker["liveness_failures"])
    if tracker["unhealthy_since"]:
        logger.warning("Server was unhealthy at test end")
    else:
        logger.info("Server was healthy at test end")

    if tracker["liveness_failures"] > 0:
        logger.error("TEST FAILED: Liveness probe failures detected")
        environment.process_exit_code = 1
