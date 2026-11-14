from io import BytesIO

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from app.extensions import db, limiter
from app.models import Resume, ResumeAnalysis, ResumeDraft
from app.services.gemini_service import GeminiServiceError
from app.services.resume_builder_service import ResumeBuilderService
from app.services.token_manager import UsageLimitExceeded


builder_bp = Blueprint("builder", __name__)


def _draft_for_user(draft_id: int) -> ResumeDraft:
    draft = db.session.execute(
        select(ResumeDraft).where(
            ResumeDraft.id == draft_id,
            ResumeDraft.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if draft is None:
        abort(404)
    return draft


def _builder_data():
    resumes = db.session.execute(
        select(Resume)
        .where(
            Resume.user_id == current_user.id,
            Resume.id.in_(
                select(ResumeAnalysis.resume_id).where(ResumeAnalysis.user_id == current_user.id)
            ),
        )
        .order_by(Resume.created_at.desc())
    ).scalars().all()
    drafts = db.session.execute(
        select(ResumeDraft)
        .where(ResumeDraft.user_id == current_user.id)
        .order_by(ResumeDraft.updated_at.desc())
    ).scalars().all()
    return resumes, drafts


def _render_workspace():
    resumes, drafts = _builder_data()
    return render_template("builder.html", resumes=resumes, drafts=drafts)


def _form_content():
    return {
        "contact_details": {
            key: request.form.get(f"contact_{key}", "")
            for key in ("name", "email", "phone", "location")
        },
        "professional_summary": request.form.get("professional_summary", ""),
        "experience_bullets": request.form.get("experience_bullets", "").splitlines(),
        "project_bullets": request.form.get("project_bullets", "").splitlines(),
        "skills": request.form.get("skills", "").splitlines(),
        "keywords_to_review": request.form.get("keywords_to_review", "").splitlines(),
    }


def _draft_json(draft: ResumeDraft) -> dict:
    return {
        "id": draft.id,
        "resume_id": draft.resume_id,
        "job_description": draft.job_description,
        "content": draft.content,
        "created_at": draft.created_at.isoformat(),
        "updated_at": draft.updated_at.isoformat(),
    }


@builder_bp.get("/builder")
@login_required
def workspace():
    return _render_workspace()


@builder_bp.post("/builder/drafts")
@login_required
@limiter.limit("10 per minute")
def create_draft():
    try:
        resume_id = int(request.form.get("resume_id", ""))
        draft = ResumeBuilderService().create_draft(
            user_id=current_user.id,
            resume_id=resume_id,
            job_description=request.form.get("job_description", ""),
        )
    except ValueError as error:
        flash(str(error), "error")
        return _render_workspace()
    except LookupError as error:
        flash(str(error), "error")
        return _render_workspace()
    except UsageLimitExceeded as error:
        flash(str(error), "error")
        return _render_workspace()
    except GeminiServiceError as error:
        current_app.logger.warning("Resume drafting failed for user %s: %s.", current_user.id, error.code)
        flash("The resume draft could not be generated. Please try again later.", "error")
        return _render_workspace()
    return redirect(url_for("builder.draft_detail", draft_id=draft.id))


@builder_bp.get("/builder/drafts/<int:draft_id>")
@login_required
def draft_detail(draft_id: int):
    return render_template("builder_draft.html", draft=_draft_for_user(draft_id))


@builder_bp.post("/builder/drafts/<int:draft_id>")
@login_required
def update_draft(draft_id: int):
    draft = _draft_for_user(draft_id)
    try:
        ResumeBuilderService().update_draft(
            draft=draft,
            user_id=current_user.id,
            content=_form_content(),
        )
    except ValueError as error:
        flash(str(error), "error")
    else:
        flash("Your edits have been saved. Review them before downloading.", "success")
    return redirect(url_for("builder.draft_detail", draft_id=draft_id))


@builder_bp.get("/builder/drafts/<int:draft_id>/download")
@login_required
def download_draft(draft_id: int):
    draft = _draft_for_user(draft_id)
    document = ResumeBuilderService.document_bytes(draft)
    return send_file(
        BytesIO(document),
        as_attachment=True,
        download_name=f"resume-draft-{draft.id}.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        max_age=0,
    )


@builder_bp.get("/api/v1/resume-drafts")
@login_required
def api_list_drafts():
    _, drafts = _builder_data()
    return jsonify([_draft_json(draft) for draft in drafts])


@builder_bp.post("/api/v1/resume-drafts")
@login_required
@limiter.limit("10 per minute")
def api_create_draft():
    if not request.is_json:
        return jsonify({"error": {"code": "json_required", "message": "Send a JSON request body."}}), 415
    payload = request.get_json()
    if (
        not isinstance(payload, dict)
        or set(payload) - {"resume_id", "job_description"}
        or "resume_id" not in payload
    ):
        return jsonify({"error": {"code": "invalid_request", "message": "Provide resume_id."}}), 400
    resume_id = payload["resume_id"]
    if isinstance(resume_id, bool) or not isinstance(resume_id, int):
        return jsonify({"error": {"code": "invalid_request", "message": "resume_id must be an integer."}}), 400
    try:
        draft = ResumeBuilderService().create_draft(
            user_id=current_user.id,
            resume_id=resume_id,
            job_description=payload.get("job_description", ""),
        )
    except ValueError as error:
        return jsonify({"error": {"code": "invalid_request", "message": str(error)}}), 400
    except LookupError:
        return jsonify({"error": {"code": "not_found", "message": "Resume or resume analysis was not found."}}), 404
    except UsageLimitExceeded as error:
        return jsonify({"error": {"code": error.code, "message": str(error)}}), 429
    except GeminiServiceError as error:
        current_app.logger.warning("Resume drafting failed for user %s: %s.", current_user.id, error.code)
        return jsonify(
            {"error": {"code": error.code, "message": "The resume draft could not be generated."}}
        ), 503
    return jsonify(_draft_json(draft)), 201


@builder_bp.get("/api/v1/resume-drafts/<int:draft_id>")
@login_required
def api_get_draft(draft_id: int):
    return jsonify(_draft_json(_draft_for_user(draft_id)))


@builder_bp.patch("/api/v1/resume-drafts/<int:draft_id>")
@login_required
def api_update_draft(draft_id: int):
    if not request.is_json:
        return jsonify({"error": {"code": "json_required", "message": "Send a JSON request body."}}), 415
    draft = _draft_for_user(draft_id)
    payload = request.get_json()
    if not isinstance(payload, dict) or set(payload) != {"content"}:
        return jsonify({"error": {"code": "invalid_request", "message": "Provide the editable content object."}}), 400
    try:
        updated = ResumeBuilderService().update_draft(
            draft=draft,
            user_id=current_user.id,
            content=payload["content"],
        )
    except ValueError as error:
        return jsonify({"error": {"code": "invalid_request", "message": str(error)}}), 400
    return jsonify(_draft_json(updated))
