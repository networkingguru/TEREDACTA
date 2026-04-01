"""Configuration for locust stress tests."""

import os

# Target server
TARGET_HOST = os.environ.get("STRESS_TARGET_HOST", "http://localhost:8000")

# Admin credentials for SSE and admin endpoints
ADMIN_PASSWORD = os.environ.get("STRESS_ADMIN_PASSWORD", "test-password")

# User class weights (must sum to 100)
WEB_USER_WEIGHT = 60
SSE_USER_WEIGHT = 15
ADMIN_USER_WEIGHT = 20
HEALTH_MONITOR_WEIGHT = 5

# Health monitoring thresholds
LIVENESS_FAILURE_SECONDS = 0  # Any liveness failure is critical
READINESS_UNHEALTHY_SECONDS = 60  # Sustained unhealthy = test failure

# SSE connection parameters
SSE_MIN_HOLD_SECONDS = 10
SSE_MAX_HOLD_SECONDS = 60

# Load test phases (seconds)
RAMP_UP_SECONDS = 30
SUSTAINED_SECONDS = 240
RAMP_DOWN_SECONDS = 30
RECOVERY_SECONDS = 15
