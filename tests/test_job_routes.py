from app.extensions import db
from app.models import User


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_job_search_page_does_not_show_sample_results_without_provider_credentials(client, app):
    with app.app_context():
        user = User(email="job-search@example.com", password_hash="unused")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/jobs?what=Python%20Developer")

    assert response.status_code == 200
    assert b"Job search is not configured" in response.data
    assert b"Example Employer" not in response.data


def test_job_search_api_requires_authentication(client):
    response = client.get("/api/v1/jobs?what=Python")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]
