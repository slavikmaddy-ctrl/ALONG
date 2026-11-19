# -*- coding: utf-8 -*-
"""Регрессионные тесты ALONG по требованиям P0/P1."""

from datetime import date, timedelta
import re

import pytest
import server

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

def test_password_reset_flow(app):
    client = app.test_client()
    token = get_csrf(client, "/password/forgot")
    response = client.post(
        "/password/forgot", data={"email": USER[0], "csrf": token}
    )
    assert response.status_code == 302
    page = client.get("/password/forgot?sent=1").get_data(as_text=True)
    match = re.search(r'(/password/reset/[^"?]+)', page)
    assert match, "В демо-режиме ссылка сброса должна быть на странице"
    reset_path = match.group(1)

    token = get_csrf(client, reset_path)
    response = client.post(
        reset_path,
        data={"password": "NewPassword99", "repeat": "NewPassword99", "csrf": token},
    )
    assert response.status_code == 302
    login(client, USER[0], "NewPassword99")
    assert client.get("/me").status_code == 200


def test_password_reset_link_is_single_use(app, db):
    client = app.test_client()
    token = get_csrf(client, "/password/forgot")
    client.post("/password/forgot", data={"email": USER[0], "csrf": token})
    page = client.get("/password/forgot?sent=1").get_data(as_text=True)
    reset_path = re.search(r'(/password/reset/[^"?]+)', page).group(1)
    token = get_csrf(client, reset_path)
    client.post(
        reset_path,
        data={"password": "AnotherPass77", "repeat": "AnotherPass77", "csrf": token},
    )
    again = client.get(reset_path)
    assert again.status_code == 400


def test_session_cookie_secure_in_prod(app, monkeypatch):
    monkeypatch.setattr(server, "SECURE_COOKIES", True)
    client = app.test_client()
    token = get_csrf(client, "/login")
    response = client.post(
        "/login", data={"email": ADMIN[0], "password": ADMIN[1], "csrf": token}
    )
    assert response.status_code == 302
    assert "Secure" in (response.headers.get("Set-Cookie") or "")


def test_verify_link_does_not_create_session(app, db):
    raw = "verify-token-for-test"
    db.execute(
        "UPDATE users SET verify_token = ?, verified = 0 WHERE email = ?",
        (server.hash_token(raw), USER[0]),
    )
    db.commit()
    client = app.test_client()
    response = client.get("/verify/" + raw)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert client.get("/me").status_code == 302


def test_forbidden_page_is_branded(user_client):
    response = user_client.get("/admin")
    assert response.status_code == 403
    html = response.get_data(as_text=True)
    assert "Недостаточно прав" in html
    assert "ALONG" in html


def test_csv_export_escapes_formulas(admin_client, db):
    db.execute(
        "UPDATE users SET name = '=2+2' WHERE id = (SELECT driver_id FROM trips WHERE id = 1)"
    )
    db.commit()
    payload = admin_client.get("/admin/trips/export").get_data(as_text=True)
    assert "'=2+2" in payload


def test_complaint_cannot_be_closed_twice(admin_client, user_client, db):
    db.execute(
        "INSERT INTO complaints (author_id, trip_id, body, status, staff_note, created_at) "
        "VALUES (2, 1, 'Проверка', 'done', 'первая пометка', 1.0)"
    )
    db.commit()
    complaint_id = db.execute("SELECT MAX(id) FROM complaints").fetchone()[0]
    token = get_csrf(admin_client, "/admin/complaints")
    response = admin_client.post(
        "/admin/complaints/%d" % complaint_id,
        data={"staff_note": "вторая пометка", "csrf": token},
    )
    assert response.status_code == 302
    note = db.execute(
        "SELECT staff_note FROM complaints WHERE id = ?", (complaint_id,)
    ).fetchone()[0]
    assert note == "первая пометка"

def test_robots_and_sitemap(client):
    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    body = robots.get_data(as_text=True)
    assert "Disallow: /admin" in body
    assert "Sitemap:" in body

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    xml = sitemap.get_data(as_text=True)
    assert "<urlset" in xml
    assert "/trips" in xml


def test_meta_tags_present(client):
    html = client.get("/").get_data(as_text=True)
    assert 'name="description"' in html
    assert 'property="og:title"' in html
    assert 'rel="canonical"' in html


def _request_booking(client, trip_id=1):
    token = get_csrf(client, "/trips/%d" % trip_id)
    response = client.post(
        "/trips/%d" % trip_id,
        data={"action": "request", "seats": "1", "csrf": token},
    )
    assert response.status_code == 302


def test_status_labels_are_human_readable(user_client, db):
    _request_booking(user_client)
    html = user_client.get("/trips/1").get_data(as_text=True)
    assert "уточнение" in html
    assert ">clarify<" not in html
    me_html = user_client.get("/me").get_data(as_text=True)
    assert "уточнение" in me_html
    assert ">clarify<" not in me_html


def test_driver_notification_counts(app, user_client, driver_client, db):
    _request_booking(user_client)
    db.execute(
        "INSERT INTO messages (sender_id, receiver_id, trip_id, text, is_read, created_at) "
        "VALUES (2, 3, NULL, 'Здравствуйте', 0, '2026-01-01 10:00:00')"
    )
    db.commit()
    html = driver_client.get("/me").get_data(as_text=True)
    assert "Новые заявки на ваши поездки: 1" in html
    assert "Непрочитанные сообщения: 1" in html


def test_driver_sees_only_matching_offers(app, driver_client, db):
    db.execute("UPDATE users SET driver_status = 'approved' WHERE id = 3")
    db.execute(
        "INSERT INTO custom_offers (passenger_id, origin, destination, offer_price, created_at) "
        "VALUES (2, 'Казань', 'Алматы', 3000, '2026-01-01 10:00:00')"
    )
    db.execute(
        "INSERT INTO custom_offers (passenger_id, origin, destination, offer_price, created_at) "
        "VALUES (2, 'Москва', 'Минск', 2500, '2026-01-01 10:00:00')"
    )
    db.commit()
    html = driver_client.get("/me").get_data(as_text=True)
    assert "Казань → Алматы" in html
    assert "Москва → Минск" not in html


def test_offer_cannot_repeat_within_day(user_client, db):
    token = get_csrf(user_client, "/trips")
    data = {
        "origin": "Москва",
        "destination": "Минск",
        "offer_price": "1500",
        "csrf": token,
    }
    assert user_client.post("/offers", data=data).status_code == 302
    token = get_csrf(user_client, "/trips")
    data["csrf"] = token
    user_client.post("/offers", data=data)
    total = db.execute(
        "SELECT COUNT(*) FROM custom_offers WHERE origin = 'Москва' AND destination = 'Минск'"
    ).fetchone()[0]
    assert total == 1


def test_complaint_daily_limit(user_client, db):
    server._RATE.clear()
    for _ in range(3):
        token = get_csrf(user_client, "/trips/1")
        response = user_client.post(
            "/trips/1",
            data={"action": "complaint", "body": "Нарушение", "csrf": token},
        )
        assert response.status_code == 302
    token = get_csrf(user_client, "/trips/1")
    page = user_client.post(
        "/trips/1",
        data={"action": "complaint", "body": "Ещё одна", "csrf": token},
    )
    assert page.status_code == 200
    assert "Не больше трёх жалоб в сутки" in page.get_data(as_text=True)
    server._RATE.clear()


def test_meeting_length_is_checked_on_server(user_client):
    _request_booking(user_client)
    token = get_csrf(user_client, "/trips/1")
    page = user_client.post(
        "/trips/1",
        data={
            "action": "clarify",
            "phone": "+79001234567",
            "meeting": "м" * 201,
            "csrf": token,
        },
    )
    assert page.status_code == 200
    assert "Не больше 200 символов" in page.get_data(as_text=True)


def test_admin_complaint_hides_trip(app, admin_client, db):
    db.execute(
        "INSERT INTO complaints (author_id, trip_id, body, status, staff_note, created_at) "
        "VALUES (2, 1, 'Проверка маршрута', 'open', '', 1.0)"
    )
    db.commit()
    complaint_id = db.execute("SELECT MAX(id) FROM complaints").fetchone()[0]
    token = get_csrf(admin_client, "/admin/complaints")
    response = admin_client.post(
        "/admin/complaints/%d" % complaint_id,
        data={
            "staff_note": "Маршрут не совпадает",
            "trip_action": "hide",
            "trip_reason": "Маршрут не совпадает",
            "csrf": token,
        },
    )
    assert response.status_code == 302
    assert db.execute("SELECT status FROM trips WHERE id = 1").fetchone()[0] == "hidden"
    assert db.execute(
        "SELECT status FROM complaints WHERE id = ?", (complaint_id,)
    ).fetchone()[0] == "done"
    actions = [row[0] for row in db.execute("SELECT action FROM admin_log").fetchall()]
    assert "hide" in actions
    assert "complaint-close" in actions


def test_complaint_status_filter(admin_client):
    html = admin_client.get("/admin/complaints?status=done").get_data(as_text=True)
    assert "Описание поправили" in html
    assert "В описании маршрут короче" not in html

def test_trips_page_has_route_inputs(client):
    html = client.get("/trips").get_data(as_text=True)
    assert 'id="filter-from"' in html
    assert 'id="filter-to"' in html
    assert "Город или адрес" in html
    assert 'id="filter-from" type="hidden"' not in html


def test_unknown_city_message_names_the_city(client):
    html = client.get("/trips?from=Тверь&to=Минск").get_data(as_text=True)
    assert "Города «Тверь» нет в списке" in html


def test_trip_card_date_is_human_readable(client):
    html = client.get("/trips").get_data(as_text=True)
    spans = re.findall(r'class="when"><strong>[^<]+</strong><span>([^<]+)</span>', html)
    assert spans
    assert all(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in spans)


def test_footer_copyright_is_not_duplicated(client):
    html = client.get("/").get_data(as_text=True)
    assert html.count("Все права защищены") == 1


def test_404_page_has_distinct_actions(client):
    html = client.get("/nope").get_data(as_text=True)
    assert html.count(">На главную<") == 1
    assert ">Смотреть поездки<" in html

def test_admin_trip_status_filter_is_readable(admin_client):
    html = admin_client.get("/admin/trips").get_data(as_text=True)
    assert ">открыта</option>" in html
    assert ">скрыта</option>" in html
    assert ">отменена</option>" in html
    assert ">open</option>" not in html


def test_admin_user_selects_are_readable(admin_client):
    html = admin_client.get("/admin/users").get_data(as_text=True)
    assert ">пользователь</option>" in html
    assert ">администратор</option>" in html
    assert ">на проверке</option>" in html
    assert ">user</option>" not in html
    assert ">review</option>" not in html


def test_csv_export_has_single_charset(admin_client):
    response = admin_client.get("/admin/trips/export")
    assert response.headers["Content-Type"] == "text/csv; charset=utf-8"


def test_admin_log_shows_human_readable_action(admin_client, db):
    db.execute(
        "INSERT INTO complaints (author_id, trip_id, body, status, staff_note, created_at) "
        "VALUES (2, 1, 'Проверка журнала', 'open', '', 1.0)"
    )
    db.commit()
    complaint_id = db.execute("SELECT MAX(id) FROM complaints").fetchone()[0]
    token = get_csrf(admin_client, "/admin/complaints")
    admin_client.post(
        "/admin/complaints/%d" % complaint_id,
        data={"staff_note": "Проверили", "csrf": token},
    )
    html = admin_client.get("/admin/log").get_data(as_text=True)
    assert "закрытие жалобы" in html
    assert "жалоба #" in html
    assert "complaint-close" not in html


def test_route_page_has_form_without_initial_error(client):
    html = client.get("/route").get_data(as_text=True)
    assert 'class="route-form"' in html
    assert 'name="from"' in html
    assert 'name="to"' in html
    assert "Выберите адрес из списка" not in html


def test_route_page_shows_distance_after_submit(client):
    html = client.get("/route?from=Москва&to=Минск").get_data(as_text=True)
    assert "Москва → Минск" in html
    assert "км в пути" in html
    assert "route-map" in html


def test_route_page_reports_unknown_city_after_submit(client):
    html = client.get("/route?from=Москва&to=Атлантида").get_data(as_text=True)
    assert "Выберите адрес из списка" in html


def test_schedule_selects_nearest_day(admin_client, db):
    token = get_csrf(admin_client, "/admin/schedules/new")
    response = admin_client.post(
        "/admin/schedules/new",
        data={
            "mode": "bus",
            "from": "Казань",
            "to": "Москва",
            "date": TOMORROW,
            "time": "09:40",
            "title": "Ближайший рейс",
            "via": "",
            "leg2_time": "",
            "csrf": token,
        },
    )
    assert response.status_code == 302
    html = admin_client.get("/schedule?mode=bus").get_data(as_text=True)
    assert f'value="{TOMORROW}"' in html
    assert "Ближайший рейс" in html


def test_past_trip_closes_booking_for_guest(client, db):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    db.execute("UPDATE trips SET depart_at = ? WHERE id = 1", (yesterday + "T09:00",))
    db.commit()
    html = client.get("/trips/1").get_data(as_text=True)
    assert "Поездка завершена" in html
    assert "Заявка сейчас не создаётся" not in html


def test_guest_does_not_see_passenger_names(client, db):
    db.execute(
        "INSERT INTO bookings (trip_id, passenger_id, seats, status, created_at) "
        "VALUES (3, 2, 1, 'confirmed', 1.0)"
    )
    db.commit()
    html = client.get("/trips/3").get_data(as_text=True)
    assert "Имена пассажиров видны водителю и подтверждённым попутчикам." in html
    assert "Дина Каримова" not in html


def test_driver_sees_passenger_names(driver_client, db):
    trip = db.execute("SELECT id, driver_id FROM trips ORDER BY id LIMIT 1").fetchone()
    db.execute(
        "INSERT INTO bookings (trip_id, passenger_id, seats, status, created_at) "
        "VALUES (?, 2, 1, 'confirmed', 1.0)",
        (trip["id"],),
    )
    db.commit()
    html = driver_client.get("/trips/%d" % trip["id"]).get_data(as_text=True)
    assert "Дина Каримова" in html


def test_support_page_saves_ticket(client, db):
    html = client.get("/support").get_data(as_text=True)
    assert "Написать в поддержку" in html
    token = get_csrf(client, "/support")
    response = client.post(
        "/support",
        data={
            "name": "Гость",
            "email": "guest@example.com",
            "topic": "Бронирование",
            "body": "Не приходит подтверждение брони.",
            "csrf": token,
        },
    )
    assert response.status_code == 302
    row = db.execute(
        "SELECT * FROM support_tickets WHERE email = 'guest@example.com'"
    ).fetchone()
    assert row is not None
    assert row["status"] == "open"
    assert row["topic"] == "Бронирование"


def test_support_page_validates_empty_message(client):
    token = get_csrf(client, "/support")
    html = client.post(
        "/support",
        data={"name": "", "email": "no-mail", "topic": "", "body": "коротко", "csrf": token},
    ).get_data(as_text=True)
    assert "Как к вам обращаться?" in html
    assert "Выберите тему обращения" in html
    assert "Опишите вопрос подробнее" in html


def test_admin_closes_support_ticket(admin_client, db):
    db.execute(
        "INSERT INTO support_tickets (user_id, name, email, topic, body, status, staff_note, created_at) "
        "VALUES (NULL, 'Гость', 'guest@example.com', 'Поездка', 'Проверка обращения', 'open', '', 1.0)"
    )
    db.commit()
    ticket_id = db.execute("SELECT MAX(id) FROM support_tickets").fetchone()[0]
    token = get_csrf(admin_client, "/admin/support")
    response = admin_client.post(
        "/admin/support/%d" % ticket_id,
        data={"action": "close", "staff_note": "Ответили на почту", "csrf": token},
    )
    assert response.status_code == 302
    row = db.execute(
        "SELECT * FROM support_tickets WHERE id = ?", (ticket_id,)
    ).fetchone()
    assert row["status"] == "done"
    assert row["staff_note"] == "Ответили на почту"
    html = admin_client.get("/admin/log").get_data(as_text=True)
    assert "закрытие обращения" in html


def test_account_deletion_requires_password(user_client, db):
    token = get_csrf(user_client, "/me")
    user_client.post(
        "/me/delete",
        data={"password": "wrong-password", "confirm": "УДАЛИТЬ", "csrf": token},
    )
    row = db.execute("SELECT email FROM users WHERE email = ?", (USER[0],)).fetchone()
    assert row is not None


def test_account_deletion_strips_personal_data(user_client, db):
    user = db.execute("SELECT * FROM users WHERE email = ?", (USER[0],)).fetchone()
    token = get_csrf(user_client, "/me")
    response = user_client.post(
        "/me/delete",
        data={"password": USER[1], "confirm": "УДАЛИТЬ", "csrf": token},
    )
    assert response.status_code == 302
    row = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    assert row["name"] == "Удалённый пользователь"
    assert row["email"] == "deleted-%d@along.invalid" % user["id"]
    assert row["status"] == "blocked"
    assert row["phone"] is None
    assert row["about"] is None
    assert row["photo"] == "deleted.svg"
    assert db.execute(
        "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user["id"],)
    ).fetchone()[0] == 0
    assert user_client.get("/me").status_code == 302
