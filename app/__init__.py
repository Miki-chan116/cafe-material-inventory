"""Cafe material inventory application."""

import os
import secrets
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path

import click
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, create_engine, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    __table_args__ = (CheckConstraint("role IN ('admin', 'staff')"),)


class Ingredient(Base):
    __tablename__ = "ingredients"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    unit: Mapped[str] = mapped_column(String(10), nullable=False)
    stock_milli: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    minimum_milli: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    movements: Mapped[list["Movement"]] = relationship(back_populates="ingredient")
    __table_args__ = (
        CheckConstraint("unit IN ('g', 'ml', '個')"),
        CheckConstraint("stock_milli >= 0"),
        CheckConstraint("minimum_milli >= 0"),
    )


class Movement(Base):
    __tablename__ = "movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    delta_milli: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    ingredient: Mapped[Ingredient] = relationship(back_populates="movements")
    actor: Mapped[User] = relationship()
    __table_args__ = (CheckConstraint("delta_milli != 0"),)


MAX_MILLI = 999_999_999_000
PASSWORD_METHOD = "pbkdf2:sha256:600000"


def parse_quantity(raw, *, positive=False):
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        raise ValueError("数量は数値で入力してください。") from None
    if not value.is_finite() or value.as_tuple().exponent < -3:
        raise ValueError("数量は小数第3位まで入力してください。")
    milli = int(value * 1000)
    if milli < 0 or (positive and milli == 0) or milli > MAX_MILLI:
        raise ValueError("数量が許容範囲外です。")
    return milli


def format_quantity(milli):
    return f"{Decimal(milli) / 1000:,.3f}".rstrip("0").rstrip(".")


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    prod = os.environ.get("APP_ENV") == "production"
    database_url = os.environ.get("DATABASE_URL") or f"sqlite:///{Path(app.instance_path) / 'inventory.sqlite3'}"
    app.config.update(
        SECRET_KEY=os.environ.get("APP_SECRET_KEY"),
        DATABASE_URL=database_url,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=prod,
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"] or (prod and len(app.config["SECRET_KEY"]) < 32):
        raise RuntimeError("APP_SECRET_KEY が必要です。")
    if prod and not app.config["DATABASE_URL"].startswith("postgresql+psycopg://"):
        raise RuntimeError("本番環境には専用の PostgreSQL 接続先が必要です。")
    if app.config.get("TESTING") and "production" in app.config["DATABASE_URL"].lower():
        raise RuntimeError("テストで本番らしい DB 接続先を使用できません。")

    os.makedirs(app.instance_path, exist_ok=True)
    engine = create_engine(app.config["DATABASE_URL"], pool_pre_ping=True)
    app.extensions["inventory_engine"] = engine
    app.extensions["inventory_sessionmaker"] = sessionmaker(bind=engine, expire_on_commit=False)
    app.jinja_env.filters["quantity"] = format_quantity

    @app.cli.command("init-db")
    def init_db():
        Base.metadata.create_all(engine)
        click.echo("DB schema initialized")

    @app.cli.command("create-admin")
    @click.argument("username")
    def create_admin(username):
        username = username.strip()
        if not 1 <= len(username) <= 80:
            raise click.ClickException("ユーザー名の長さが不正です。")
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
        if len(password) < 12:
            raise click.ClickException("パスワードは12文字以上にしてください。")
        with app.extensions["inventory_sessionmaker"].begin() as db:
            if db.scalar(select(User).where(User.username == username)):
                raise click.ClickException("既存のユーザー名です。")
            db.add(User(username=username, password_hash=generate_password_hash(password, method=PASSWORD_METHOD), role="admin"))
        click.echo("Admin created")

    @app.before_request
    def open_session():
        g.db = app.extensions["inventory_sessionmaker"]()
        g.user = g.db.get(User, session["user_id"]) if session.get("user_id") else None
        if request.method == "POST":
            token = request.form.get("csrf_token", "")
            if not secrets.compare_digest(token, session.get("csrf_token", "__missing__")):
                abort(400, "CSRF token が不正です。")

    @app.teardown_request
    def close_session(_exc):
        if "db" in g:
            g.db.close()

    @app.context_processor
    def template_context():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return {"current_user": g.get("user"), "csrf_token": session["csrf_token"]}

    def login_required(role=None):
        def decorator(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if not g.user:
                    return redirect(url_for("login"))
                if role and g.user.role != role:
                    abort(403)
                return fn(*args, **kwargs)
            return wrapped
        return decorator

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = g.db.scalar(select(User).where(User.username == username))
            if user and check_password_hash(user.password_hash, password):
                session.clear()
                session["user_id"] = user.id
                session["csrf_token"] = secrets.token_urlsafe(32)
                return redirect(url_for("index"))
            flash("ユーザー名またはパスワードが違います。")
        return render_template("login.html")

    @app.post("/logout")
    @login_required()
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @login_required()
    def index():
        ingredients = g.db.scalars(select(Ingredient).order_by(Ingredient.name)).all()
        return render_template("index.html", ingredients=ingredients)

    @app.route("/ingredients/new", methods=["GET", "POST"])
    @login_required("admin")
    def ingredient_new():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            unit = request.form.get("unit", "")
            try:
                minimum = parse_quantity(request.form.get("minimum", ""))
                if not 1 <= len(name) <= 120 or unit not in ("g", "ml", "個"):
                    raise ValueError("材料名または単位が不正です。")
                if g.db.scalar(select(Ingredient).where(Ingredient.name == name)):
                    raise ValueError("同じ名前の材料があります。")
                g.db.add(Ingredient(name=name, unit=unit, minimum_milli=minimum, stock_milli=0))
                g.db.commit()
                return redirect(url_for("index"))
            except ValueError as exc:
                g.db.rollback()
                flash(str(exc))
        return render_template("ingredient.html", ingredient=None)

    @app.route("/ingredients/<int:ingredient_id>/edit", methods=["GET", "POST"])
    @login_required("admin")
    def ingredient_edit(ingredient_id):
        ingredient = g.db.get(Ingredient, ingredient_id)
        if ingredient is None:
            abort(404)
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            try:
                minimum = parse_quantity(request.form.get("minimum", ""))
                if not 1 <= len(name) <= 120:
                    raise ValueError("材料名が不正です。")
                duplicate = g.db.scalar(select(Ingredient).where(Ingredient.name == name, Ingredient.id != ingredient_id))
                if duplicate:
                    raise ValueError("同じ名前の材料があります。")
                ingredient.name = name
                ingredient.minimum_milli = minimum
                g.db.commit()
                return redirect(url_for("index"))
            except ValueError as exc:
                g.db.rollback()
                flash(str(exc))
        return render_template("ingredient.html", ingredient=ingredient)

    @app.route("/ingredients/<int:ingredient_id>/move", methods=["GET", "POST"])
    @login_required()
    def move(ingredient_id):
        ingredient = g.db.get(Ingredient, ingredient_id)
        if ingredient is None:
            abort(404)
        if request.method == "POST":
            try:
                quantity = parse_quantity(request.form.get("quantity", ""), positive=True)
                direction = request.form.get("direction", "")
                reason = request.form.get("reason", "").strip()
                if direction not in ("in", "out") or not 1 <= len(reason) <= 240:
                    raise ValueError("入出庫区分または理由が不正です。")
                delta = quantity if direction == "in" else -quantity
                if delta > 0:
                    stmt = update(Ingredient).where(Ingredient.id == ingredient_id, Ingredient.stock_milli <= MAX_MILLI - delta)
                else:
                    stmt = update(Ingredient).where(Ingredient.id == ingredient_id, Ingredient.stock_milli >= -delta)
                result = g.db.execute(stmt.values(stock_milli=Ingredient.stock_milli + delta))
                if result.rowcount != 1:
                    raise ValueError("在庫不足、または上限を超えています。")
                from datetime import datetime, timezone
                g.db.add(Movement(ingredient_id=ingredient_id, actor_id=g.user.id, delta_milli=delta,
                                  reason=reason, created_at=datetime.now(timezone.utc).isoformat()))
                g.db.commit()
                return redirect(url_for("history", ingredient_id=ingredient_id))
            except ValueError as exc:
                g.db.rollback()
                flash(str(exc))
        return render_template("move.html", ingredient=ingredient)

    @app.get("/ingredients/<int:ingredient_id>/history")
    @login_required()
    def history(ingredient_id):
        ingredient = g.db.get(Ingredient, ingredient_id)
        if ingredient is None:
            abort(404)
        movements = g.db.scalars(select(Movement).where(Movement.ingredient_id == ingredient_id)
                                 .order_by(Movement.id.desc()).limit(200)).all()
        return render_template("history.html", ingredient=ingredient, movements=movements)

    @app.route("/users/new", methods=["GET", "POST"])
    @login_required("admin")
    def user_new():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            role = request.form.get("role", "")
            if not 1 <= len(username) <= 80 or len(password) < 12 or role not in ("admin", "staff"):
                flash("ユーザー名、12文字以上のパスワード、権限を確認してください。")
            elif g.db.scalar(select(User).where(User.username == username)):
                flash("既存のユーザー名です。")
            else:
                g.db.add(User(username=username, password_hash=generate_password_hash(password, method=PASSWORD_METHOD), role=role))
                g.db.commit()
                flash("ユーザーを登録しました。")
                return redirect(url_for("index"))
        return render_template("user.html")

    return app
