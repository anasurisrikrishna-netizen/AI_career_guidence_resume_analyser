from app.extensions import db
from app.models import AIUsageEvent, User
from app.services.gemini_service import (
    GeminiRateLimitError,
    GenerationResult,
)
from app.services.token_manager import TokenManager, UsageLimitExceeded


class FakeGeminiService:
    model = "test-model"

    def __init__(self, input_tokens=12, failures=0):
        self.input_tokens = input_tokens
        self.failures = failures
        self.generate_calls = []

    def count_input_tokens(self, prompt, *, system_instruction=None):
        return self.input_tokens

    def generate_text(self, prompt, **kwargs):
        self.generate_calls.append(kwargs)
        if self.failures:
            self.failures -= 1
            raise GeminiRateLimitError("rate limited")
        return GenerationResult("result", 12, 8, 20, self.model)


def test_token_manager_records_actual_usage(app):
    with app.app_context():
        user = User(email="usage@example.com", password_hash="unused")
        db.session.add(user)
        db.session.commit()

        service = FakeGeminiService()
        result = TokenManager(service).generate_text(
            user_id=user.id,
            feature="resume_analysis",
            prompt="short prompt",
            max_output_tokens=128,
        )

        event = db.session.query(AIUsageEvent).one()
        assert result.text == "result"
        assert event.status == "succeeded"
        assert event.estimated_input_tokens == 12
        assert (event.input_tokens, event.output_tokens) == (12, 8)
        assert event.total_tokens == 20
        assert service.generate_calls[0]["max_output_tokens"] == 128


def test_token_manager_rejects_input_over_limit(app):
    with app.app_context():
        app.config["AI_MAX_INPUT_TOKENS"] = 10
        service = FakeGeminiService(input_tokens=11)

        try:
            TokenManager(service).generate_text(
                user_id=None,
                feature="resume_analysis",
                prompt="large prompt",
            )
        except UsageLimitExceeded:
            pass
        else:
            raise AssertionError("Expected the configured input limit to reject the request.")

        event = db.session.query(AIUsageEvent).one()
        assert event.status == "rejected"
        assert event.error_code == "ai_usage_limit_exceeded"
        assert service.generate_calls == []


def test_token_manager_retries_rate_limited_generation(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr("app.services.token_manager.time.sleep", lambda _: None)
        service = FakeGeminiService(failures=1)

        result = TokenManager(service).generate_text(
            user_id=None,
            feature="interview",
            prompt="practice question",
        )

        assert result.text == "result"
        assert len(service.generate_calls) == 2
        assert db.session.query(AIUsageEvent).one().status == "succeeded"
