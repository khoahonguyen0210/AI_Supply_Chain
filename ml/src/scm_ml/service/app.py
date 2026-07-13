"""FastAPI application: the HTTP boundary between the Spring backend and Python."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from scm_ml.forecast.inference import ForecastError

from .contracts import ErrorResponse, ForecastRequest, ForecastResponse
from .forecasting import ForecastService

STATUS_BY_CODE = {
    "UNKNOWN_SERIES": 404,
    "HISTORY_TOO_SHORT": 409,
    "MODEL_NOT_CALIBRATED": 503,
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(code=code, message=message).model_dump(by_alias=True)
    return JSONResponse(status_code=status, content=body)


def create_app(forecasts: ForecastService | None = None) -> FastAPI:
    """Build the app; with no service given, load it from SCM_ML_MODEL_DIR / SCM_ML_DATASET_DIR."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if forecasts is None:
            app.state.forecasts = ForecastService.from_directories(
                Path(os.environ["SCM_ML_MODEL_DIR"]), Path(os.environ["SCM_ML_DATASET_DIR"])
            )
        else:
            app.state.forecasts = forecasts
        yield

    app = FastAPI(title="SCM ML service", version="1", lifespan=lifespan)

    @app.exception_handler(ForecastError)
    async def forecast_error(_: Request, exc: ForecastError) -> JSONResponse:
        return _error(STATUS_BY_CODE.get(exc.code, 422), exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ())[1:])
        return _error(422, "VALIDATION_FAILED", f"{where}: {first.get('msg', 'invalid request')}")

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        return {"status": "UP", "service": "scm-ml", **request.app.state.forecasts.info()}

    @app.get("/v1/model")
    async def model_info(request: Request) -> dict[str, Any]:
        info: dict[str, Any] = request.app.state.forecasts.info()
        return info

    @app.post("/v1/forecast", response_model_by_alias=True)
    async def forecast(request: Request, body: ForecastRequest) -> ForecastResponse:
        response: ForecastResponse = request.app.state.forecasts.forecast(body)
        return response

    return app
