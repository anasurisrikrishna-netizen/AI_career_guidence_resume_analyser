from flask import Blueprint, current_app, flash, jsonify, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from app.data.career_roles import CAREER_ROLE_SKILLS
from app.extensions import db
from app.models import Resume, ResumeAnalysis
from app.services.career_service import CareerGuidanceService
from app.services.gemini_service import GeminiServiceError
from app.services.token_manager import UsageLimitExceeded


careers_bp = Blueprint("careers", __name__)


def _failure_message(error: GeminiServiceError) -> str:
    if error.code == "gemini_not_configured":
        return "Career guidance is not configured yet. Please try again later."
    if error.code in ("gemini_rate_limited", "gemini_transient_error"):
        return "The AI service is busy right now. Please try again shortly."
    if error.code == "gemini_quota_exhausted":
        return "AI service capacity is temporarily unavailable. Please try again later."
    return "Career guidance could not be completed. Please try again later."


def _roadmap_json(roadmap):
    return {
        "id": roadmap.id,
        "target_role": roadmap.target_role,
        "current_skills": roadmap.current_skills,
        "required_skills": roadmap.required_skills,
        "skill_gaps": roadmap.skill_gaps,
        "learning_phases": roadmap.roadmap,
        "related_roles": roadmap.related_roles,
        "created_at": roadmap.created_at.isoformat(),
    }


@careers_bp.get("/careers")
@login_required
def workspace():
    roadmaps = CareerGuidanceService().user_roadmaps(current_user.id)
    resumes = db.session.execute(
        select(Resume)
        .where(Resume.user_id == current_user.id)
        .order_by(Resume.created_at.desc())
    ).scalars().all()
    analyzed_resumes = [
        resume for resume in resumes
        if any(analysis.user_id == current_user.id for analysis in resume.analyses)
    ]
    return render_template(
        "careers.html",
        roles=CAREER_ROLE_SKILLS,
        roadmaps=roadmaps,
        resumes=analyzed_resumes,
    )


@careers_bp.post("/careers/roadmaps")
@login_required
def create_roadmap():
    role = request.form.get("target_role", "")
    raw_skills = request.form.get("current_skills", "")
    skills = [skill.strip() for skill in raw_skills.split(",") if skill.strip()]
    try:
        resume_id = int(request.form["resume_id"]) if request.form.get("resume_id") else None
        roadmap = CareerGuidanceService().create_roadmap(
            user_id=current_user.id,
            role=role,
            current_skills=skills,
            resume_id=resume_id,
        )
    except LookupError as error:
        flash(str(error), "error")
    except ValueError as error:
        flash(str(error), "error")
    except UsageLimitExceeded as error:
        flash(str(error), "error")
    except GeminiServiceError as error:
        current_app.logger.warning("Career guidance failed for user %s: %s.", current_user.id, error.code)
        flash(_failure_message(error), "error")
    else:
        flash("Your career roadmap is ready. Review the steps and adapt them to your goals.", "success")
    return workspace()


@careers_bp.post("/api/v1/careers/roadmaps")
@login_required
def api_create_roadmap():
    if not request.is_json:
        return jsonify({"error": {"code": "json_required", "message": "Send a JSON request body."}}), 415
    payload = request.get_json()
    if (
        not isinstance(payload, dict)
        or set(payload) - {"target_role", "current_skills", "resume_id"}
        or not {"target_role", "current_skills"}.issubset(payload)
    ):
        return jsonify(
            {"error": {"code": "invalid_request", "message": "Provide target_role and current_skills."}}
        ), 400
    resume_id = payload.get("resume_id")
    if resume_id is not None and (isinstance(resume_id, bool) or not isinstance(resume_id, int)):
        return jsonify({"error": {"code": "invalid_request", "message": "resume_id must be an integer."}}), 400
    try:
        roadmap = CareerGuidanceService().create_roadmap(
            user_id=current_user.id,
            role=payload["target_role"],
            current_skills=payload["current_skills"],
            resume_id=resume_id,
        )
    except LookupError:
        return jsonify({"error": {"code": "not_found", "message": "Resume was not found."}}), 404
    except ValueError as error:
        return jsonify({"error": {"code": "invalid_request", "message": str(error)}}), 400
    except UsageLimitExceeded as error:
        return jsonify({"error": {"code": error.code, "message": str(error)}}), 429
    except GeminiServiceError as error:
        current_app.logger.warning("Career guidance failed for user %s: %s.", current_user.id, error.code)
        return jsonify({"error": {"code": error.code, "message": _failure_message(error)}}), 503
    return jsonify(_roadmap_json(roadmap)), 201
