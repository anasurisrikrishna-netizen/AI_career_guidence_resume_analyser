import pytest

from app import create_app


def test_app_refuses_missing_or_example_secret_key():
    class MissingSecretConfig:
        TESTING = True
        SECRET_KEY = "replace-with-a-long-random-secret"

    with pytest.raises(RuntimeError, match="unique SECRET_KEY"):
        create_app(MissingSecretConfig)


def test_dynamic_responses_have_security_and_cache_headers(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
