from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.data.career_roles import CAREER_ROLE_SKILLS
from app.services.resource_service import ResourceService


learning_bp = Blueprint("learning", __name__)


@learning_bp.get("/learning")
@login_required
def workspace():
    role = request.args.get("role", "Python Developer")
    if role not in CAREER_ROLE_SKILLS:
        abort(400)
    service = ResourceService()
    return render_template(
        "learning.html",
        roles=CAREER_ROLE_SKILLS,
        selected_role=role,
        resources=service.resources_for_role(role),
        progress=service.progress_for_user(current_user.id),
    )


@learning_bp.post("/learning/progress")
@login_required
def update_progress():
    try:
        service = ResourceService()
        service.update_progress(
            user_id=current_user.id,
            resource_id=int(request.form.get("resource_id", "")),
            status=request.form.get("status", ""),
            roadmap_id=int(request.form["roadmap_id"]) if request.form.get("roadmap_id") else None,
        )
    except (ValueError, LookupError) as error:
        flash(str(error), "error")
    else:
        flash("Learning progress updated.", "success")
    role = request.form.get("role", "Python Developer")
    if role not in CAREER_ROLE_SKILLS:
        flash("Choose a supported career role.", "error")
        role = "Python Developer"
    return redirect(url_for("learning.workspace", role=role))


@learning_bp.get("/api/v1/learning/resources")
@login_required
def api_resources():
    role = request.args.get("role", "")
    if role not in CAREER_ROLE_SKILLS:
        return jsonify({"error": {"code": "invalid_role", "message": "Choose a supported career role."}}), 400
    resources = ResourceService().resources_for_role(role)
    return jsonify(
        {
            "role": role,
            "resources": resources,
            "note": "Only recently verified links are clickable. Other catalog entries require verification.",
        }
    )


@learning_bp.put("/api/v1/learning/progress/<int:resource_id>")
@login_required
def api_update_progress(resource_id: int):
    if not request.is_json:
        return jsonify({"error": {"code": "json_required", "message": "Send a JSON request body."}}), 415
    payload = request.get_json()
    if not isinstance(payload, dict) or set(payload) - {"status", "roadmap_id"} or "status" not in payload:
        return jsonify({"error": {"code": "invalid_request", "message": "Provide a valid status."}}), 400
    roadmap_id = payload.get("roadmap_id")
    if roadmap_id is not None and (isinstance(roadmap_id, bool) or not isinstance(roadmap_id, int)):
        return jsonify({"error": {"code": "invalid_request", "message": "roadmap_id must be an integer."}}), 400
    try:
        progress = ResourceService().update_progress(
            user_id=current_user.id,
            resource_id=resource_id,
            status=payload["status"],
            roadmap_id=roadmap_id,
        )
    except ValueError as error:
        return jsonify({"error": {"code": "invalid_status", "message": str(error)}}), 400
    except LookupError:
        return jsonify({"error": {"code": "not_found", "message": "Resource or roadmap was not found."}}), 404
    return jsonify(
        {
            "resource_id": progress.resource_id,
            "status": progress.status,
            "updated_at": progress.updated_at.isoformat(),
        }
    )
