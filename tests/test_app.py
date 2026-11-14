from app.extensions import db
from app.models import Resume, User


def test_dashboard_renders(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"Your career toolkit" in response.data


def test_password_is_hashed_and_verifiable(app):
    with app.app_context():
        user = User(email="candidate@example.com")
        user.set_password("correct horse battery staple")

        assert user.password_hash != "correct horse battery staple"
        assert user.check_password("correct horse battery staple")
        assert not user.check_password("incorrect password")


def test_resume_records_are_scoped_by_owner(app):
    with app.app_context():
        first_user = User(email="first@example.com", password_hash="unused")
        second_user = User(email="second@example.com", password_hash="unused")
        db.session.add_all([first_user, second_user])
        db.session.flush()
        db.session.add_all(
            [
                Resume(
                    user_id=first_user.id,
                    original_filename="resume.pdf",
                    file_type="pdf",
                    extracted_text="private resume text",
                ),
                Resume(
                    user_id=second_user.id,
                    original_filename="resume.docx",
                    file_type="docx",
                    extracted_text="another private resume",
                ),
            ]
        )
        db.session.commit()

        visible = db.session.query(Resume).filter_by(user_id=first_user.id).all()

        assert len(visible) == 1
        assert visible[0].extracted_text == "private resume text"
