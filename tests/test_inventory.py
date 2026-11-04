from sqlalchemy import select

from app import Ingredient, Movement
from conftest import csrf, login


def add_ingredient(client, name="コーヒー豆", minimum="2.5"):
    return client.post("/ingredients/new", data={"csrf_token": csrf(client), "name": name, "unit": "g", "minimum": minimum})


def move(client, ingredient_id, direction, quantity, reason="テスト"):
    return client.post(f"/ingredients/{ingredient_id}/move", data={"csrf_token": csrf(client),
                       "direction": direction, "quantity": quantity, "reason": reason})


def test_inventory_history_and_warning(app, client):
    login(client)
    assert add_ingredient(client).status_code == 302
    with app.extensions["inventory_sessionmaker"]() as db:
        ingredient = db.scalar(select(Ingredient).where(Ingredient.name == "コーヒー豆"))
        ingredient_id = ingredient.id
        assert ingredient.stock_milli == 0
    assert "不足" in client.get("/").get_data(as_text=True)
    assert move(client, ingredient_id, "in", "3.125").status_code == 302
    assert move(client, ingredient_id, "out", "0.625").status_code == 302
    with app.extensions["inventory_sessionmaker"]() as db:
        ingredient = db.get(Ingredient, ingredient_id)
        assert ingredient.stock_milli == 2500
        assert [m.delta_milli for m in db.scalars(select(Movement).order_by(Movement.id)).all()] == [3125, -625]
    history = client.get(f"/ingredients/{ingredient_id}/history").get_data(as_text=True)
    assert "コーヒー豆" in history and "テスト" in history


def test_invalid_and_insufficient_stock_are_atomic(app, client):
    login(client)
    add_ingredient(client)
    with app.extensions["inventory_sessionmaker"]() as db:
        ingredient_id = db.scalar(select(Ingredient.id))
    assert move(client, ingredient_id, "out", "1").status_code == 200
    assert move(client, ingredient_id, "in", "0").status_code == 200
    assert move(client, ingredient_id, "in", "1.0001").status_code == 200
    assert move(client, ingredient_id, "in", "NaN").status_code == 200
    with app.extensions["inventory_sessionmaker"]() as db:
        assert db.get(Ingredient, ingredient_id).stock_milli == 0
        assert db.scalars(select(Movement)).all() == []


def test_duplicate_and_html_escaped(client):
    login(client)
    assert add_ingredient(client).status_code == 302
    assert add_ingredient(client).status_code == 200
    assert add_ingredient(client, name="<script>alert(1)</script>").status_code == 302
    page = client.get("/").get_data(as_text=True)
    assert "&lt;script&gt;" in page
    assert "<script>" not in page


def test_admin_edit_and_staff_movement(app, client):
    login(client)
    add_ingredient(client, minimum="1")
    with app.extensions["inventory_sessionmaker"]() as db:
        ingredient_id = db.scalar(select(Ingredient.id))
    response = client.post(f"/ingredients/{ingredient_id}/edit", data={
        "csrf_token": csrf(client), "name": "深煎り豆", "minimum": "2"})
    assert response.status_code == 302
    client.post("/logout", data={"csrf_token": csrf(client)})
    login(client, "staff", "staff-test-password")
    assert move(client, ingredient_id, "in", "3", "納品").status_code == 302
    assert "深煎り豆" in client.get("/").get_data(as_text=True)
    assert "不足" not in client.get("/").get_data(as_text=True)
    with app.extensions["inventory_sessionmaker"]() as db:
        ingredient = db.get(Ingredient, ingredient_id)
        assert (ingredient.name, ingredient.minimum_milli, ingredient.stock_milli) == ("深煎り豆", 2000, 3000)
