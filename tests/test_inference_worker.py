"""Unit-Tests für den Inference-Worker."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest

from app.inference_worker import (
    InferenceServiceHTTPError,
    InferenceWorkerService,
    inference_service_exception_handler,
)
from app.models import WeekPlanInput


def _week_input() -> WeekPlanInput:
    return WeekPlanInput(
        target_distance="10k",
        race_time_seconds=2400.0,
        weekly_km=80.0,
        experience_years=5,
        current_phase="supportive",
        week_in_phase=4,
        phase_weeks_total=8,
        last_week_workouts=["tempo_continuous"],
        rest_day=1,
        long_run_day=0,
        days_since_hard_workout=3,
        days_to_race=None,
    )


def _worker_ok(request_queue: Any, response_queue: Any) -> None:
    while True:
        message = request_queue.get()
        if message.get("kind") == "shutdown":
            return
        if message.get("kind") == "warmup":
            response_queue.put({
                "request_id": message["request_id"],
                "status": "ok",
                "data": None,
            })
            continue
        response_queue.put({
            "request_id": message["request_id"],
            "status": "ok",
            "data": {"worker": "ok"},
        })


def _worker_timeout_once_then_ok(request_queue: Any, response_queue: Any) -> None:
    marker_path = os.environ.get("CANOVR_TEST_TIMEOUT_MARKER")
    marker = Path(marker_path) if marker_path else None

    while True:
        message = request_queue.get()
        if message.get("kind") == "shutdown":
            return
        if message.get("kind") == "warmup":
            response_queue.put({
                "request_id": message["request_id"],
                "status": "ok",
                "data": None,
            })
            continue

        if marker is not None and not marker.exists():
            marker.write_text("timeout_once", encoding="utf-8")
            time.sleep(1.0)

        response_queue.put({
            "request_id": message["request_id"],
            "status": "ok",
            "data": {"worker": "restarted"},
        })


def _worker_always_timeout(request_queue: Any, response_queue: Any) -> None:
    while True:
        message = request_queue.get()
        if message.get("kind") == "shutdown":
            return
        if message.get("kind") == "warmup":
            response_queue.put({
                "request_id": message["request_id"],
                "status": "ok",
                "data": None,
            })
            continue
        time.sleep(1.0)


def test_worker_start_and_infer_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.inference_worker.WORKER_BOOT_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr("app.inference_worker.INFERENCE_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr("app.inference_worker.WORKER_RETRY_ON_TIMEOUT", 1)

    service = InferenceWorkerService(worker_target=_worker_ok)
    try:
        service.start()
        payload, request_id = service.infer_week(_week_input())
        assert payload == {"worker": "ok"}
        assert request_id
    finally:
        service.shutdown()


def test_worker_timeout_restarts_and_retries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "timeout.marker"
    monkeypatch.setenv("CANOVR_TEST_TIMEOUT_MARKER", str(marker))
    monkeypatch.setattr("app.inference_worker.WORKER_BOOT_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr("app.inference_worker.INFERENCE_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr("app.inference_worker.WORKER_RETRY_ON_TIMEOUT", 1)

    service = InferenceWorkerService(worker_target=_worker_timeout_once_then_ok)
    try:
        service.start()
        payload, _request_id = service.infer_week(_week_input())
        assert marker.exists()
        assert payload == {"worker": "restarted"}
    finally:
        service.shutdown()


def test_worker_timeout_fails_after_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.inference_worker.WORKER_BOOT_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr("app.inference_worker.INFERENCE_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr("app.inference_worker.WORKER_RETRY_ON_TIMEOUT", 1)

    service = InferenceWorkerService(worker_target=_worker_always_timeout)
    try:
        service.start()
        with pytest.raises(InferenceServiceHTTPError) as exc_info:
            service.infer_week(_week_input())
        assert exc_info.value.code == "INFERENCE_TIMEOUT"
    finally:
        service.shutdown()


def test_exception_handler_returns_flat_payload() -> None:
    exc = InferenceServiceHTTPError(
        code="INFERENCE_TIMEOUT",
        detail="timeout",
        request_id="req-123",
    )
    response = inference_service_exception_handler(None, exc)
    assert response.status_code == 503
    assert response.content == {
        "code": "INFERENCE_TIMEOUT",
        "detail": "timeout",
        "request_id": "req-123",
    }
