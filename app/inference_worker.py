"""Inference-Worker für stabile Week-Inferenz.

Isoliert PyReason in einem separaten Prozess, damit Request-Threads nicht
blockieren. Timeouts und Worker-Restarts werden hier zentral gesteuert.
"""

from __future__ import annotations

import json
import logging
import multiprocessing as mp
import os
import queue
import threading
import uuid
from dataclasses import asdict
from typing import Any

from litestar.connection import Request
from litestar.enums import MediaType
from litestar.response import Response

from app.models import WeekPlanInput


INFERENCE_TIMEOUT_SECONDS = 20
WORKER_BOOT_TIMEOUT_SECONDS = 90
WORKER_RETRY_ON_TIMEOUT = 1

_LOGGER = logging.getLogger("canovr.inference_worker")


class InferenceServiceHTTPError(Exception):
    """HTTP-nahe Fehler für deterministische 503-Responses."""

    def __init__(self, code: str, detail: str, request_id: str | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.request_id = request_id or uuid.uuid4().hex
        self.status_code = 503


def inference_service_exception_handler(_: Request[Any, Any, Any], exc: InferenceServiceHTTPError) -> Response:
    """Erzeuge ein stabiles, flaches Fehler-Payload für den Client."""
    return Response(
        status_code=exc.status_code,
        media_type=MediaType.JSON,
        content={
            "code": exc.code,
            "detail": exc.detail,
            "request_id": exc.request_id,
        },
    )


def _default_warmup_payload() -> dict[str, Any]:
    """Kleiner, gültiger Week-Input für Startup-Warmup."""
    return WeekPlanInput(
        target_distance="10k",
        race_time_seconds=2400.0,
        weekly_km=70.0,
        experience_years=3,
        current_phase="general",
        week_in_phase=1,
        phase_weeks_total=8,
        last_week_workouts=[],
        rest_day=1,
        long_run_day=0,
        days_since_hard_workout=3,
        days_to_race=None,
    ).model_dump()


def _worker_main(request_queue: Any, response_queue: Any) -> None:
    """Worker-Prozess: führt Week-Inferenz isoliert aus."""
    from app.models import WeekPlanInput as WorkerWeekPlanInput
    from app.reasoner import run_week_inference

    while True:
        message = request_queue.get()
        if not isinstance(message, dict):
            continue

        request_id = str(message.get("request_id", ""))
        kind = message.get("kind")
        payload = message.get("payload", {})

        if kind == "shutdown":
            return

        try:
            if kind == "warmup":
                warmup_input = WorkerWeekPlanInput(**payload)
                run_week_inference(warmup_input)
                response_queue.put({"request_id": request_id, "status": "ok", "data": None})
                continue

            if kind == "infer_week":
                week_input = WorkerWeekPlanInput(**payload)
                inference = run_week_inference(week_input)
                response_queue.put({
                    "request_id": request_id,
                    "status": "ok",
                    "data": asdict(inference),
                })
                continue

            response_queue.put({
                "request_id": request_id,
                "status": "error",
                "detail": f"Unbekannter Worker-Call: {kind}",
            })
        except Exception as exc:  # noqa: BLE001
            response_queue.put({
                "request_id": request_id,
                "status": "error",
                "detail": f"{exc.__class__.__name__}: {exc}",
            })


class InferenceWorkerService:
    """Single-Worker-Service pro App-Instanz."""

    def __init__(self, worker_target: Any = _worker_main) -> None:
        self._ctx = mp.get_context("spawn")
        self._worker_target = worker_target
        self._process: Any = None
        self._request_queue: Any = None
        self._response_queue: Any = None
        self._service_lock = threading.Lock()
        self._call_lock = threading.Lock()
        self._started = False

    def start(self) -> None:
        """Worker starten und via Warmup validieren."""
        with self._service_lock:
            if self._started and self._is_alive():
                return
            self._spawn_worker_locked()

        try:
            self._send_and_receive(
                kind="warmup",
                payload=_default_warmup_payload(),
                timeout_seconds=WORKER_BOOT_TIMEOUT_SECONDS,
            )
        except InferenceServiceHTTPError as exc:
            self.shutdown()
            raise InferenceServiceHTTPError(
                code="INFERENCE_UNAVAILABLE",
                detail=f"Inference-Worker Warmup fehlgeschlagen: {exc.detail}",
                request_id=exc.request_id,
            ) from exc

        with self._service_lock:
            self._started = True

        self._log_event("inference_worker_started", boot_timeout_s=WORKER_BOOT_TIMEOUT_SECONDS)

    def shutdown(self) -> None:
        """Worker sauber stoppen."""
        with self._service_lock:
            if self._process and self._process.is_alive() and self._request_queue is not None:
                try:
                    self._request_queue.put({"request_id": "shutdown", "kind": "shutdown", "payload": {}})
                except Exception:  # noqa: BLE001
                    pass
                self._process.join(timeout=5)
                if self._process.is_alive():
                    self._process.terminate()
                    self._process.join(timeout=3)

            self._process = None
            self._request_queue = None
            self._response_queue = None
            self._started = False

    def restart(self, reason: str, attempt: int) -> None:
        """Worker neu starten und erneut validieren."""
        self._log_event("inference_worker_restart", restart_reason=reason, attempt=attempt)
        self.shutdown()
        self.start()

    def infer_week(self, inp: WeekPlanInput) -> tuple[dict[str, Any], str]:
        """Week-Inferenz mit Timeout + einmaligem Retry."""
        last_error: InferenceServiceHTTPError | None = None

        for attempt in range(WORKER_RETRY_ON_TIMEOUT + 1):
            try:
                self._ensure_started()
                response, request_id = self._send_and_receive(
                    kind="infer_week",
                    payload=inp.model_dump(),
                    timeout_seconds=INFERENCE_TIMEOUT_SECONDS,
                )
                if not isinstance(response, dict):
                    raise InferenceServiceHTTPError(
                        code="INFERENCE_UNAVAILABLE",
                        detail="Inference-Worker lieferte kein gültiges Ergebnis",
                        request_id=request_id,
                    )
                return response, request_id
            except InferenceServiceHTTPError as exc:
                last_error = exc
                can_retry = (
                    exc.code == "INFERENCE_TIMEOUT"
                    and attempt < WORKER_RETRY_ON_TIMEOUT
                )
                if not can_retry:
                    break
                self.restart(
                    reason=f"inference_timeout_request_{exc.request_id}",
                    attempt=attempt + 1,
                )

        if last_error is None:
            raise InferenceServiceHTTPError(
                code="INFERENCE_UNAVAILABLE",
                detail="Inference-Worker Fehler ohne Detail",
            )

        if last_error.code == "INFERENCE_TIMEOUT":
            try:
                self.restart(
                    reason=f"inference_timeout_terminal_{last_error.request_id}",
                    attempt=WORKER_RETRY_ON_TIMEOUT + 1,
                )
            except InferenceServiceHTTPError:
                # Folgefehler beim Self-Healing maskieren den ursprünglichen Timeout nicht.
                pass
            raise InferenceServiceHTTPError(
                code="INFERENCE_TIMEOUT",
                detail=(
                    f"Inferenz überschritt Timeout von {INFERENCE_TIMEOUT_SECONDS}s "
                    f"(Retries: {WORKER_RETRY_ON_TIMEOUT})"
                ),
                request_id=last_error.request_id,
            ) from last_error

        raise last_error

    def _ensure_started(self) -> None:
        if self._started and self._is_alive():
            return
        self.start()

    def _is_alive(self) -> bool:
        return bool(self._process and self._process.is_alive())

    def _spawn_worker_locked(self) -> None:
        self._request_queue = self._ctx.Queue()
        self._response_queue = self._ctx.Queue()
        self._process = self._ctx.Process(
            target=self._worker_target,
            args=(self._request_queue, self._response_queue),
            daemon=True,
        )
        self._process.start()

    def _send_and_receive(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> tuple[Any, str]:
        request_id = uuid.uuid4().hex
        message = {"request_id": request_id, "kind": kind, "payload": payload}

        with self._call_lock:
            if not self._is_alive() or self._request_queue is None or self._response_queue is None:
                raise InferenceServiceHTTPError(
                    code="INFERENCE_UNAVAILABLE",
                    detail="Inference-Worker ist nicht gestartet",
                    request_id=request_id,
                )

            self._request_queue.put(message)
            try:
                response = self._response_queue.get(timeout=timeout_seconds)
            except queue.Empty as exc:
                raise InferenceServiceHTTPError(
                    code="INFERENCE_TIMEOUT",
                    detail=f"Inference-Worker antwortete nicht in {timeout_seconds}s",
                    request_id=request_id,
                ) from exc

        if not isinstance(response, dict):
            raise InferenceServiceHTTPError(
                code="INFERENCE_UNAVAILABLE",
                detail="Inference-Worker lieferte ein ungültiges Antwortformat",
                request_id=request_id,
            )

        response_request_id = str(response.get("request_id", ""))
        if response_request_id != request_id:
            raise InferenceServiceHTTPError(
                code="INFERENCE_UNAVAILABLE",
                detail=(
                    "Antwort-Korrelation fehlgeschlagen "
                    f"(expected={request_id}, got={response_request_id})"
                ),
                request_id=request_id,
            )

        if response.get("status") == "error":
            raise InferenceServiceHTTPError(
                code="INFERENCE_UNAVAILABLE",
                detail=str(response.get("detail", "Unbekannter Worker-Fehler")),
                request_id=request_id,
            )

        return response.get("data"), request_id

    def _log_event(self, event: str, **fields: Any) -> None:
        payload = {"event": event, **fields}
        _LOGGER.info(json.dumps(payload, ensure_ascii=False))


_GLOBAL_SERVICE: InferenceWorkerService | None = None
_GLOBAL_LOCK = threading.Lock()


def get_inference_worker() -> InferenceWorkerService:
    """Globaler Worker-Service für die App-Instanz."""
    global _GLOBAL_SERVICE
    if _GLOBAL_SERVICE is None:
        with _GLOBAL_LOCK:
            if _GLOBAL_SERVICE is None:
                _GLOBAL_SERVICE = InferenceWorkerService()
    return _GLOBAL_SERVICE


def should_skip_worker_startup() -> bool:
    """Optionaler Schalter für Umgebungen, die keinen Worker booten sollen."""
    return os.environ.get("CANOVR_SKIP_INFERENCE_STARTUP", "0") == "1"
