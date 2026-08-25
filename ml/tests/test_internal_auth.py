from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from scm_ml.service.app import (
    INSECURE_FLAG,
    INTERNAL_TOKEN_HEADER,
    MissingInternalTokenError,
    create_app,
    resolve_internal_token,
)
from scm_ml.service.engine import build_engine
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticWorld

TOKEN = "a-shared-secret-long-enough"
BODY = {
    "schemaVersion": "1",
    "actor": {"userId": "pat", "role": "planner"},
    "question": "Who approves large orders?",
}


@pytest.fixture(scope="module")
def client(small_world: SyntheticWorld, small_service: ForecastService) -> Iterator[TestClient]:
    app = create_app(small_service, build_engine(small_world, small_service), TOKEN)
    with TestClient(app) as c:
        yield c


def test_calls_without_the_token_are_refused(client: TestClient) -> None:
    for response in (
        client.post("/v1/documents/ask", json=BODY),
        client.get("/v1/model"),
        client.get("/v1/telemetry"),
        client.get("/v1/approvals"),
    ):
        assert response.status_code == 401
        assert response.json() == {
            "code": "UNAUTHENTICATED",
            "message": "a valid internal service token is required",
        }


def test_a_wrong_or_empty_token_is_refused(client: TestClient) -> None:
    for token in ("", "wrong-token", TOKEN + "x", TOKEN[:-1]):
        response = client.post(
            "/v1/documents/ask", json=BODY, headers={INTERNAL_TOKEN_HEADER: token}
        )
        assert response.status_code == 401


def test_the_right_token_is_accepted(client: TestClient) -> None:
    response = client.post("/v1/documents/ask", json=BODY, headers={INTERNAL_TOKEN_HEADER: TOKEN})
    assert response.status_code == 200
    assert client.get("/v1/model", headers={INTERNAL_TOKEN_HEADER: TOKEN}).status_code == 200


def test_liveness_needs_no_token_and_reveals_nothing(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "UP", "service": "scm-ml"}


def test_the_service_will_not_start_without_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCM_ML_INTERNAL_TOKEN", raising=False)
    monkeypatch.delenv(INSECURE_FLAG, raising=False)
    with pytest.raises(MissingInternalTokenError, match="SCM_ML_INTERNAL_TOKEN is not set"):
        resolve_internal_token(None)


def test_a_short_secret_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(INSECURE_FLAG, raising=False)
    with pytest.raises(MissingInternalTokenError, match="at least 16"):
        resolve_internal_token("short")


def test_the_secret_can_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCM_ML_INTERNAL_TOKEN", TOKEN)
    assert resolve_internal_token(None) == TOKEN


def test_running_without_authentication_must_be_asked_for_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCM_ML_INTERNAL_TOKEN", raising=False)
    monkeypatch.setenv(INSECURE_FLAG, "1")
    assert resolve_internal_token(None) is None
    monkeypatch.setenv(INSECURE_FLAG, "true")  # only the exact opt-in counts
    with pytest.raises(MissingInternalTokenError):
        resolve_internal_token(None)


def test_app_construction_enforces_the_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCM_ML_INTERNAL_TOKEN", raising=False)
    monkeypatch.delenv(INSECURE_FLAG, raising=False)
    engine: Any = None
    with pytest.raises(MissingInternalTokenError):
        create_app(None, engine)
