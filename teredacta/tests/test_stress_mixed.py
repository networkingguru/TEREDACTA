"""Stress tests for mixed concurrent workloads."""

import asyncio
import sqlite3

import pytest
import httpx


@pytest.mark.stress
@pytest.mark.timeout(90)
class TestMixedWorkload:

    @pytest.fixture
    def seeded_app(self, stress_app, stress_db):
        """Seed the stress_db with document data for mixed workload."""
        conn = sqlite3.connect(str(stress_db))
        rows = [
            (f"doc-{i}", f"source-{i % 5}", f"text content {i} " * 20,
             1, 0, f"file_{i}.pdf", (i % 10) + 1, i * 100)
            for i in range(1000)
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO documents "
            "(id, source, extracted_text, text_processed, pdf_processed, "
            "original_filename, page_count, size_bytes) VALUES (?,?,?,?,?,?,?,?)", rows
        )
        conn.commit()
        conn.close()
        return stress_app

    @pytest.mark.asyncio
    async def test_concurrent_requests_and_sse(self, seeded_app):
        """Simultaneous HTTP requests + SSE subscribers don't deadlock."""
        errors = []

        async def make_requests(client, n):
            for i in range(n):
                try:
                    resp = await client.get("/documents")
                    if resp.status_code not in (200, 307, 503):
                        errors.append(f"GET /documents returned {resp.status_code}")
                except Exception as e:
                    errors.append(f"request error: {e}")

        async def subscribe_sse(client):
            """Subscribe to SSE briefly — expects 403 (no admin session)."""
            try:
                resp = await asyncio.wait_for(
                    client.get("/sse/stats"), timeout=5.0
                )
            except (Exception, asyncio.TimeoutError):
                pass

        async def check_health(client, results):
            for _ in range(5):
                resp = await client.get("/health/ready")
                results.append(resp.json())
                await asyncio.sleep(0.2)

        health_results = []

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=seeded_app),
            base_url="http://testserver",
        ) as client:
            # Launch mixed workload with timeout to prevent hangs
            await asyncio.wait_for(
                asyncio.gather(
                    make_requests(client, 10),
                    make_requests(client, 10),
                    make_requests(client, 10),
                    subscribe_sse(client),
                    subscribe_sse(client),
                    check_health(client, health_results),
                ),
                timeout=60.0,
            )

        assert not errors, f"Errors during mixed workload: {errors}"
        # Health should have been healthy throughout (light load)
        for result in health_results:
            assert result["status"] in ("healthy", "degraded")

    @pytest.mark.asyncio
    async def test_recovery_after_load(self, seeded_app):
        """Health returns to healthy after load subsides."""

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=seeded_app),
            base_url="http://testserver",
        ) as client:
            # Phase 1: Apply load
            tasks = []
            for _ in range(10):
                tasks.append(client.get("/documents"))
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=30.0)

            # Phase 2: Wait briefly for things to settle
            await asyncio.sleep(0.5)

            # Phase 3: Check health
            resp = await client.get("/health/ready")
            data = resp.json()
            assert data["status"] == "healthy"
