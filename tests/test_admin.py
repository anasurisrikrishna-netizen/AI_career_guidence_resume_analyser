from app.extensions import db
from app.models import AIUsageEvent, AIUsageSetting, User
from app.services.settings_service import SettingsService
from app.services.token_manager import TokenManager


def _login(client, email, password="a-very-long-test-passphrase"):
    return client.post("/auth/login", data={"email": email, "password": password})


def test_admin_dashboard_is_role_protected_and_reports_aggregate_usage(client, app):
    with app.app_context():
        regular_user = User(email="regular-admin-test@example.com")
        regular_user.set_password("a-very-long-test-passphrase")
        admin_user = User(email="admin-test@example.com", role="admin")
        admin_user.set_password("a-very-long-test-passphrase")
        db.session.add_all([regular_user, admin_user])
        db.session.flush()
        db.session.add(
            AIUsageEvent(
                user_id=regular_user.id,
                feature="resume_analysis",
                model="test-model",
                estimated_input_tokens=20,
                input_tokens=18,
                output_tokens=7,
                status="succeeded",
            )
        )
        db.session.commit()
    assert client.get("/admin").status_code == 302
    _login(client, "regular-admin-test@example.com")
    assert client.get("/admin").status_code == 403

    client.post("/auth/logout")
    _login(client, "admin-test@example.com")
    response = client.get("/admin")
    assert response.status_code == 200
    assert b"Platform overview" in response.data
    assert b"18" in response.data


def test_admin_updates_runtime_limits_and_invalid_changes_are_rejected(app, client):
    with app.app_context():
        admin = User(email="limits-admin@example.com", role="admin")
        admin.set_password("a-very-long-test-passphrase")
        db.session.add(admin)
        db.session.commit()

    _login(client, "limits-admin@example.com")
    response = client.post(
        "/admin/usage-settings",
        data={
            "AI_MAX_INPUT_TOKENS": "15000",
            "AI_MAX_OUTPUT_TOKENS": "1024",
            "AI_MAX_DAILY_TOKENS_PER_USER": "50000",
            "AI_RETRY_ATTEMPTS": "2",
            "AI_RETRY_BASE_SECONDS": "0.8",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"AI usage limits updated" in response.data

    with app.app_context():
        assert TokenManager._setting("AI_MAX_INPUT_TOKENS", 20000) == 15000
        assert TokenManager._setting("AI_RETRY_ATTEMPTS", 3) == 2
        settings_count = db.session.query(AIUsageSetting).count()
        assert settings_count == 5

    response = client.post(
        "/admin/usage-settings",
        data={
            "AI_MAX_INPUT_TOKENS": "0",
            "AI_MAX_OUTPUT_TOKENS": "1024",
            "AI_MAX_DAILY_TOKENS_PER_USER": "50000",
            "AI_RETRY_ATTEMPTS": "2",
            "AI_RETRY_BASE_SECONDS": "0.8",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"must be between 1 and 100000" in response.data
    with app.app_context():
        assert TokenManager._setting("AI_MAX_INPUT_TOKENS", 20000) == 15000


def test_regular_user_cannot_access_admin_api(client, app):
    with app.app_context():
        user = User(email="regular-api-admin@example.com")
        user.set_password("a-very-long-test-passphrase")
        db.session.add(user)
        db.session.commit()

    _login(client, "regular-api-admin@example.com")
    assert client.get("/api/v1/admin/metrics").status_code == 403
