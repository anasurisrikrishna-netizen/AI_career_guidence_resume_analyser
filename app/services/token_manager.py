import time
from datetime import datetime, time as datetime_time, timezone
from uuid import uuid4

from flask import current_app
from flask import has_app_context
from sqlalchemy import case, func

from app.extensions import db
from app.models import AIUsageEvent, AIUsageSetting
from app.services.gemini_service import (
    GeminiRateLimitError,
    GeminiService,
    GeminiServiceError,
    GeminiTransientError,
)


class UsageLimitExceeded(Exception):
    code = "ai_usage_limit_exceeded"


class TokenManager:
    def __init__(self, gemini_service: GeminiService | None = None):
        self.gemini_service = gemini_service or GeminiService()

    def generate_text(
        self,
        *,
        user_id: int | None,
        feature: str,
        prompt: str,
        system_instruction: str | None = None,
        max_output_tokens: int = 2048,
        temperature: float = 0.2,
    ):
        if not feature or len(feature) > 48:
            raise ValueError("feature must contain between 1 and 48 characters.")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive.")

        request_id = uuid4().hex
        model = self.gemini_service.model
        estimated_input_tokens = 0
        output_limit = min(
            max_output_tokens,
            self._setting("AI_MAX_OUTPUT_TOKENS", 4096),
        )
        attempts = min(max(self._setting("AI_RETRY_ATTEMPTS", 3), 1), 5)
        base_delay = max(self._setting("AI_RETRY_BASE_SECONDS", 0.5), 0)
        for attempt in range(attempts):
            try:
                estimated_input_tokens = self.gemini_service.count_input_tokens(
                    prompt,
                    system_instruction=system_instruction,
                )
                break
            except (GeminiRateLimitError, GeminiTransientError) as error:
                if attempt + 1 == attempts:
                    self._record(
                        request_id=request_id,
                        user_id=user_id,
                        feature=feature,
                        model=model,
                        estimated_input_tokens=estimated_input_tokens,
                        status="failed",
                        error_code=error.code,
                    )
                    raise
                time.sleep(min(base_delay * (2**attempt), 8))
            except GeminiServiceError as error:
                self._record(
                    request_id=request_id,
                    user_id=user_id,
                    feature=feature,
                    model=model,
                    estimated_input_tokens=estimated_input_tokens,
                    status="failed",
                    error_code=error.code,
                )
                raise

        try:
            self._check_limits(user_id, estimated_input_tokens, output_limit)
        except UsageLimitExceeded as error:
            self._record(
                request_id=request_id,
                user_id=user_id,
                feature=feature,
                model=model,
                estimated_input_tokens=estimated_input_tokens,
                status="rejected",
                error_code=error.code,
            )
            raise

        for attempt in range(attempts):
            try:
                result = self.gemini_service.generate_text(
                    prompt,
                    system_instruction=system_instruction,
                    max_output_tokens=output_limit,
                    temperature=temperature,
                )
            except (GeminiRateLimitError, GeminiTransientError) as error:
                if attempt + 1 == attempts:
                    self._record(
                        request_id=request_id,
                        user_id=user_id,
                        feature=feature,
                        model=model,
                        estimated_input_tokens=estimated_input_tokens,
                        status="failed",
                        error_code=error.code,
                    )
                    raise
                time.sleep(min(base_delay * (2**attempt), 8))
            except GeminiServiceError as error:
                self._record(
                    request_id=request_id,
                    user_id=user_id,
                    feature=feature,
                    model=model,
                    estimated_input_tokens=estimated_input_tokens,
                    status="failed",
                    error_code=error.code,
                )
                raise
            else:
                self._record(
                    request_id=request_id,
                    user_id=user_id,
                    feature=feature,
                    model=result.model,
                    estimated_input_tokens=estimated_input_tokens,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    status="succeeded",
                )
                return result

    def user_report(self, user_id: int) -> dict:
        rows = (
            db.session.query(
                AIUsageEvent.feature,
                func.count(AIUsageEvent.id),
                func.coalesce(func.sum(AIUsageEvent.input_tokens), 0),
                func.coalesce(func.sum(AIUsageEvent.output_tokens), 0),
            )
            .filter(AIUsageEvent.user_id == user_id)
            .group_by(AIUsageEvent.feature)
            .all()
        )
        return {
            row[0]: {
                "requests": row[1],
                "input_tokens": int(row[2]),
                "output_tokens": int(row[3]),
                "total_tokens": int(row[2]) + int(row[3]),
            }
            for row in rows
        }

    def feature_report(self) -> dict:
        rows = (
            db.session.query(
                AIUsageEvent.feature,
                func.count(AIUsageEvent.id),
                func.coalesce(func.sum(AIUsageEvent.input_tokens), 0),
                func.coalesce(func.sum(AIUsageEvent.output_tokens), 0),
                func.sum(case((AIUsageEvent.status == "failed", 1), else_=0)),
            )
            .group_by(AIUsageEvent.feature)
            .all()
        )
        return {
            row[0]: {
                "requests": row[1],
                "input_tokens": int(row[2]),
                "output_tokens": int(row[3]),
                "total_tokens": int(row[2]) + int(row[3]),
                "failed_requests": int(row[4] or 0),
            }
            for row in rows
        }

    def _check_limits(self, user_id: int | None, input_tokens: int, output_tokens: int) -> None:
        if input_tokens > self._setting("AI_MAX_INPUT_TOKENS", 20000):
            raise UsageLimitExceeded("Estimated input exceeds the per-request token limit.")

        daily_limit = self._setting("AI_MAX_DAILY_TOKENS_PER_USER", 100000)
        if user_id is None or daily_limit <= 0:
            return

        now = datetime.now(timezone.utc)
        day_start = datetime.combine(now.date(), datetime_time.min, tzinfo=timezone.utc)
        used_tokens = (
            db.session.query(
                func.coalesce(
                    func.sum(AIUsageEvent.input_tokens + AIUsageEvent.output_tokens),
                    0,
                )
            )
            .filter(
                AIUsageEvent.user_id == user_id,
                AIUsageEvent.created_at >= day_start,
                AIUsageEvent.status == "succeeded",
            )
            .scalar()
        )
        if int(used_tokens or 0) + input_tokens + output_tokens > daily_limit:
            raise UsageLimitExceeded("Daily AI token allowance would be exceeded.")

    def _record(
        self,
        *,
        request_id: str,
        user_id: int | None,
        feature: str,
        model: str,
        estimated_input_tokens: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        status: str,
        error_code: str | None = None,
    ) -> None:
        db.session.add(
            AIUsageEvent(
                user_id=user_id,
                request_id=request_id,
                feature=feature,
                model=model,
                estimated_input_tokens=estimated_input_tokens,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                status=status,
                error_code=error_code,
            )
        )
        db.session.commit()

    @staticmethod
    def _setting(name: str, default):
        if has_app_context():
            override = db.session.get(AIUsageSetting, name)
            if override is not None:
                return int(override.numeric_value) if name != "AI_RETRY_BASE_SECONDS" else float(override.numeric_value)
            return current_app.config.get(name, default)
        return default
