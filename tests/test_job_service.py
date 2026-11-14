import json

import pytest

from app.extensions import db
from app.models import Resume, ResumeAnalysis, User
from app.services.gemini_service import GenerationResult, GeminiResponseError
from app.services.job_service import JobService


def _match_payload():
    return {
        "compatibility_estimate": 67,
        "matched_skills": ["Python"],
        "missing_skills": ["REST APIs"],
        "recommendation": "partial_match",
        "explanation": "The resume shows Python experience, while the listing asks for API experience.",
        "caveats": ["The provider description may be an excerpt."],
    }


class FakeTokenManager:
    def __init__(self, response):
        self.response = response
        self.request = None

    def generate_text(self, **kwargs):
        self.request = kwargs
        return GenerationResult(self.response, 40, 50, 90, "test-model")


def test_job_match_uses_analyzed_resume_context_not_raw_resume_text(app):
    with app.app_context():
        user = User(email="job-match@example.com", password_hash="unused")
        db.session.add(user)
        db.session.flush()
        resume = Resume(
            user_id=user.id,
            original_filename="resume.pdf",
            file_type="pdf",
            extracted_text="PRIVATE RAW RESUME CONTENT",
        )
        db.session.add(resume)
        db.session.flush()
        analysis = ResumeAnalysis(
            user_id=user.id,
            resume_id=resume.id,
            criteria_version="test",
            feedback={
                "summary": "Python developer",
                "skills": ["Python"],
                "experience": ["Built internal tools"],
            },
        )
        db.session.add(analysis)
        db.session.commit()
        token_manager = FakeTokenManager(json.dumps(_match_payload()))

        match = JobService(token_manager=token_manager).match_resume_to_description(
            user_id=user.id,
            resume_id=resume.id,
            job_description="Seeking a Python developer who can build REST APIs.",
        )

        assert match["compatibility_estimate"] == 67.0
        assert match["missing_skills"] == ["REST APIs"]
        assert "PRIVATE RAW RESUME CONTENT" not in token_manager.request["prompt"]
        assert "REST APIs" in token_manager.request["prompt"]
        assert token_manager.request["feature"] == "job_matching"


def test_job_match_rejects_other_users_resume_and_malformed_ai_output(app):
    with app.app_context():
        owner = User(email="job-owner@example.com", password_hash="unused")
        other = User(email="job-other@example.com", password_hash="unused")
        db.session.add_all([owner, other])
        db.session.flush()
        resume = Resume(
            user_id=owner.id,
            original_filename="resume.pdf",
            file_type="pdf",
            extracted_text="Private data",
        )
        db.session.add(resume)
        db.session.flush()
        db.session.add(
            ResumeAnalysis(
                user_id=owner.id,
                resume_id=resume.id,
                criteria_version="test",
                feedback={"summary": "", "skills": [], "experience": []},
            )
        )
        db.session.commit()

        service = JobService(token_manager=FakeTokenManager("{}"))
        with pytest.raises(LookupError):
            service.match_resume_to_description(
                user_id=other.id,
                resume_id=resume.id,
                job_description="A job description",
            )
        with pytest.raises(GeminiResponseError):
            service.match_resume_to_description(
                user_id=owner.id,
                resume_id=resume.id,
                job_description="A job description",
            )
