import json

import pytest

from app.extensions import db
from app.models import InterviewSession, User
from app.services.gemini_service import GenerationResult, GeminiResponseError
from app.services.interview_service import InterviewService


def _questions(category="technical"):
    return {
        "questions": [
            {
                "category": category,
                "question": f"Practice question {number}?",
                "what_it_assesses": "Reasoning and communication.",
            }
            for number in range(6)
        ]
    }


def _evaluation():
    return {
        "rating": 4,
        "strengths": ["Clear structure"],
        "improvements": ["Add a specific example."],
        "outline": "Explain context, action, and outcome without inventing results.",
        "explanation": "The answer is organized and relevant.",
    }


class FakeTokenManager:
    def __init__(self, response):
        self.response = response
        self.request = None

    def generate_text(self, **kwargs):
        self.request = kwargs
        return GenerationResult(self.response, 30, 50, 80, "test-model")


def test_interview_session_creates_questions_and_evaluates_answers(app):
    with app.app_context():
        user = User(email="interview@example.com", password_hash="unused")
        db.session.add(user)
        db.session.commit()
        token_manager = FakeTokenManager(json.dumps(_questions()))
        session = InterviewService(token_manager).create_session(
            user_id=user.id,
            role="Python Developer",
            mode="technical",
        )

        assert len(session.session_data) == 6
        assert session.session_data[0]["id"] == 0
        assert session.session_data[0]["attempts"] == []

        evaluation_manager = FakeTokenManager(json.dumps(_evaluation()))
        updated = InterviewService(evaluation_manager).evaluate_answer(
            user_id=user.id,
            session_id=session.id,
            question_index=0,
            answer="I would start by clarifying the requirements.",
        )

        assert updated.session_data[0]["attempts"][0]["evaluation"]["rating"] == 4
        assert evaluation_manager.request["feature"] == "interview_evaluation"
        assert db.session.query(InterviewSession).count() == 1


def test_interview_service_rejects_wrong_owner_and_invalid_model_data(app):
    with app.app_context():
        owner = User(email="interview-owner@example.com", password_hash="unused")
        other = User(email="interview-other@example.com", password_hash="unused")
        db.session.add_all([owner, other])
        db.session.commit()
        session = InterviewService(FakeTokenManager(json.dumps(_questions()))).create_session(
            user_id=owner.id,
            role="Python Developer",
            mode="technical",
        )

        with pytest.raises(LookupError):
            InterviewService(FakeTokenManager(json.dumps(_evaluation()))).evaluate_answer(
                user_id=other.id,
                session_id=session.id,
                question_index=0,
                answer="A practice answer",
            )
        with pytest.raises(GeminiResponseError):
            InterviewService(FakeTokenManager(json.dumps(_questions("hr")))).create_session(
                user_id=owner.id,
                role="Python Developer",
                mode="technical",
            )
        with pytest.raises(ValueError):
            InterviewService(FakeTokenManager("{}")).create_session(
                user_id=owner.id,
                role="Python Developer",
                mode=["technical"],
            )

        assert db.session.query(InterviewSession).count() == 1


def test_interview_session_page_requires_auth_and_renders(client, app):
    with app.app_context():
        user = User(email="interview-page@example.com")
        user.set_password("a-very-long-test-passphrase")
        db.session.add(user)
        db.session.commit()

    assert client.get("/interviews").status_code == 302
    response = client.post(
        "/auth/login",
        data={"email": "interview-page@example.com", "password": "a-very-long-test-passphrase"},
    )
    assert response.status_code == 302
    response = client.get("/interviews")
    assert response.status_code == 200
    assert b"Start a practice session" in response.data
