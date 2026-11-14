import math

from sqlalchemy import select

from app.extensions import db
from app.models import AIUsageSetting


SETTING_RULES = {
    "AI_MAX_INPUT_TOKENS": (1, 100000, int),
    "AI_MAX_OUTPUT_TOKENS": (1, 8192, int),
    "AI_MAX_DAILY_TOKENS_PER_USER": (0, 1000000, int),
    "AI_RETRY_ATTEMPTS": (1, 5, int),
    "AI_RETRY_BASE_SECONDS": (0, 5, float),
}
SETTING_DEFAULTS = {
    "AI_MAX_INPUT_TOKENS": 20000,
    "AI_MAX_OUTPUT_TOKENS": 4096,
    "AI_MAX_DAILY_TOKENS_PER_USER": 100000,
    "AI_RETRY_ATTEMPTS": 3,
    "AI_RETRY_BASE_SECONDS": 0.5,
}


class SettingsService:
    def get_usage_settings(self, config) -> dict[str, int | float]:
        values = {name: config.get(name, SETTING_DEFAULTS[name]) for name in SETTING_RULES}
        overrides = db.session.execute(
            select(AIUsageSetting).where(AIUsageSetting.setting_name.in_(SETTING_RULES))
        ).scalars()
        for override in overrides:
            converter = SETTING_RULES[override.setting_name][2]
            values[override.setting_name] = converter(override.numeric_value)
        return values

    def update_usage_settings(self, *, submitted: dict[str, object], updated_by: int) -> dict:
        if set(submitted) != set(SETTING_RULES):
            raise ValueError("Provide every configurable AI usage limit.")

        validated = {}
        for name, (minimum, maximum, converter) in SETTING_RULES.items():
            try:
                raw_value = submitted[name]
                if isinstance(raw_value, bool):
                    raise ValueError
                numeric_value = converter(raw_value)
                if isinstance(numeric_value, float) and not math.isfinite(numeric_value):
                    raise ValueError
            except (TypeError, ValueError) as error:
                raise ValueError(f"{name} must be a valid number.") from error
            if not minimum <= numeric_value <= maximum:
                raise ValueError(f"{name} must be between {minimum} and {maximum}.")
            validated[name] = numeric_value

        for name, value in validated.items():
            setting = db.session.get(AIUsageSetting, name)
            if setting is None:
                setting = AIUsageSetting(setting_name=name, numeric_value=float(value))
                db.session.add(setting)
            else:
                setting.numeric_value = float(value)
            setting.updated_by = updated_by
        db.session.commit()
        return validated
