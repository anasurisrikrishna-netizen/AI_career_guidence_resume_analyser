from flask import Flask, request

from app.config import Config
from app.extensions import csrf, db, limiter, login_manager, migrate


def create_app(config_object=Config):
    import click

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    if not app.config.get("SECRET_KEY") or app.config["SECRET_KEY"] == "replace-with-a-long-random-secret":
        raise RuntimeError("Set a unique SECRET_KEY in the environment before starting the application.")
    app.config.setdefault("UPLOAD_FOLDER", app.instance_path + "/uploads")

    import os

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from app.models import User
    from app.routes.auth import auth_bp
    from app.routes.admin import admin_bp
    from app.routes.builder import builder_bp
    from app.routes.careers import careers_bp
    from app.routes.learning import learning_bp
    from app.routes.pages import pages_bp
    from app.routes.jobs import jobs_bp
    from app.routes.interviews import interviews_bp
    from app.routes.resumes import resumes_bp

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        try:
            user_id = int(user_id)
        except ValueError:
            return None
        return db.session.get(User, user_id)

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(builder_bp)
    app.register_blueprint(careers_bp)
    app.register_blueprint(learning_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(interviews_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(resumes_bp)

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.cli.command("seed-learning-resources")
    def seed_learning_resources():
        from app.services.resource_service import ResourceService

        result = ResourceService().seed_catalog()
        click.echo(
            f"Learning resource verification complete: "
            f"{result['verified']} verified, {result['failed']} require verification."
        )

    @app.cli.command("make-admin")
    @click.argument("email")
    def make_admin(email):
        from sqlalchemy import select

        from app.models import User

        user = db.session.execute(
            select(User).where(User.email == email.strip().lower())
        ).scalar_one_or_none()
        if user is None:
            raise click.ClickException("Create the user account first, then promote it with this command.")
        user.role = "admin"
        db.session.commit()
        click.echo("User role updated to administrator.")

    return app
