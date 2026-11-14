import json
import os
from dataclasses import dataclass
from typing import Any

from flask import current_app, has_app_context
from google import genai
from google.genai import errors, types


class GeminiServiceError(Exception):
    """Base error for safely classifying Gemini service failures."""

    code = "gemini_error"


class GeminiConfigurationError(GeminiServiceError):
    code = "gemini_not_configured"


class GeminiAuthenticationError(GeminiServiceError):
    code = "gemini_authentication_failed"


class GeminiRateLimitError(GeminiServiceError):
    code = "gemini_rate_limited"


class GeminiQuotaError(GeminiServiceError):
    code = "gemini_quota_exhausted"


class GeminiProviderError(GeminiServiceError):
    code = "gemini_provider_error"


class GeminiTransientError(GeminiServiceError):
    code = "gemini_transient_error"


class GeminiResponseError(GeminiServiceError):
    code = "gemini_invalid_response"


@dataclass(frozen=True)
class GenerationResult:
    text: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    model: str


class GeminiService:
    def __init__(self, client: Any = None, api_key: str | None = None, model: str | None = None):
        if has_app_context():
            api_key = api_key or current_app.config.get("GEMINI_API_KEY")
            model = model or current_app.config.get("GEMINI_MODEL")

        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise GeminiConfigurationError("Gemini is not configured.")
        self._client = genai.Client(api_key=self._api_key)
        return self._client

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        max_output_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> GenerationResult:
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive.")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2.")

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )

        try:
            response = self._get_client().models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
        except errors.APIError as error:
            self._raise_provider_error(error)

        response_text = response.text
        if not response_text or not response_text.strip():
            raise GeminiResponseError("Gemini returned an empty response.")

        usage = response.usage_metadata
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        total_tokens = int(getattr(usage, "total_token_count", 0) or 0)
        if total_tokens == 0:
            total_tokens = input_tokens + output_tokens

        return GenerationResult(
            text=response_text.strip(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            model=self.model,
        )

    def count_input_tokens(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
    ) -> int:
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        config = types.CountTokensConfig(system_instruction=system_instruction)

        try:
            response = self._get_client().models.count_tokens(
                model=self.model,
                contents=prompt,
                config=config,
            )
        except errors.APIError as error:
            self._raise_provider_error(error)

        token_count = getattr(response, "total_tokens", None)
        if token_count is None or token_count < 0:
            raise GeminiResponseError("Gemini returned invalid input token metadata.")
        return int(token_count)

    def generate_json(self, prompt: str, **kwargs) -> tuple[dict, GenerationResult]:
        result = self.generate_text(prompt, **kwargs)
        try:
            payload = json.loads(result.text)
        except json.JSONDecodeError as error:
            raise GeminiResponseError("Gemini returned malformed JSON.") from error
        if not isinstance(payload, dict):
            raise GeminiResponseError("Gemini JSON response must be an object.")
        return payload, result

    @staticmethod
    def _raise_provider_error(error: errors.APIError) -> None:
        code = getattr(error, "code", None)
        try:
            code = int(code)
        except (TypeError, ValueError):
            code = None
        message = str(getattr(error, "message", "") or "").lower()

        if code in (401, 403):
            raise GeminiAuthenticationError("Gemini authentication or access failed.") from error
        if code == 429:
            if "quota" in message or "resource exhausted" in message:
                raise GeminiQuotaError("Gemini quota is exhausted.") from error
            raise GeminiRateLimitError("Gemini request rate limit was reached.") from error
        if code in (408, 500, 502, 503, 504):
            raise GeminiTransientError("Gemini is temporarily unavailable.") from error
        raise GeminiProviderError("Gemini provider request failed.") from error
