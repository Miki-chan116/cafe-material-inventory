from conftest import csrf, login


def test_authentication_and_roles(client):
    assert client.get("/").status_code == 302
    assert client.post("/login", data={"csrf_token": csrf(client), "username": "admin", "password": "wrong"}).status_code == 200
    login(client, "staff", "staff-test-password")
    assert client.get("/").status_code == 200
    assert client.get("/ingredients/new").status_code == 403
    assert client.post("/ingredients/new", data={"csrf_token": csrf(client), "name": "豆", "unit": "g", "minimum": "0"}).status_code == 403
    assert client.get("/users/new").status_code == 403
    assert client.post("/logout", data={"csrf_token": csrf(client)}).status_code == 302
    assert client.get("/").status_code == 302


def test_csrf_rejects_missing_or_wrong_token(client):
    assert client.post("/login", data={"username": "admin", "password": "admin-test-password"}).status_code == 400
    login(client)
    assert client.post("/logout", data={"csrf_token": "wrong"}).status_code == 400
    assert client.get("/").status_code == 200


def test_admin_creates_staff_with_password_hash(app, client):
    login(client)
    response = client.post("/users/new", data={"csrf_token": csrf(client), "username": "newstaff",
                                               "password": "a-long-test-password", "role": "staff"})
    assert response.status_code == 302
    from sqlalchemy import select
    from app import User
    with app.extensions["inventory_sessionmaker"]() as db:
        user = db.scalar(select(User).where(User.username == "newstaff"))
        assert user.password_hash != "a-long-test-password"
        assert user.role == "staff"
