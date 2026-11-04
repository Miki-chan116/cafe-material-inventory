import pytest
from werkzeug.security import generate_password_hash

from app import Base, PASSWORD_METHOD, User, create_app


@pytest.fixture
def app(tmp_path):
    database = tmp_path / "test.sqlite3"
    app = create_app({"TESTING": True, "SECRET_KEY": "test-only-secret", "DATABASE_URL": f"sqlite:///{database}"})
    engine = app.extensions["inventory_engine"]
    Base.metadata.create_all(engine)
    with app.extensions["inventory_sessionmaker"].begin() as db:
        db.add_all([
            User(username="admin", password_hash=generate_password_hash("admin-test-password", method=PASSWORD_METHOD), role="admin"),
            User(username="staff", password_hash=generate_password_hash("staff-test-password", method=PASSWORD_METHOD), role="staff"),
        ])
    yield app
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client):
    client.get("/login")
    with client.session_transaction() as sess:
        return sess["csrf_token"]


def login(client, username="admin", password="admin-test-password"):
    response = client.post("/login", data={"csrf_token": csrf(client), "username": username, "password": password})
    assert response.status_code == 302
    return response
