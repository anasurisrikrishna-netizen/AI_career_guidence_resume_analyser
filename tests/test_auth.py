from app.extensions import db
from app.models import User


def test_registration_normalizes_email_and_authenticates(client, app):
    response = client.post(
        "/auth/register",
        data={"email": "  Candidate@Example.com ", "password": "a-very-long-test-passphrase"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Your career toolkit" in response.data
    with app.app_context():
        user = db.session.execute(db.select(User)).scalar_one()
        assert user.email == "candidate@example.com"
        assert user.check_password("a-very-long-test-passphrase")


def test_registration_rejects_case_insensitive_duplicate(client, app):
    with app.app_context():
        user = User(email="candidate@example.com")
        user.set_password("a-very-long-test-passphrase")
        db.session.add(user)
        db.session.commit()

    response = client.post(
        "/auth/register",
        data={"email": "CANDIDATE@example.com", "password": "another-long-test-passphrase"},
    )

    assert response.status_code == 200
    assert b"already exists" in response.data


def test_login_uses_generic_failure_message(client):
    response = client.post(
        "/auth/login",
        data={"email": "unknown@example.com", "password": "not-the-right-password"},
    )

    assert response.status_code == 200
    assert b"Email or password is incorrect." in response.data


def test_login_rejects_external_and_encoded_open_redirects(client, app):
    with app.app_context():
        user = User(email="redirect@example.com")
        user.set_password("a-very-long-test-passphrase")
        db.session.add(user)
        db.session.commit()

    for next_url in ("https://attacker.example", "//attacker.example", "/%2f%2fattacker.example", "/\\attacker.example"):
        response = client.post(
            "/auth/login",
            query_string={"next": next_url},
            data={"email": "redirect@example.com", "password": "a-very-long-test-passphrase"},
        )
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/")
        client.post("/auth/logout")
