import json

import pytest

from app.extensions import db
from app.models import CareerRoadmap, Resume, ResumeAnalysis, User
from app.services.career_service import CareerGuidanceService
from app.services.gemini_service import GenerationResult, GeminiResponseError


def _roadmap_response():
    return {
        "learning_phases": [
            {
                "title": f"Phase {number}",
                "level": "beginner" if number == 1 else "intermediate",
                "topics": ["Python fundamentals"],
                "project": "Build a small tool and write tests.",
                "outcome": "Explain the approach and tradeoffs.",
            }
            for number in range(1, 4)
        ],
        "related_roles": ["Data Analyst"],
    }


class FakeTokenManager:
    def __init__(self, response):
        self.response = response
        self.request = None

    def generate_text(self, **kwargs):
        self.request = kwargs
        return GenerationResult(self.response, 30, 50, 80, "test-model")


def test_roadmap_compares_skills_and_persists_owner_data(app):
    with app.app_context():
        user = User(email="career@example.com", password_hash="unused")
        db.session.add(user)
        db.session.commit()
        token_manager = FakeTokenManager(json.dumps(_roadmap_response()))

        roadmap = CareerGuidanceService(token_manager).create_roadmap(
            user_id=user.id,
            role="Python Developer",
            current_skills=[" python ", "JS", "Git"],
        )

        assert roadmap.current_skills == ["python", "JS", "Git"]
        assert "Object-oriented programming" in roadmap.skill_gaps
        assert "Python" not in roadmap.skill_gaps
        assert roadmap.related_roles == ["Data Analyst"]
        assert token_manager.request["feature"] == "career_guidance"
        assert db.session.query(CareerRoadmap).filter_by(user_id=user.id).count() == 1


def test_career_guidance_rejects_unknown_role_and_invalid_model_shape(app):
    with app.app_context():
        token_manager = FakeTokenManager('{"learning_phases": [], "related_roles": []}')
        service = CareerGuidanceService(token_manager)

        with pytest.raises(ValueError):
            service.create_roadmap(user_id=1, role="Unknown Role", current_skills=[])
        with pytest.raises(GeminiResponseError):
            service.create_roadmap(user_id=1, role="Python Developer", current_skills=[])

        assert db.session.query(CareerRoadmap).count() == 0


def test_roadmap_can_use_skills_from_only_the_users_own_analysis(app):
    with app.app_context():
        owner = User(email="resume-skills@example.com", password_hash="unused")
        other = User(email="other-resume-skills@example.com", password_hash="unused")
        db.session.add_all([owner, other])
        db.session.flush()
        resume = Resume(
            user_id=owner.id,
            original_filename="resume.pdf",
            file_type="pdf",
            extracted_text="private resume text",
        )
        db.session.add(resume)
        db.session.flush()
        analysis = ResumeAnalysis(
            user_id=owner.id,
            resume_id=resume.id,
            criteria_version="test",
            feedback={"skills": ["Python", "SQL"]},
        )
        db.session.add(analysis)
        db.session.commit()

        service = CareerGuidanceService(FakeTokenManager(json.dumps(_roadmap_response())))
        with pytest.raises(LookupError):
            service.create_roadmap(
                user_id=other.id,
                role="Python Developer",
                current_skills=[],
                resume_id=resume.id,
            )
        roadmap = service.create_roadmap(
            user_id=owner.id,
            role="Python Developer",
            current_skills=["Git"],
            resume_id=resume.id,
        )

        assert roadmap.current_skills == ["Git", "Python", "SQL"]


def test_career_form_pages_require_auth_and_render(app, client):
    with app.app_context():
        user = User(email="career-page@example.com", password_hash="unused")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True

    assert client.get("/careers").status_code == 200
    assert client.get("/learning?role=Python%20Developer").status_code == 200
