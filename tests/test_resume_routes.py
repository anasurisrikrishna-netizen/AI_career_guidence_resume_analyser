from io import BytesIO

import fitz
from app.extensions import db
from app.models import Resume, User


def _resume_pdf():
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Jordan Example\nPython Developer")
    data = document.tobytes()
    document.close()
    return data


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_resume_workspace_requires_authentication(client):
    response = client.get("/resumes")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_upload_stores_file_outside_public_static_directory(client, app):
    with app.app_context():
        user = User(email="resume@example.com")
        user.set_password("a-very-long-test-passphrase")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.post(
        "/resumes/upload",
        data={"resume": (BytesIO(_resume_pdf()), "candidate.pdf")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Resume uploaded and text extracted" in response.data
    with app.app_context():
        resume = db.session.execute(db.select(Resume)).scalar_one()
        stored = app.config["UPLOAD_FOLDER"] + "\\" + resume.storage_key + ".pdf"
        assert "static" not in stored.lower()
        with open(stored, "rb") as saved_file:
            assert saved_file.read().startswith(b"%PDF-")


def test_user_cannot_access_another_users_resume_api(client, app):
    with app.app_context():
        owner = User(email="owner@example.com", password_hash="unused")
        other = User(email="other@example.com", password_hash="unused")
        db.session.add_all([owner, other])
        db.session.flush()
        resume = Resume(
            user_id=owner.id,
            original_filename="resume.pdf",
            file_type="pdf",
            extracted_text="private details",
        )
        db.session.add(resume)
        db.session.commit()
        resume_id = resume.id
        other_id = other.id

    _login(client, other_id)
    response = client.post(f"/api/v1/resumes/{resume_id}/analysis")

    assert response.status_code == 404


def test_upload_rejects_invalid_document(client, app):
    with app.app_context():
        user = User(email="invalid-upload@example.com", password_hash="unused")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.post(
        "/resumes/upload",
        data={"resume": (BytesIO(b"not a PDF"), "resume.pdf")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"not a valid PDF" in response.data
    with app.app_context():
        assert db.session.execute(db.select(Resume)).scalars().all() == []
