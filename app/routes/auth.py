from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user
from flask_wtf import FlaskForm
from sqlalchemy.exc import IntegrityError
from wtforms import EmailField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, Length

from app.extensions import db, limiter
from app.models import User


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


class NormalizedEmailForm(FlaskForm):
    def validate(self, extra_validators=None):
        if self.email.data:
            self.email.data = self.email.data.strip().lower()
        return super().validate(extra_validators)


class RegisterForm(NormalizedEmailForm):
    email = EmailField("Email address", validators=[DataRequired(), Email(), Length(max=320)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=12, max=128)])
    submit = SubmitField("Create account")


class LoginForm(NormalizedEmailForm):
    email = EmailField("Email address", validators=[DataRequired(), Email(), Length(max=320)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128)])
    submit = SubmitField("Sign in")


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("pages.dashboard"))

    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User(email=email, role="user")
        user.set_password(form.password.data)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError as error:
            db.session.rollback()
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if constraint != "uq_users_email_lower" and "uq_users_email_lower" not in str(error.orig):
                raise
            form.email.errors.append("An account with that email already exists.")
        else:
            login_user(user)
            session.permanent = True
            flash("Your account is ready.", "success")
            return redirect(url_for("pages.dashboard"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("pages.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
        if user is not None and user.is_active and user.check_password(form.password.data):
            login_user(user)
            session.permanent = True
            next_url = request.args.get("next")
            if _is_safe_next_url(next_url):
                return redirect(next_url)
            return redirect(url_for("pages.dashboard"))
        flash("Email or password is incorrect.", "error")

    return render_template("auth/login.html", form=form)


@auth_bp.post("/logout")
def logout():
    if current_user.is_authenticated:
        logout_user()
    session.clear()
    return redirect(url_for("pages.dashboard"))


def _is_safe_next_url(value: str | None) -> bool:
    if not value:
        return False
    from urllib.parse import unquote, urlsplit

    try:
        parsed = urlsplit(value)
        decoded_path = unquote(parsed.path)
    except ValueError:
        return False
    return (
        not parsed.scheme
        and not parsed.netloc
        and decoded_path.startswith("/")
        and not decoded_path.startswith("//")
        and "\\" not in decoded_path
        and "\r" not in decoded_path
        and "\n" not in decoded_path
    )
