"""Locust load test for PulseQueue's task submission API.

Run against a live API + worker(s) + PostgreSQL + Redis stack - see
benchmarks/README.md for the exact repeatable commands:

    locust -f benchmarks/locustfile.py --host http://localhost:8000
"""

from __future__ import annotations

import random
import uuid

from locust import HttpUser, between, task

_TASK_PAYLOADS: list[tuple[str, dict[str, object]]] = [
    ("generateReport", {"reportName": "weekly-performance", "periodDays": 7}),
    ("calculateMetrics", {"metricName": "latency", "values": [1.0, 2.0, 3.0, 4.0]}),
    ("sendNotification", {"recipientName": "Hema C", "message": "Your report is ready."}),
]
"""A fixed workload mix - three of the five registered task types, all
fast/deterministic. Each submission gets its own Idempotency-Key, so
this measures fresh-task throughput, not idempotency's fast path."""


class PulseQueueUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(5)
    def submitAndCheckTask(self) -> None:
        taskType, payload = random.choice(_TASK_PAYLOADS)
        response = self.client.post(
            "/api/v1/tasks",
            json={"taskType": taskType, "payload": payload},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        if response.status_code == 201:
            taskId = response.json()["taskId"]
            self.client.get(f"/api/v1/tasks/{taskId}", name="/api/v1/tasks/[taskId]")

    @task(1)
    def listRecentTasks(self) -> None:
        self.client.get("/api/v1/tasks?limit=20")
