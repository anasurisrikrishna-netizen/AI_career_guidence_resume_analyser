from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import limiter
from app.services.gemini_service import GeminiServiceError
from app.services.interview_service import InterviewService
from app.services.token_manager import UsageLimitExceeded


interviews_bp = Blueprint("interviews", __name__)


def _session_json(session):
    return {
        "id": session.id,
        "target_role": session.target_role,
        "mode": session.mode,
        "questions": session.session_data,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


@interviews_bp.get("/interviews")
@login_required
def workspace():
    return render_template("interviews.html", sessions=InterviewService.list_sessions(current_user.id))


@interviews_bp.post("/interviews")
@login_required
@limiter.limit("10 per minute")
def create_session():
    try:
        session = InterviewService().create_session(
            user_id=current_user.id,
            role=request.form.get("target_role", ""),
            mode=request.form.get("mode", ""),
        )
    except ValueError as error:
        flash(str(error), "error")
        return workspace()
    except UsageLimitExceeded as error:
        flash(str(error), "error")
        return workspace()
    except GeminiServiceError as error:
        current_app.logger.warning("Interview session generation failed for user %s: %s.", current_user.id, error.code)
        flash("Interview practice could not be created. Please try again later.", "error")
        return workspace()
    return redirect(url_for("interviews.session_detail", session_id=session.id))


@interviews_bp.get("/interviews/<int:session_id>")
@login_required
def session_detail(session_id: int):
    try:
        session = InterviewService.get_session(current_user.id, session_id)
    except LookupError:
        abort(404)
    return render_template("interview_session.html", session=session)


@interviews_bp.post("/interviews/<int:session_id>/answers/<int:question_index>")
@login_required
@limiter.limit("20 per minute")
def submit_answer(session_id: int, question_index: int):
    try:
        session = InterviewService().evaluate_answer(
            user_id=current_user.id,
            session_id=session_id,
            question_index=question_index,
            answer=request.form.get("answer", ""),
        )
    except LookupError:
        abort(404)
    except ValueError as error:
        flash(str(error), "error")
    except UsageLimitExceeded as error:
        flash(str(error), "error")
    except GeminiServiceError as error:
        current_app.logger.warning("Interview answer evaluation failed for user %s: %s.", current_user.id, error.code)
        flash("Answer feedback could not be generated. Please try again later.", "error")
    return redirect(url_for("interviews.session_detail", session_id=session_id))


@interviews_bp.post("/api/v1/interviews")
@login_required
@limiter.limit("10 per minute")
def api_create_session():
    if not request.is_json:
        return jsonify({"error": {"code": "json_required", "message": "Send a JSON request body."}}), 415
    payload = request.get_json()
    if not isinstance(payload, dict) or set(payload) != {"target_role", "mode"}:
        return jsonify(
            {"error": {"code": "invalid_request", "message": "Provide target_role and mode."}}
        ), 400
    try:
        session = InterviewService().create_session(
            user_id=current_user.id,
            role=payload["target_role"],
            mode=payload["mode"],
        )
    except ValueError as error:
        return jsonify({"error": {"code": "invalid_request", "message": str(error)}}), 400
    except UsageLimitExceeded as error:
        return jsonify({"error": {"code": error.code, "message": str(error)}}), 429
    except GeminiServiceError as error:
        current_app.logger.warning("Interview session generation failed for user %s: %s.", current_user.id, error.code)
        return jsonify({"error": {"code": error.code, "message": "Interview practice could not be created."}}), 503
    return jsonify(_session_json(session)), 201


@interviews_bp.get("/api/v1/interviews")
@login_required
def api_list_sessions():
    return jsonify([_session_json(session) for session in InterviewService.list_sessions(current_user.id)])


@interviews_bp.get("/api/v1/interviews/<int:session_id>")
@login_required
def api_get_session(session_id: int):
    try:
        session = InterviewService.get_session(current_user.id, session_id)
    except LookupError:
        return jsonify({"error": {"code": "not_found", "message": "Interview session was not found."}}), 404
    return jsonify(_session_json(session))


@interviews_bp.post("/api/v1/interviews/<int:session_id>/answers/<int:question_index>")
@login_required
@limiter.limit("20 per minute")
def api_submit_answer(session_id: int, question_index: int):
    if not request.is_json:
        return jsonify({"error": {"code": "json_required", "message": "Send a JSON request body."}}), 415
    payload = request.get_json()
    if not isinstance(payload, dict) or set(payload) != {"answer"}:
        return jsonify({"error": {"code": "invalid_request", "message": "Provide an answer."}}), 400
    try:
        session = InterviewService().evaluate_answer(
            user_id=current_user.id,
            session_id=session_id,
            question_index=question_index,
            answer=payload["answer"],
        )
    except LookupError:
        return jsonify({"error": {"code": "not_found", "message": "Interview question was not found."}}), 404
    except ValueError as error:
        return jsonify({"error": {"code": "invalid_request", "message": str(error)}}), 400
    except UsageLimitExceeded as error:
        return jsonify({"error": {"code": error.code, "message": str(error)}}), 429
    except GeminiServiceError as error:
        current_app.logger.warning("Interview answer evaluation failed for user %s: %s.", current_user.id, error.code)
        return jsonify({"error": {"code": error.code, "message": "Answer feedback could not be generated."}}), 503
    return jsonify(_session_json(session))
