from flask import Blueprint, current_app, flash, jsonify, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from app.extensions import db, limiter
from app.models import Resume, ResumeAnalysis
from app.services.gemini_service import GeminiServiceError
from app.services.job_provider import (
    JobProviderConfigurationError,
    JobProviderError,
    JobProviderRateLimitError,
    JobProviderUnavailableError,
)
from app.services.job_service import JobService
from app.services.token_manager import UsageLimitExceeded


jobs_bp = Blueprint("jobs", __name__)


def _analyzed_resumes():
    return db.session.execute(
        select(Resume)
        .where(
            Resume.user_id == current_user.id,
            Resume.id.in_(
                select(ResumeAnalysis.resume_id).where(ResumeAnalysis.user_id == current_user.id)
            ),
        )
        .order_by(Resume.created_at.desc())
    ).scalars().all()


def _search_results(query, location, page):
    results = JobService().search(query, location, page=page)
    return [
        {
            "provider_id": listing.provider_id,
            "title": listing.title,
            "company": listing.company,
            "location": listing.location,
            "description": listing.description,
            "apply_url": listing.apply_url,
            "posted_at": listing.posted_at,
            "salary_min": listing.salary_min,
            "salary_max": listing.salary_max,
            "contract_type": listing.contract_type,
        }
        for listing in results.listings
    ], results.total_count


def _provider_error(error: JobProviderError) -> tuple[str, str, int]:
    if isinstance(error, JobProviderConfigurationError):
        return "Job search is not configured. Add valid Adzuna credentials to the server environment.", error.code, 503
    if isinstance(error, JobProviderRateLimitError):
        return "The job source is receiving too many requests. Please retry shortly.", error.code, 429
    if isinstance(error, JobProviderUnavailableError):
        return "The job source is temporarily unavailable. Please try again later.", error.code, 503
    return "The job search could not be completed. Please try again later.", error.code, 502


def _resume_listing_data():
    return _analyzed_resumes()


@jobs_bp.get("/jobs")
@login_required
@limiter.limit("30 per minute")
def workspace():
    query = request.args.get("what", "").strip()
    location = request.args.get("where", "").strip()
    try:
        page = int(request.args.get("page", "1"))
        results, total_count = _search_results(query, location, page) if query else ([], 0)
        error_message = None
    except ValueError as error:
        results, total_count = [], 0
        error_message = str(error)
    except JobProviderError as error:
        current_app.logger.warning("Job search provider failure: %s.", error.code)
        error_message, _, _ = _provider_error(error)
        results, total_count = [], 0
    return render_template(
        "jobs.html",
        query=query,
        location=location,
        results=results,
        total_count=total_count,
        page=request.args.get("page", "1"),
        resumes=_resume_listing_data(),
        error_message=error_message,
    )


@jobs_bp.get("/api/v1/jobs")
@login_required
@limiter.limit("30 per minute")
def api_search():
    query = request.args.get("what", "")
    location = request.args.get("where", "")
    try:
        page = int(request.args.get("page", "1"))
        results, total_count = _search_results(query, location, page)
    except ValueError as error:
        return jsonify({"error": {"code": "invalid_request", "message": str(error)}}), 400
    except JobProviderError as error:
        current_app.logger.warning("Job search provider failure: %s.", error.code)
        message, code, status = _provider_error(error)
        return jsonify({"error": {"code": code, "message": message}}), status
    return jsonify(
        {
            "provider": "Adzuna",
            "results": results,
            "total_count": total_count,
            "page": page,
            "cached": False,
        }
    )


@jobs_bp.post("/jobs/match")
@login_required
@limiter.limit("10 per minute")
def match_page():
    try:
        resume_id = int(request.form.get("resume_id", ""))
        match = JobService().match_resume_to_description(
            user_id=current_user.id,
            resume_id=resume_id,
            job_description=request.form.get("job_description", ""),
        )
    except ValueError as error:
        flash(str(error), "error")
        return render_template("jobs.html", query="", location="", results=[], total_count=0, resumes=_resume_listing_data(), error_message=None)
    except LookupError as error:
        flash(str(error), "error")
        return render_template("jobs.html", query="", location="", results=[], total_count=0, resumes=_resume_listing_data(), error_message=None)
    except UsageLimitExceeded as error:
        flash(str(error), "error")
        return render_template("jobs.html", query="", location="", results=[], total_count=0, resumes=_resume_listing_data(), error_message=None)
    except GeminiServiceError as error:
        current_app.logger.warning("Job compatibility analysis failed for user %s: %s.", current_user.id, error.code)
        flash("Job compatibility analysis could not be completed. Please try again later.", "error")
        return render_template("jobs.html", query="", location="", results=[], total_count=0, resumes=_resume_listing_data(), error_message=None)
    return render_template("job_match.html", match=match, dashboard_url=url_for("pages.dashboard"))


@jobs_bp.post("/api/v1/jobs/matches")
@login_required
@limiter.limit("10 per minute")
def api_match():
    if not request.is_json:
        return jsonify({"error": {"code": "json_required", "message": "Send a JSON request body."}}), 415
    payload = request.get_json()
    if not isinstance(payload, dict) or set(payload) != {"resume_id", "job_description"}:
        return jsonify(
            {"error": {"code": "invalid_request", "message": "Provide resume_id and job_description."}}
        ), 400
    resume_id = payload["resume_id"]
    if isinstance(resume_id, bool) or not isinstance(resume_id, int):
        return jsonify({"error": {"code": "invalid_request", "message": "resume_id must be an integer."}}), 400
    try:
        match = JobService().match_resume_to_description(
            user_id=current_user.id,
            resume_id=resume_id,
            job_description=payload["job_description"],
        )
    except ValueError as error:
        return jsonify({"error": {"code": "invalid_request", "message": str(error)}}), 400
    except LookupError:
        return jsonify({"error": {"code": "not_found", "message": "Resume or resume analysis was not found."}}), 404
    except UsageLimitExceeded as error:
        return jsonify({"error": {"code": error.code, "message": str(error)}}), 429
    except GeminiServiceError as error:
        current_app.logger.warning("Job compatibility analysis failed for user %s: %s.", current_user.id, error.code)
        return jsonify(
            {"error": {"code": error.code, "message": "Job compatibility analysis could not be completed."}}
        ), 503
    return jsonify(match)
