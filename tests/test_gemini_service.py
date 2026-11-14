from types import SimpleNamespace

import pytest

from app.services.gemini_service import (
    GeminiConfigurationError,
    GeminiResponseError,
    GeminiService,
)


class FakeModels:
    def __init__(self, response):
        self.response = response
        self.call = None

    def generate_content(self, **kwargs):
        self.call = kwargs
        return self.response

    def count_tokens(self, **kwargs):
        return SimpleNamespace(total_tokens=23)


class FakeClient:
    def __init__(self, response):
        self.models = FakeModels(response)


def test_generation_returns_provider_usage_metadata():
    client = FakeClient(
        SimpleNamespace(
            text="A structured response",
            usage_metadata=SimpleNamespace(
                prompt_token_count=12,
                candidates_token_count=7,
                total_token_count=19,
            ),
        )
    )
    service = GeminiService(client=client, model="test-model")

    result = service.generate_text("Analyze this resume")

    assert result.text == "A structured response"
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (12, 7, 19)
    assert client.models.call["model"] == "test-model"


def test_json_generation_rejects_malformed_provider_output():
    client = FakeClient(
        SimpleNamespace(
            text="not JSON",
            usage_metadata=SimpleNamespace(),
        )
    )
    service = GeminiService(client=client, model="test-model")

    with pytest.raises(GeminiResponseError):
        service.generate_json("Return a JSON object")


def test_generation_requires_provider_configuration():
    service = GeminiService(api_key="", model="test-model")

    with pytest.raises(GeminiConfigurationError):
        service.generate_text("Prompt")
