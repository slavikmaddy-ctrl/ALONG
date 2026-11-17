# -*- coding: utf-8 -*-
"""Регрессионные тесты ALONG по требованиям P0/P1."""

from datetime import date, timedelta

import pytest

from conftest import ADMIN, USER, get_csrf, login

TOMORROW = (date.today() + timedelta(days=1)).isoformat()
PUBLIC_PAGES = ("/", "/trips", "/schedule", "/route", "/login", "/register")
SECURITY_HEADERS = (
    "Content-Security-Policy",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Permissions-Policy",
)


def test_public_pages_open(client):
    for path in PUBLIC_PAGES:
        response = client.get(path)
        assert response.status_code == 200, f"{path} -> {response.status_code}"


def test_security_headers_everywhere(client):
    for path in ("/", "/trips", "/no-such-page"):
        response = client.get(path)
        for header in SECURITY_HEADERS:
            assert response.headers.get(header), f"Нет {header} на {path}"
    assert "frame-ancestors 'none'" in client.get("/").headers["Content-Security-Policy"]
    assert client.get("/").headers["X-Frame-Options"] == "DENY"
    assert client.get("/").headers["X-Content-Type-Options"] == "nosniff"


def test_static_deduplication(client):
    assert client.head("/static/videos/hero-bg.mp4").status_code == 200
    assert client.get("/static/logo.png").status_code == 200
    assert client.get("/static/media/road.mp4").status_code == 404
    assert client.get("/static/images/logo.png").status_code == 404


def test_register_login_logout(app):
    client = app.test_client()
    token = get_csrf(client, "/register")
    email = "newbie@example.org"
    response = client.post(
        "/register",
        data={
            "name": "Новый Пассажир",
            "email": email,
            "city": "Москва",
            "account_kind": "passenger",
            "password": "Passw0rd-New",
            "csrf": token,
        },
    )
    assert response.status_code == 302
    verify_page = client.get("/verify")
    assert verify_page.status_code == 200
    verify_html = verify_page.get_data(as_text=True)
    assert "Демо-режим почты" in verify_html
    assert "/verify/" in verify_html

    login(client, email, "Passw0rd-New")
    me_page = client.get("/me")
    assert me_page.status_code == 200
    assert "Новый Пассажир" in me_page.get_data(as_text=True)

    logout_token = get_csrf(client, "/me")
    assert client.post("/logout", data={"csrf": logout_token}).status_code == 302
    after = client.get("/me")
    assert after.status_code == 302
    assert "/login" in after.headers["Location"]


def test_admin_requires_login_and_role(app, admin_client):
    anonymous = app.test_client().get("/admin")
    assert anonymous.status_code == 302
    assert "/login" in anonymous.headers["Location"]
    assert "next=" in anonymous.headers["Location"]

    regular = app.test_client()
    login(regular, *USER)
    assert regular.get("/admin").status_code == 403

    assert admin_client.get("/admin").status_code == 200


def test_post_without_csrf_is_rejected(app, admin_client):
    anonymous = app.test_client()
    assert anonymous.post("/login", data={"email": "x@y.z", "password": "12345678"}).status_code == 400
    assert admin_client.post("/admin/schedules/new", data={}).status_code == 400
    assert admin_client.post("/admin/reviews/1/delete", data={}).status_code == 400


def test_sqli_probe_does_not_break_queries(client, admin_client, db):
    probes = (
        "/trips?seats=1%27%20OR%20%271%27%3D%271",
        "/trips?from=%27%3B%20DROP%20TABLE%20users%3B--",
        "/trips?price=0%20UNION%20SELECT%201,2,3--",
    )
    for path in probes:
        response = client.get(path)
        assert response.status_code == 200, path
    assert client.get("/admin/reviews?q=%27%20OR%201%3D1--").status_code == 302
    assert admin_client.get("/admin/reviews?q=%27%20OR%201%3D1--").status_code == 200
    assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 7


def test_xss_complaint_is_escaped(user_client, admin_client):
    payload = '<script>alert("xss")</script>'
    token = get_csrf(user_client, "/trips/1")
    response = user_client.post(
        "/trips/1",
        data={"action": "complaint", "body": payload, "csrf": token},
    )
    assert response.status_code == 302
    html = admin_client.get("/admin/complaints").get_data(as_text=True)
    assert "&lt;script&gt;alert" in html
    assert payload not in html


def test_trip_creation_requires_approved_driver(user_client, db):
    token = get_csrf(user_client, "/trips/new")
    data = {
        "from": "Москва",
        "to": "Минск",
        "date": TOMORROW,
        "time": "09:30",
        "price": "1000",
        "seats": "2",
        "pickup": "Тверская",
        "dropoff": "",
        "luggage": "рюкзак",
        "comment": "",
        "csrf": token,
    }
    before = db.execute(
        "SELECT COUNT(*) FROM trips WHERE origin = 'Москва' AND destination = 'Минск'"
    ).fetchone()[0]
    response = user_client.post("/trips/new", data=data)
    assert response.status_code == 200
    assert "статус водителя" in response.get_data(as_text=True)
    assert db.execute(
        "SELECT COUNT(*) FROM trips WHERE origin = 'Москва' AND destination = 'Минск'"
    ).fetchone()[0] == before

    db.execute("UPDATE users SET driver_status = 'approved' WHERE email = ?", (USER[0],))
    db.commit()
    token = get_csrf(user_client, "/trips/new")
    data["csrf"] = token
    response = user_client.post("/trips/new", data=data)
    assert response.status_code == 302
    assert db.execute(
        "SELECT COUNT(*) FROM trips WHERE driver_id = (SELECT id FROM users WHERE email = ?)"
        " AND origin = 'Москва' AND destination = 'Минск'",
        (USER[0],),
    ).fetchone()[0] == 1
    created = db.execute(
        "SELECT t.* FROM trips t JOIN users u ON u.id = t.driver_id "
        "WHERE u.email = ? ORDER BY t.id DESC LIMIT 1",
        (USER[0],),
    ).fetchone()
    assert created is not None
    assert created["price"] == 1000
    assert created["seats_total"] == 2


def test_booking_and_confirmation_flow(app, user_client, driver_client, db):
    token = get_csrf(user_client, "/trips/1")
    assert user_client.post(
        "/trips/1", data={"action": "request", "seats": "1", "csrf": token}
    ).status_code == 302
    booking = db.execute(
        "SELECT b.* FROM bookings b JOIN users u ON u.id = b.passenger_id "
        "WHERE b.trip_id = 1 AND u.email = ? ORDER BY b.id DESC LIMIT 1",
        (USER[0],),
    ).fetchone()
    assert booking is not None
    assert booking["status"] == "clarify"
    booking_id = booking["id"]

    token = get_csrf(user_client, "/trips/1")
    assert user_client.post(
        "/trips/1",
        data={
            "action": "clarify",
            "phone": "+79001234567",
            "meeting": "Казань, Кольцо",
            "luggage": "рюкзак",
            "comment": "",
            "csrf": token,
        },
    ).status_code == 302

    token = get_csrf(driver_client, "/trips/1")
    assert driver_client.post(
        "/trips/1",
        data={"action": "agree", "booking_id": str(booking_id), "csrf": token},
    ).status_code == 302
    assert db.execute("SELECT status FROM bookings WHERE id = ?", (booking_id,)).fetchone()[0] == "plan"

    token = get_csrf(user_client, "/trips/1")
    assert user_client.post(
        "/trips/1", data={"action": "plan_ok", "csrf": token}
    ).status_code == 302
    token = get_csrf(driver_client, "/trips/1")
    assert driver_client.post(
        "/trips/1",
        data={"action": "plan_ok", "booking_id": str(booking_id), "csrf": token},
    ).status_code == 302

    token = get_csrf(user_client, "/trips/1")
    assert user_client.post(
        "/trips/1", data={"action": "confirm", "csrf": token}
    ).status_code == 302
    assert db.execute("SELECT status FROM bookings WHERE id = ?", (booking_id,)).fetchone()[0] == "confirmed"
    assert db.execute("SELECT seats_taken FROM trips WHERE id = 1").fetchone()[0] == 2


def test_schedule_crud(admin_client, db):
    token = get_csrf(admin_client, "/admin/schedules/new")
    response = admin_client.post(
        "/admin/schedules/new",
        data={
            "mode": "bus",
            "from": "Москва",
            "to": "Минск",
            "date": TOMORROW,
            "time": "10:15",
            "title": "Тестовый рейс",
            "via": "",
            "leg2_time": "",
            "csrf": token,
        },
    )
    assert response.status_code == 302
    item = db.execute(
        "SELECT * FROM schedules WHERE title = 'Тестовый рейс' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert item is not None
    assert item["depart_at"] == f"{TOMORROW}T10:15"

    token = get_csrf(admin_client, f"/admin/schedules/{item['id']}")
    response = admin_client.post(
        f"/admin/schedules/{item['id']}",
        data={
            "mode": "train",
            "from": "Москва",
            "to": "Минск",
            "date": TOMORROW,
            "time": "11:45",
            "title": "Тестовый рейс (правка)",
            "via": "",
            "leg2_time": "",
            "csrf": token,
        },
    )
    assert response.status_code == 302
    updated = db.execute("SELECT * FROM schedules WHERE id = ?", (item["id"],)).fetchone()
    assert updated["mode"] == "train"
    assert updated["title"] == "Тестовый рейс (правка)"

    token = get_csrf(admin_client, "/admin/schedules")
    response = admin_client.post(
        f"/admin/schedules/{item['id']}/delete", data={"csrf": token}
    )
    assert response.status_code == 302
    assert db.execute("SELECT id FROM schedules WHERE id = ?", (item["id"],)).fetchone() is None
    logged = db.execute(
        "SELECT action, entity FROM admin_log WHERE entity = 'schedule' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert logged["action"] == "delete"


def test_schedule_validation(admin_client, db):
    token = get_csrf(admin_client, "/admin/schedules/new")
    before = db.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]
    response = admin_client.post(
        "/admin/schedules/new",
        data={
            "mode": "ship",
            "from": "Атлантида",
            "to": "Минск",
            "date": "не дата",
            "time": "99:99",
            "title": "",
            "csrf": token,
        },
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Выберите вид транспорта" in html
    assert db.execute("SELECT COUNT(*) FROM schedules").fetchone()[0] == before


def test_review_moderation(admin_client, db):
    review = db.execute("SELECT * FROM reviews ORDER BY id LIMIT 1").fetchone()
    target_id = review["target_id"]
    text = review["text"]
    assert admin_client.get("/admin/reviews").status_code == 200

    token = get_csrf(admin_client, "/admin/reviews")
    response = admin_client.post(
        f"/admin/reviews/{review['id']}/delete", data={"csrf": token}
    )
    assert response.status_code == 302
    assert db.execute("SELECT id FROM reviews WHERE id = ?", (review["id"],)).fetchone() is None

    profile = admin_client.get(f"/u/{target_id}")
    assert profile.status_code == 200
    assert text not in profile.get_data(as_text=True)
    logged = db.execute(
        "SELECT action, entity FROM admin_log WHERE entity = 'review' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert logged["action"] == "delete"


@pytest.mark.parametrize(
    "path",
    ["/admin/schedules", "/admin/schedules/new", "/admin/reviews", "/admin/log"],
)
def test_admin_sections_permissions(app, path, admin_client):
    assert admin_client.get(path).status_code == 200
    regular = app.test_client()
    login(regular, *USER)
    assert regular.get(path).status_code == 403
    anonymous = app.test_client().get(path)
    assert anonymous.status_code == 302
    assert "/login" in anonymous.headers["Location"]


def test_reviews_single_source_of_truth(db):
    columns = [row["name"] for row in db.execute("PRAGMA table_info(reviews)").fetchall()]
    assert columns == [
        "id", "trip_id", "author_id", "target_id", "rating", "text", "created_at",
    ]
    assert "driver_id" not in columns
    assert "body" not in columns


def test_foreign_key_indexes(db):
    names = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    for expected in (
        "idx_trips_driver", "idx_trips_status", "idx_bookings_passenger",
        "idx_bookings_trip", "idx_messages_sender", "idx_messages_receiver",
        "idx_messages_trip", "idx_reviews_target", "idx_complaints_status",
        "idx_sessions_user", "idx_admin_log_created",
    ):
        assert expected in names


def test_login_attempts_cleanup(app, db):
    db.execute(
        "INSERT INTO login_attempts (email, created_at) VALUES (?, ?)",
        ("old@example.org", 1.0),
    )
    db.commit()
    client = app.test_client()
    login(client, *ADMIN)
    assert db.execute(
        "SELECT COUNT(*) FROM login_attempts WHERE email = ?", ("old@example.org",)
    ).fetchone()[0] == 0


def test_old_demo_password_no_longer_seeded(client):
    response = client.post(
        "/login",
        data={"email": ADMIN[0], "password": "AlongAdmin1", "csrf": get_csrf(client, "/login")},
    )
    assert response.status_code == 200
    assert "Неверная почта или пароль" in response.get_data(as_text=True)
