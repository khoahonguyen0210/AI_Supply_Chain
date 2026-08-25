"""FastAPI application: the HTTP boundary between the Spring backend and Python."""

from __future__ import annotations

import hmac
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from scm_ml.forecast.inference import ForecastError
from scm_ml.synthetic import SyntheticConfig, generate_world

from .contracts import ErrorResponse, ForecastRequest, ForecastResponse
from .engine import EngineError, EngineService, build_engine
from .engine_contracts import (
    AgentTaskRequest,
    ApprovalDecisionRequest,
    DocumentQuestionRequest,
    EngineResponse,
    OptimizeRequest,
    ScenarioRunRequest,
    SupplierPerformanceRequest,
    SupplierSearchRequest,
)
from .forecasting import ForecastService
from .quality import DEFAULT_ROOT, quality_summary

STATUS_BY_CODE = {
    "UNKNOWN_SERIES": 404,
    "HISTORY_TOO_SHORT": 409,
    "MODEL_NOT_CALIBRATED": 503,
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(code=code, message=message).model_dump(by_alias=True)
    return JSONResponse(status_code=status, content=body)


INTERNAL_TOKEN_HEADER = "X-Internal-Token"
INSECURE_FLAG = "SCM_ML_INSECURE_NO_AUTH"


class MissingInternalTokenError(RuntimeError):
    pass


def resolve_internal_token(configured: str | None) -> str | None:
    """The shared secret the backend must present; None only when auth is switched off explicitly.

    The planning engine trusts the actor named in a request, so it must only ever be reachable by
    the backend. Starting without a secret is therefore an error unless SCM_ML_INSECURE_NO_AUTH=1
    says the caller means it (local experiments).
    """

    token = configured if configured is not None else os.environ.get("SCM_ML_INTERNAL_TOKEN")
    if token:
        if len(token) < 16:
            raise MissingInternalTokenError("SCM_ML_INTERNAL_TOKEN must be at least 16 characters")
        return token
    if os.environ.get(INSECURE_FLAG) == "1":
        return None
    raise MissingInternalTokenError(
        "SCM_ML_INTERNAL_TOKEN is not set; set it (and the same value as the backend's "
        f"SCM_ML_INTERNAL_TOKEN), or set {INSECURE_FLAG}=1 to run without service authentication"
    )


def create_app(
    forecasts: ForecastService | None = None,
    engine: EngineService | None = None,
    internal_token: str | None = None,
    *,
    require_token: bool = True,
) -> FastAPI:
    """Build the app; services not given are loaded from the environment.

    Every route except /health needs the shared internal token (see `resolve_internal_token`).
    Tests that are not about authentication pass `require_token=False`.

    SCM_ML_MODEL_DIR / SCM_ML_DATASET_DIR locate the forecast model; the planning engine is built
    on the default synthetic world with SCM_ML_PLANNER (rule|claude), SCM_ML_EMBEDDER
    (hashing|fastembed) and SCM_ML_STATE_PATH (SQLite file for tasks and approvals).
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if forecasts is None:
            app.state.forecasts = ForecastService.from_directories(
                Path(os.environ["SCM_ML_MODEL_DIR"]), Path(os.environ["SCM_ML_DATASET_DIR"])
            )
        else:
            app.state.forecasts = forecasts
        if engine is None:
            app.state.engine = build_engine(
                generate_world(SyntheticConfig()),
                app.state.forecasts,
                planner_name=os.environ.get("SCM_ML_PLANNER", "rule"),
                embedder_name=os.environ.get("SCM_ML_EMBEDDER", "hashing"),
                state_path=os.environ.get("SCM_ML_STATE_PATH", ":memory:"),
            )
        else:
            app.state.engine = engine
        yield

    app = FastAPI(title="SCM ML service", version="1", lifespan=lifespan)
    token = resolve_internal_token(internal_token) if require_token else None

    @app.middleware("http")
    async def require_internal_token(request: Request, call_next: Any) -> Any:
        if token is not None and request.url.path != "/health":
            presented = request.headers.get(INTERNAL_TOKEN_HEADER, "")
            if not hmac.compare_digest(presented.encode(), token.encode()):
                return _error(401, "UNAUTHENTICATED", "a valid internal service token is required")
        return await call_next(request)

    @app.exception_handler(ForecastError)
    async def forecast_error(_: Request, exc: ForecastError) -> JSONResponse:
        return _error(STATUS_BY_CODE.get(exc.code, 422), exc.code, exc.message)

    @app.exception_handler(EngineError)
    async def engine_error(_: Request, exc: EngineError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ())[1:])
        return _error(422, "VALIDATION_FAILED", f"{where}: {first.get('msg', 'invalid request')}")

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness only; details are behind the token at /v1/model."""
        return {"status": "UP", "service": "scm-ml"}

    @app.get("/v1/model")
    async def model_info(request: Request) -> dict[str, Any]:
        info: dict[str, Any] = {
            **request.app.state.forecasts.info(),
            "engine": request.app.state.engine.info(),
        }
        return info

    @app.post("/v1/forecast", response_model_by_alias=True)
    async def forecast(request: Request, body: ForecastRequest) -> ForecastResponse:
        telemetry = request.app.state.engine.telemetry
        started = time.perf_counter()
        try:
            response: ForecastResponse = request.app.state.forecasts.forecast(body)
        except Exception:
            telemetry.forecast(time.perf_counter() - started, ok=False)
            raise
        telemetry.forecast(time.perf_counter() - started, ok=True)
        return response

    @app.get("/v1/telemetry")
    def telemetry_snapshot(request: Request) -> dict[str, Any]:
        """Runtime counters and latencies, plus the headline offline-evaluation results."""
        return {
            "runtime": request.app.state.engine.telemetry.snapshot(),
            "quality": quality_summary(Path(os.environ.get("SCM_ML_EXPERIMENT_DIR", DEFAULT_ROOT))),
        }

    def engine_of(request: Request) -> EngineService:
        service: EngineService = request.app.state.engine
        return service

    # Engine calls are synchronous and CPU-bound, so they are plain `def` endpoints that run in
    # the threadpool and leave /health responsive while a long optimization runs.
    @app.post("/v1/suppliers/search")
    def search_suppliers(request: Request, body: SupplierSearchRequest) -> EngineResponse:
        return EngineResponse(data=engine_of(request).search_suppliers(body))

    @app.post("/v1/suppliers/performance")
    def supplier_performance(request: Request, body: SupplierPerformanceRequest) -> EngineResponse:
        return EngineResponse(data=engine_of(request).supplier_performance(body))

    @app.post("/v1/plans/optimize")
    def optimize(request: Request, body: OptimizeRequest) -> EngineResponse:
        return EngineResponse(data=engine_of(request).optimize(body))

    @app.post("/v1/scenarios/run")
    def run_scenario(request: Request, body: ScenarioRunRequest) -> EngineResponse:
        return EngineResponse(data=engine_of(request).run_scenario(body))

    @app.post("/v1/documents/ask")
    def ask_documents(request: Request, body: DocumentQuestionRequest) -> EngineResponse:
        return EngineResponse(data=engine_of(request).ask_documents(body))

    @app.post("/v1/agent/tasks")
    def run_agent(request: Request, body: AgentTaskRequest) -> EngineResponse:
        return EngineResponse(data=engine_of(request).run_agent(body))

    @app.get("/v1/agent/tasks/{task_id}")
    def get_task(request: Request, task_id: str) -> EngineResponse:
        return EngineResponse(data=engine_of(request).get_task(task_id))

    @app.get("/v1/approvals")
    def list_approvals(request: Request, status: str | None = None) -> EngineResponse:
        return EngineResponse(data={"approvals": engine_of(request).list_approvals(status)})

    @app.get("/v1/approvals/{approval_id}")
    def get_approval(request: Request, approval_id: str) -> EngineResponse:
        return EngineResponse(data=engine_of(request).get_approval(approval_id))

    @app.post("/v1/approvals/{approval_id}/decision")
    def decide_approval(
        request: Request, approval_id: str, body: ApprovalDecisionRequest
    ) -> EngineResponse:
        return EngineResponse(data=engine_of(request).decide_approval(approval_id, body))

    return app
