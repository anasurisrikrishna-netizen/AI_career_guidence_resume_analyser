from datetime import timedelta

import pytest

from app.extensions import db
from app.models import LearningProgress, LearningResource, User, utc_now
from app.services.resource_service import ResourceService
from app.services.resource_verifier import (
    ResourceVerifier,
    UnsafeResourceURLError,
    validate_resource_url,
)


def test_resource_url_policy_blocks_unapproved_destinations():
    assert validate_resource_url("https://docs.python.org/3/tutorial/").startswith("https://")
    for url in (
        "http://docs.python.org/3/tutorial/",
        "https://docs.python.org.evil.example/",
        "https://127.0.0.1/admin",
        "https://docs.python.org:8443/",
        "https://user@docs.python.org/",
    ):
        with pytest.raises(UnsafeResourceURLError):
            validate_resource_url(url)


def test_verifier_accepts_only_approved_final_redirect(monkeypatch):
    class FakeResponse:
        def __init__(self, final_url):
            self.final_url = final_url

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return self.final_url

        def getcode(self):
            return 200

        def read(self, size):
            return b"verified"

    class FakeOpener:
        def __init__(self, final_url):
            self.final_url = final_url

        def open(self, request, timeout):
            return FakeResponse(self.final_url)

    monkeypatch.setattr(
        "app.services.resource_verifier.build_opener",
        lambda handler: FakeOpener("https://developer.mozilla.org/en-US/docs/"),
    )
    assert ResourceVerifier().verify("https://docs.python.org/3/tutorial/")

    monkeypatch.setattr(
        "app.services.resource_verifier.build_opener",
        lambda handler: FakeOpener("https://attacker.example/"),
    )
    assert not ResourceVerifier().verify("https://docs.python.org/3/tutorial/")


def test_learning_resources_hide_unverified_and_expired_links(app):
    with app.app_context():
        fresh = LearningResource(
            title="Python Tutorial",
            url="https://docs.python.org/3/tutorial/",
            provider="Python",
            resource_type="tutorial",
            access_type="free",
            level="beginner",
            topics=["python"],
            verification_status="verified",
            verified_at=utc_now(),
        )
        stale = LearningResource(
            title="Old Python page",
            url="https://docs.python.org/3/library/",
            provider="Python",
            resource_type="documentation",
            access_type="free",
            level="intermediate",
            topics=["python"],
            verification_status="verified",
            verified_at=utc_now() - timedelta(days=40),
        )
        unverified = LearningResource(
            title="Needs checking",
            url="https://docs.python.org/3/howto/",
            provider="Python",
            resource_type="tutorial",
            access_type="free",
            level="advanced",
            topics=["python"],
            verification_status="unverified",
        )
        db.session.add_all([fresh, stale, unverified])
        db.session.commit()

        resources = ResourceService().resources_for_role("Python Developer")
        by_title = {resource["title"]: resource for resource in resources}

        assert by_title["Python Tutorial"]["url"] == fresh.url
        assert by_title["Old Python page"]["url"] is None
        assert by_title["Needs checking"]["url"] is None
        assert by_title["Old Python page"]["requires_verification"]


def test_learning_progress_is_user_scoped_and_requires_verified_resource(app):
    with app.app_context():
        first = User(email="learner-one@example.com", password_hash="unused")
        second = User(email="learner-two@example.com", password_hash="unused")
        resource = LearningResource(
            title="Python Tutorial",
            url="https://docs.python.org/3/tutorial/",
            provider="Python",
            resource_type="tutorial",
            access_type="free",
            level="beginner",
            topics=["python"],
            verification_status="verified",
            verified_at=utc_now(),
        )
        db.session.add_all([first, second, resource])
        db.session.commit()

        service = ResourceService()
        progress = service.update_progress(
            user_id=first.id,
            resource_id=resource.id,
            status="completed",
        )

        assert progress.status == "completed"
        assert service.progress_for_user(first.id) == {resource.id: "completed"}
        assert service.progress_for_user(second.id) == {}
        with pytest.raises(ValueError):
            service.update_progress(user_id=second.id, resource_id=resource.id, status=["completed"])
        assert db.session.query(LearningProgress).count() == 1


def test_catalog_seeding_verifies_each_curated_url(app):
    class SelectiveVerifier:
        def __init__(self):
            self.checked = []

        def verify(self, url):
            self.checked.append(url)
            return "pytorch" not in url

    with app.app_context():
        verifier = SelectiveVerifier()
        result = ResourceService(verifier).seed_catalog()

        assert result["verified"] > 0
        assert result["failed"] == 1
        assert len(verifier.checked) == result["verified"] + result["failed"]
        statuses = {
            resource.url: resource.verification_status
            for resource in db.session.execute(db.select(LearningResource)).scalars()
        }
        assert statuses["https://docs.pytorch.org/tutorials/"] == "failed"
