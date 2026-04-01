# TEREDACTA Stress Tests

Load testing suite using [Locust](https://locust.io/).

## Setup

```bash
pip install -e ".[stress]"
```

## Running

### Against local server

Start TEREDACTA locally first:
```bash
teredacta run
```

Then run the stress tests:
```bash
# Headless (CI mode) — uses StressTestShape for phases
locust -f stress/locustfile.py --headless --host http://localhost:8000

# With web UI (interactive)
locust -f stress/locustfile.py --host http://localhost:8000
# Then open http://localhost:8089
```

### Against VPS

```bash
export STRESS_ADMIN_PASSWORD=your-admin-password
locust -f stress/locustfile.py --headless --host https://your-vps.example.com
```

### With web UI

```bash
locust -f stress/locustfile.py --host https://your-vps.example.com
```
Open http://localhost:8089 to configure users, spawn rate, and watch results.

## Load Phases (StressTestShape)

| Phase | Duration | Users | Description |
|---|---|---|---|
| Warm-up | 0-30s | 0→200 | Ramp up at 10 users/sec |
| Sustained | 30s-4m30s | 200 | Full load |
| Cool-down | 4m30s-5m | 200→0 | Ramp down |
| Recovery | 5m-5m15s | 1 | Verify health returns to healthy |

## Configuration

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `STRESS_TARGET_HOST` | `http://localhost:8000` | Target server URL |
| `STRESS_ADMIN_PASSWORD` | `test-password` | Admin password for SSE/admin tests |

## User Profiles

| Profile | Weight | Description |
|---|---|---|
| WebUser | 60% | Browses public pages (documents, recoveries, highlights) |
| SSEUser | 15% | Opens SSE connections, holds 10-60s, mix of graceful/ungraceful disconnects |
| AdminUser | 20% | Admin dashboard, daemon status, entity index status, config, logs |
| HealthMonitor | 5% | Polls /health/live and /health/ready, tracks status transitions |

## Success Criteria

- Liveness probe (`/health/live`) never fails
- Readiness probe (`/health/ready`) does not report "unhealthy" for more than 60 seconds continuously
- No HTTP 500 errors
- Server recovers to "healthy" after load subsides
