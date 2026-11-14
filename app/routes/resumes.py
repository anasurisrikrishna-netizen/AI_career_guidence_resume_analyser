from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from app.extensions import db
from app.models import Resume
from app.processing.document_parser import ResumeProcessingError
from app.processing.file_validation import ResumeValidationError
from app.services.gemini_service import GeminiServiceError
from app.services.resume_service import ResumeService, ResumeStorageError
from app.services.token_manager import UsageLimitExceeded


resumes_bp = Blueprint("resumes", __name__)


def _owned_resume(resume_id: int) -> Resume:
    resume = db.session.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == current_user.id)
    ).scalar_one_or_none()
    if resume is None:
        abort(404)
    return resume


def _read_upload():
    uploaded_file = request.files.get("resume")
    if uploaded_file is None or not uploaded_file.filename:
        raise ResumeValidationError("Choose a PDF or DOCX resume to continue.")
    data = uploaded_file.stream.read(current_app.config["MAX_CONTENT_LENGTH"] + 1)
    return uploaded_file.filename, data


def _analysis_error_message(error: GeminiServiceError) -> tuple[str, str]:
    if error.code == "gemini_not_configured":
        return "Resume analysis is not configured yet. Please try again later.", "error"
    if error.code in ("gemini_rate_limited", "gemini_transient_error"):
        return "The AI service is busy right now. Please try again shortly.", "error"
    if error.code == "gemini_quota_exhausted":
        return "AI service capacity is temporarily unavailable. Please try again later.", "error"
    if error.code == "ai_usage_limit_exceeded":
        return "This request exceeds your configured AI usage limit.", "error"
    return "Resume analysis could not be completed. Please try again later.", "error"


@resumes_bp.get("/resumes")
@login_required
def workspace():
    resumes = db.session.execute(
        select(Resume)
        .where(Resume.user_id == current_user.id)
        .order_by(Resume.created_at.desc())
    ).scalars().all()
    return render_template("resumes.html", resumes=resumes)


@resumes_bp.post("/resumes/upload")
@login_required
def upload():
    try:
        filename, data = _read_upload()
        resume = ResumeService().upload(user_id=current_user.id, filename=filename, data=data)
    except ResumeValidationError as error:
        flash(str(error), "error")
    except ResumeProcessingError as error:
        flash(str(error), "error")
    except ResumeStorageError:
        current_app.logger.exception("Resume storage failed for user %s.", current_user.id)
        flash("The resume could not be saved securely. Please try again later.", "error")
    else:
        flash("Resume uploaded and text extracted. You can now request an analysis.", "success")
        current_app.logger.info("Resume %s uploaded for user %s.", resume.id, current_user.id)
    return redirect(url_for("resumes.workspace"))


@resumes_bp.post("/resumes/<int:resume_id>/analyze")
@login_required
def analyze(resume_id: int):
    resume = _owned_resume(resume_id)
    try:
        analysis = ResumeService().analyze(user_id=current_user.id, resume=resume)
    except UsageLimitExceeded as error:
        flash(str(error), "error")
    except GeminiServiceError as error:
        current_app.logger.warning(
            "Resume analysis failed for user %s: %s.",
            current_user.id,
            error.code,
        )
        message, category = _analysis_error_message(error)
        flash(message, category)
    else:
        flash("Resume analysis is ready. Review the feedback and verify it against your experience.", "success")
        current_app.logger.info("Resume analysis %s created for user %s.", analysis.id, current_user.id)
    return redirect(url_for("resumes.workspace"))


@resumes_bp.get("/api/v1/resumes")
@login_required
def api_list():
    resumes = db.session.execute(
        select(Resume)
        .where(Resume.user_id == current_user.id)
        .order_by(Resume.created_at.desc())
    ).scalars().all()
    return jsonify(
        [
            {
                "id": resume.id,
                "filename": resume.original_filename,
                "file_type": resume.file_type,
                "created_at": resume.created_at.isoformat(),
            }
            for resume in resumes
        ]
    )


@resumes_bp.post("/api/v1/resumes")
@login_required
def api_upload():
    try:
        filename, data = _read_upload()
        resume = ResumeService().upload(user_id=current_user.id, filename=filename, data=data)
    except ResumeValidationError as error:
        return jsonify({"error": {"code": "invalid_resume", "message": str(error)}}), 400
    except ResumeProcessingError as error:
        return jsonify({"error": {"code": "resume_processing_failed", "message": str(error)}}), 422
    except ResumeStorageError:
        current_app.logger.exception("Resume storage failed for user %s.", current_user.id)
        return jsonify({"error": {"code": "resume_storage_failed", "message": "Resume could not be stored."}}), 500
    return jsonify(
        {
            "id": resume.id,
            "filename": resume.original_filename,
            "file_type": resume.file_type,
            "created_at": resume.created_at.isoformat(),
        }
    ), 201


@resumes_bp.post("/api/v1/resumes/<int:resume_id>/analysis")
@login_required
def api_analyze(resume_id: int):
    resume = _owned_resume(resume_id)
    try:
        analysis = ResumeService().analyze(user_id=current_user.id, resume=resume)
    except UsageLimitExceeded as error:
        return jsonify({"error": {"code": error.code, "message": str(error)}}), 429
    except GeminiServiceError as error:
        current_app.logger.warning(
            "Resume analysis failed for user %s: %s.",
            current_user.id,
            error.code,
        )
        message, _ = _analysis_error_message(error)
        return jsonify({"error": {"code": error.code, "message": message}}), 503
    return jsonify(
        {
            "id": analysis.id,
            "resume_id": resume.id,
            "criteria_version": analysis.criteria_version,
            "feedback": analysis.feedback,
            "created_at": analysis.created_at.isoformat(),
        }
    ), 201
