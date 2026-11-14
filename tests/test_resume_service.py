import json

import pytest

from app.extensions import db
from app.models import Resume, ResumeAnalysis, User
from app.services.gemini_service import GenerationResult, GeminiResponseError
from app.services.resume_service import ResumeService


def _valid_analysis():
    return {
        "contact_details": {
            "name": "Jordan Example",
            "email": None,
            "phone": None,
            "location": None,
        },
        "summary": "Python developer with project experience.",
        "skills": ["Python"],
        "education": [],
        "experience": [],
        "projects": ["Portfolio app"],
        "strengths": ["Relevant technical project"],
        "weaknesses": [],
        "missing_keywords": ["Testing"],
        "structure_feedback": ["Use consistent section headings."],
        "improvements": ["Add measurable outcomes where accurate."],
        "ats_criteria": ["Section clarity", "Relevant terminology"],
        "ats_estimate": 72,
    }


class FakeTokenManager:
    def __init__(self, response):
        self.response = response
        self.request = None

    def generate_text(self, **kwargs):
        self.request = kwargs
        return GenerationResult(self.response, 50, 75, 125, "test-model")


def test_analysis_persists_validated_feedback_and_uses_resume_once(app):
    with app.app_context():
        user = User(email="analysis@example.com", password_hash="unused")
        db.session.add(user)
        db.session.flush()
        resume = Resume(
            user_id=user.id,
            original_filename="resume.pdf",
            file_type="pdf",
            extracted_text="Jordan Example\nPython Developer",
        )
        db.session.add(resume)
        db.session.commit()

        token_manager = FakeTokenManager(json.dumps(_valid_analysis()))
        analysis = ResumeService(token_manager).analyze(user_id=user.id, resume=resume)

        assert analysis.ats_estimate == 72
        assert analysis.feedback["skills"] == ["Python"]
        assert "Jordan Example" in token_manager.request["prompt"]
        assert token_manager.request["feature"] == "resume_analysis"
        assert db.session.query(ResumeAnalysis).count() == 1


def test_analysis_rejects_malformed_provider_data_without_saving(app):
    with app.app_context():
        user = User(email="bad-analysis@example.com", password_hash="unused")
        db.session.add(user)
        db.session.flush()
        resume = Resume(
            user_id=user.id,
            original_filename="resume.pdf",
            file_type="pdf",
            extracted_text="Candidate text",
        )
        db.session.add(resume)
        db.session.commit()

        token_manager = FakeTokenManager('{"ats_estimate": 140}')
        with pytest.raises(GeminiResponseError):
            ResumeService(token_manager).analyze(user_id=user.id, resume=resume)

        assert db.session.query(ResumeAnalysis).count() == 0


def test_analysis_service_rejects_wrong_owner(app):
    with app.app_context():
        owner = User(email="resume-owner@example.com", password_hash="unused")
        other = User(email="other-owner@example.com", password_hash="unused")
        db.session.add_all([owner, other])
        db.session.flush()
        resume = Resume(
            user_id=owner.id,
            original_filename="resume.pdf",
            file_type="pdf",
            extracted_text="Candidate text",
        )
        db.session.add(resume)
        db.session.commit()

        with pytest.raises(PermissionError):
            ResumeService(FakeTokenManager("{}")).analyze(user_id=other.id, resume=resume)
