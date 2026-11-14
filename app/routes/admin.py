from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, func, select

from app.extensions import db
from app.models import AIUsageEvent, ResumeAnalysis, User
from app.security.authorization import admin_required
from app.services.settings_service import SettingsService
from app.services.token_manager import TokenManager


admin_bp = Blueprint("admin", __name__)


def _admin_metrics():
    total_users = db.session.scalar(select(func.count(User.id)))
    total_analyses = db.session.scalar(select(func.count(ResumeAnalysis.id)))
    usage = db.session.execute(
        select(
            func.count(AIUsageEvent.id),
            func.coalesce(func.sum(AIUsageEvent.input_tokens), 0),
            func.coalesce(func.sum(AIUsageEvent.output_tokens), 0),
            func.sum(case((AIUsageEvent.status == "failed", 1), else_=0)),
        )
    ).one()
    errors = db.session.execute(
        select(AIUsageEvent.error_code, func.count(AIUsageEvent.id))
        .where(
            AIUsageEvent.status == "failed",
            AIUsageEvent.error_code.is_not(None),
        )
        .group_by(AIUsageEvent.error_code)
        .order_by(func.count(AIUsageEvent.id).desc())
        .limit(10)
    ).all()
    return {
        "total_users": int(total_users or 0),
        "total_analyses": int(total_analyses or 0),
        "ai_requests": int(usage[0] or 0),
        "input_tokens": int(usage[1] or 0),
        "output_tokens": int(usage[2] or 0),
        "total_tokens": int(usage[1] or 0) + int(usage[2] or 0),
        "failed_requests": int(usage[3] or 0),
        "feature_usage": TokenManager().feature_report(),
        "api_errors": [{"code": row[0], "count": row[1]} for row in errors],
    }


@admin_bp.get("/admin")
@login_required
@admin_required
def dashboard():
    metrics = _admin_metrics()
    settings = SettingsService().get_usage_settings(current_app.config)
    return render_template("admin.html", metrics=metrics, settings=settings)


@admin_bp.post("/admin/usage-settings")
@login_required
@admin_required
def update_usage_settings():
    submitted = {
        "AI_MAX_INPUT_TOKENS": request.form.get("AI_MAX_INPUT_TOKENS", ""),
        "AI_MAX_OUTPUT_TOKENS": request.form.get("AI_MAX_OUTPUT_TOKENS", ""),
        "AI_MAX_DAILY_TOKENS_PER_USER": request.form.get("AI_MAX_DAILY_TOKENS_PER_USER", ""),
        "AI_RETRY_ATTEMPTS": request.form.get("AI_RETRY_ATTEMPTS", ""),
        "AI_RETRY_BASE_SECONDS": request.form.get("AI_RETRY_BASE_SECONDS", ""),
    }
    try:
        SettingsService().update_usage_settings(submitted=submitted, updated_by=current_user.id)
    except ValueError as error:
        flash(str(error), "error")
    else:
        current_app.logger.info("AI usage limits updated by admin user %s.", current_user.id)
        flash("AI usage limits updated.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.get("/api/v1/admin/metrics")
@login_required
@admin_required
def api_metrics():
    return jsonify(_admin_metrics())


@admin_bp.get("/api/v1/admin/usage-settings")
@login_required
@admin_required
def api_usage_settings():
    return jsonify(SettingsService().get_usage_settings(current_app.config))
