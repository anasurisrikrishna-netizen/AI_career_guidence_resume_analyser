import json
from io import BytesIO

import pytest
from docx import Document

from app.extensions import db
from app.models import Resume, ResumeAnalysis, ResumeDraft, User
from app.services.gemini_service import GenerationResult, GeminiResponseError
from app.services.resume_builder_service import ResumeBuilderService


def _generated_content():
    return {
        "professional_summary": "Python developer with experience building internal tools.",
        "experience_bullets": ["Built internal tools using Python."],
        "project_bullets": ["Created a portfolio project."],
        "keywords_to_review": ["REST APIs"],
        "change_notes": ["Kept the original project and experience facts."],
    }


class FakeTokenManager:
    def __init__(self, response):
        self.response = response
        self.request = None

    def generate_text(self, **kwargs):
        self.request = kwargs
        return GenerationResult(self.response, 50, 80, 130, "test-model")


def _setup_resume(db_session):
    user = User(email="builder@example.com", password_hash="unused")
    db.session.add(user)
    db.session.flush()
    resume = Resume(
        user_id=user.id,
        original_filename="resume.pdf",
        file_type="pdf",
        extracted_text="PRIVATE RAW RESUME DATA",
    )
    db.session.add(resume)
    db.session.flush()
    analysis = ResumeAnalysis(
        user_id=user.id,
        resume_id=resume.id,
        criteria_version="test",
        feedback={
            "contact_details": {"name": "Jordan", "email": "", "phone": "", "location": ""},
            "summary": "Python developer",
            "experience": ["Built internal tools using Python."],
            "projects": ["Created a portfolio project."],
            "skills": ["Python"],
        },
    )
    db.session.add(analysis)
    db.session.commit()
    return user, resume


def test_builder_creates_grounded_draft_and_docx_excludes_suggested_keywords(app):
    with app.app_context():
        user, resume = _setup_resume(db.session)
        token_manager = FakeTokenManager(json.dumps(_generated_content()))

        draft = ResumeBuilderService(token_manager).create_draft(
            user_id=user.id,
            resume_id=resume.id,
            job_description="Seeking REST API development experience.",
        )

        assert draft.content["contact_details"]["name"] == "Jordan"
        assert draft.content["keywords_to_review"] == ["REST APIs"]
        assert "PRIVATE RAW RESUME DATA" not in token_manager.request["prompt"]
        assert "candidate's source facts" in token_manager.request["prompt"]

        document = Document(BytesIO(ResumeBuilderService.document_bytes(draft)))
        document_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        assert "Jordan" in document_text
        assert "Python developer" in document_text
        assert "REST APIs" not in document_text


def test_builder_rejects_rewritten_experience_that_changes_source_item_count(app):
    with app.app_context():
        user, resume = _setup_resume(db.session)
        generated = _generated_content()
        generated["experience_bullets"] = []

        with pytest.raises(GeminiResponseError):
            ResumeBuilderService(FakeTokenManager(json.dumps(generated))).create_draft(
                user_id=user.id,
                resume_id=resume.id,
            )
        assert db.session.query(ResumeDraft).count() == 0


def test_builder_updates_user_edits_and_rejects_wrong_owner(app):
    with app.app_context():
        user, resume = _setup_resume(db.session)
        other = User(email="other-builder@example.com", password_hash="unused")
        db.session.add(other)
        db.session.commit()
        draft = ResumeBuilderService(FakeTokenManager(json.dumps(_generated_content()))).create_draft(
            user_id=user.id,
            resume_id=resume.id,
        )
        content = {
            "contact_details": {"name": "Jordan Edited", "email": "", "phone": "", "location": ""},
            "professional_summary": "Edited summary",
            "experience_bullets": ["Edited experience"],
            "project_bullets": ["Edited project"],
            "skills": ["Python"],
            "keywords_to_review": ["Check REST API experience"],
        }

        ResumeBuilderService().update_draft(draft=draft, user_id=user.id, content=content)
        assert draft.content["contact_details"]["name"] == "Jordan Edited"
        assert draft.content["professional_summary"] == "Edited summary"
        with pytest.raises(LookupError):
            ResumeBuilderService().update_draft(draft=draft, user_id=other.id, content=content)


def test_builder_routes_protect_other_users_drafts(client, app):
    with app.app_context():
        owner, resume = _setup_resume(db.session)
        draft = ResumeBuilderService(FakeTokenManager(json.dumps(_generated_content()))).create_draft(
            user_id=owner.id,
            resume_id=resume.id,
        )
        other = User(email="other-draft-owner@example.com", password_hash="unused")
        db.session.add(other)
        db.session.commit()
        draft_id = draft.id
        other_id = other.id

    with client.session_transaction() as session:
        session["_user_id"] = str(other_id)
        session["_fresh"] = True

    response = client.get(f"/builder/drafts/{draft_id}")
    assert response.status_code == 404

    response = client.get(f"/builder/drafts/{draft_id}/download")
    assert response.status_code == 404
