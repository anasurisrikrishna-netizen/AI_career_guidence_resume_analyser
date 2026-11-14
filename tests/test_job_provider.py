import json
from io import BytesIO
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError

import pytest

from app.services.job_provider import (
    AdzunaClient,
    JobProviderConfigurationError,
    JobProviderRateLimitError,
    JobProviderResponseError,
    safe_adzuna_redirect_url,
)


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return self.body[:size]


def _job_result(**overrides):
    result = {
        "id": "12345",
        "title": "Python Developer",
        "description": "Build and test Python services.",
        "company": {"display_name": "Example Employer"},
        "location": {"display_name": "Bengaluru"},
        "redirect_url": "http://www.adzuna.in/jobs/land/ad/12345?utm_source=api",
        "created": "2026-11-14T10:00:00Z",
        "salary_min": 500000,
        "salary_max": 800000,
        "contract_type": "permanent",
    }
    result.update(overrides)
    return result


def test_adzuna_client_returns_only_provider_data_and_preserves_tracking(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeResponse(
            json.dumps({"count": 1, "results": [_job_result()]}).encode()
        )

    monkeypatch.setattr("app.services.job_provider.urlopen", fake_urlopen)
    result = AdzunaClient(
        app_id="local-id",
        app_key="local-secret",
        country_code="in",
        timeout_seconds=2,
    ).search("Python developer", "Bengaluru")

    listing = result.listings[0]
    query = parse_qs(urlsplit(captured["url"]).query)
    assert urlsplit(captured["url"]).path.endswith("/jobs/in/search/1")
    assert query["what"] == ["Python developer"]
    assert query["where"] == ["Bengaluru"]
    assert query["app_key"] == ["local-secret"]
    assert captured["timeout"] == 2
    assert listing.title == "Python Developer"
    assert listing.apply_url == "https://www.adzuna.in/jobs/land/ad/12345?utm_source=api"


def test_adzuna_client_requires_credentials_and_validates_search(monkeypatch):
    with pytest.raises(JobProviderConfigurationError):
        AdzunaClient(app_id="", app_key="", country_code="in").search("Python")
    with pytest.raises(ValueError):
        AdzunaClient(app_id="id", app_key="key").search(" " )
    with pytest.raises(ValueError):
        AdzunaClient(app_id="id", app_key="key").search("x" * 121)


def test_adzuna_client_rejects_bad_provider_shapes(monkeypatch):
    monkeypatch.setattr(
        "app.services.job_provider.urlopen",
        lambda request, timeout: FakeResponse(b'{"count": 1, "results": [{}]}'),
    )
    with pytest.raises(JobProviderResponseError):
        AdzunaClient(app_id="id", app_key="key").search("Python")


def test_adzuna_rate_limit_is_classified(monkeypatch):
    def raise_rate_limit(request, timeout):
        raise HTTPError(request.full_url, 429, "rate limited", {}, BytesIO(b""))

    monkeypatch.setattr("app.services.job_provider.urlopen", raise_rate_limit)
    with pytest.raises(JobProviderRateLimitError):
        AdzunaClient(app_id="id", app_key="key").search("Python")


def test_job_redirects_are_https_and_limited_to_adzuna():
    assert safe_adzuna_redirect_url("http://adzuna.in/jobs/123").startswith("https://")
    assert safe_adzuna_redirect_url("https://attacker.example/jobs/123") is None
    assert safe_adzuna_redirect_url("javascript:alert(1)") is None
