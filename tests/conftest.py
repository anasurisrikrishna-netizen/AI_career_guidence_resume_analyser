import pytest

from app import create_app
from app.extensions import db


@pytest.fixture
def app(tmp_path):
    class TestConfig:
        TESTING = True
        SECRET_KEY = "test-only-secret-key"
        SQLALCHEMY_DATABASE_URI = "sqlite://"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        MAX_CONTENT_LENGTH = 5 * 1024 * 1024
        MAX_RESUME_TEXT_CHARS = 50000
        MAX_RESUME_PAGES = 80
        UPLOAD_FOLDER = str(tmp_path / "uploads")
        WTF_CSRF_ENABLED = False
        RATELIMIT_ENABLED = False

    application = create_app(TestConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
