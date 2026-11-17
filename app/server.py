# -*- coding: utf-8 -*-
"""Локальное приложение ALONG: один процесс Flask и SQLite."""

import csv
import hashlib
import hmac
import io
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from functools import wraps
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import (
    Flask, Response, abort, flash, g, redirect, render_template, request,
    send_from_directory, session, url_for,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from mail import send_mail, smtp_configured

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.environ.get("ALONG_DB") or os.path.join(ROOT, "along.db"))
IMAGES = os.path.normpath(os.path.join(ROOT, "static", "images"))
SECRET_PATH = os.path.join(ROOT, ".secret")
SESSION_SECONDS = 60 * 60 * 8
HERE = "Моё местоположение"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REVIEW_TEXT_LIMIT = 1000
STATUS_LABELS = {
    "clarify": "уточнение",
    "plan": "план",
    "confirmed": "подтверждено",
    "rejected": "отказ",
    "cancelled": "отменено",
    "open": "открыта",
    "hidden": "скрыта",
    "done": "разобрана",
    "active": "активен",
    "blocked": "заблокирован",
    "pending": "на проверке",
    "approved": "подтверждён",
    "pending_resignation": "ждёт отказа",
    "passenger": "пассажир",
    "driver": "водитель",
    "admin": "администратор",
    "user": "пользователь",
}
FIELD_LIMITS = {
    "meeting": 200,
    "luggage": 200,
    "comment": 500,
    "reason": 500,
    "staff_note": 500,
    "complaint": 2000,
}
ENV_NAME = (os.environ.get("ALONG_ENV") or "dev").strip().lower()
BASE_URL = (os.environ.get("ALONG_BASE_URL") or "").strip().rstrip("/")
SECURE_COOKIES = os.environ.get("ALONG_SECURE_COOKIES") == "1" or ENV_NAME == "prod"
PER_PAGE = 20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("along")

CITIES = [
    {"name": "Москва", "lat": 55.7558, "lon": 37.6173, "country": "Россия"},
    {"name": "Санкт-Петербург", "lat": 59.9343, "lon": 30.3351, "country": "Россия"},
    {"name": "Казань", "lat": 55.7887, "lon": 49.1221, "country": "Россия"},
    {"name": "Новосибирск", "lat": 55.0084, "lon": 82.9357, "country": "Россия"},
    {"name": "Екатеринбург", "lat": 56.8389, "lon": 60.6057, "country": "Россия"},
    {"name": "Нижний Новгород", "lat": 56.2965, "lon": 43.9361, "country": "Россия"},
    {"name": "Самара", "lat": 53.1959, "lon": 50.1002, "country": "Россия"},
    {"name": "Уфа", "lat": 54.7388, "lon": 55.9721, "country": "Россия"},
    {"name": "Ростов-на-Дону", "lat": 47.2357, "lon": 39.7015, "country": "Россия"},
    {"name": "Краснодар", "lat": 45.0355, "lon": 38.9753, "country": "Россия"},
    {"name": "Воронеж", "lat": 51.6608, "lon": 39.2003, "country": "Россия"},
    {"name": "Пермь", "lat": 58.0105, "lon": 56.2502, "country": "Россия"},
    {"name": "Волгоград", "lat": 48.708, "lon": 44.5133, "country": "Россия"},
    {"name": "Красноярск", "lat": 56.0153, "lon": 92.8932, "country": "Россия"},
    {"name": "Сочи", "lat": 43.6028, "lon": 39.7342, "country": "Россия"},
    {"name": "Иннополис", "lat": 55.752, "lon": 48.7446, "country": "Россия"},
    {"name": "Минск", "lat": 53.9006, "lon": 27.559, "country": "Беларусь"},
    {"name": "Гомель", "lat": 52.4345, "lon": 30.9754, "country": "Беларусь"},
    {"name": "Брест", "lat": 52.0976, "lon": 23.7341, "country": "Беларусь"},
    {"name": "Алматы", "lat": 43.222, "lon": 76.8512, "country": "Казахстан"},
    {"name": "Астана", "lat": 51.1694, "lon": 71.4491, "country": "Казахстан"},
    {"name": "Шымкент", "lat": 42.3417, "lon": 69.5901, "country": "Казахстан"},
    {"name": "Ереван", "lat": 40.1792, "lon": 44.4991, "country": "Армения"},
    {"name": "Гюмри", "lat": 40.7894, "lon": 43.8475, "country": "Армения"},
    {"name": "Бишкек", "lat": 42.8746, "lon": 74.5698, "country": "Кыргызстан"},
    {"name": "Ош", "lat": 40.5283, "lon": 72.7985, "country": "Кыргызстан"},
    {"name": "Ташкент", "lat": 41.2995, "lon": 69.2401, "country": "Узбекистан"},
    {"name": "Самарканд", "lat": 39.6542, "lon": 66.9597, "country": "Узбекистан"},
    {"name": "Душанбе", "lat": 38.5598, "lon": 68.787, "country": "Таджикистан"},
    {"name": "Худжанд", "lat": 40.2826, "lon": 69.6222, "country": "Таджикистан"},
    {"name": "Баку", "lat": 40.4093, "lon": 49.8671, "country": "Азербайджан"},
    {"name": "Гянджа", "lat": 40.6828, "lon": 46.3606, "country": "Азербайджан"},
]
CITY_BY_NAME = {item["name"]: item for item in CITIES}
TRIP_KINDS = ("city", "intercity", "international")
KIND_RATE = {"city": 8, "intercity": 5, "international": 4}
CITY_CLUSTER = (frozenset(("Казань", "Иннополис")),)
MONTHS = "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()

app = Flask(__name__, template_folder="templates", static_folder="static")


def load_secret():
    env_secret = (os.environ.get("ALONG_SECRET_KEY") or "").strip()
    if env_secret:
        return env_secret
    if os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    value = secrets.token_hex(32)
    with open(SECRET_PATH, "w", encoding="utf-8") as handle:
        handle.write(value)
    return value


app.secret_key = load_secret()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=SECURE_COOKIES,
    PERMANENT_SESSION_LIFETIME=timedelta(seconds=SESSION_SECONDS),
)

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data: blob: https:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "script-src 'self' 'unsafe-inline' https://unpkg.com; "
    "connect-src 'self' https://nominatim.openstreetmap.org https://router.project-osrm.org "
    "https://tile.openstreetmap.org https://tiles.openfreemap.org https://unpkg.com; "
    "worker-src 'self' blob:; child-src 'self' blob:; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@app.after_request
def security_headers(response):
    """Единые заголовки безопасности и журнал запросов для всех ответов."""
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(self)")
    if SECURE_COOKIES:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    if request.endpoint not in ("static", "media"):
        log.info("%s %s -> %s", request.method, request.path, response.status_code)
    return response


def db():
    return g.db


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return salt.hex() + ":" + digest.hex()


def check_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 200_000
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_is_hashed(value):
    if not value or len(value) != 64:
        return False
    try:
        int(value, 16)
    except (TypeError, ValueError):
        return False
    return True


def text_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_ts():
    return datetime.now().timestamp()


def future_dt(days, hour, minute):
    moment = datetime.now() + timedelta(days=days)
    return moment.replace(hour=hour, minute=minute, second=0, microsecond=0)


def fmt_dt(value):
    if not value:
        return ""
    moment = datetime.fromisoformat(value)
    return f"{moment.day} {MONTHS[moment.month - 1]}, {moment.strftime('%H:%M')}"


def fmt_ts(value):
    try:
        moment = datetime.fromtimestamp(float(value))
    except (TypeError, ValueError, OSError, OverflowError):
        return ""
    return f"{moment.day} {MONTHS[moment.month - 1]} {moment.year}"


def trip_meta(row):
    left = int(row["seats_total"]) - int(row["seats_taken"])
    moment = datetime.fromisoformat(row["depart_at"])
    if row["status"] == "hidden":
        badge = "скрыта"
    elif row["status"] == "cancelled":
        badge = "отменена"
    elif moment < datetime.now():
        badge = "завершена"
    elif left <= 0:
        badge = "мест нет"
    elif left == 1:
        badge = "почти заполнено"
    else:
        badge = "есть места"
    return badge, left, moment < datetime.now()


def public_closed(row):
    badge, left, past = trip_meta(row)
    if row["status"] in ("hidden", "cancelled"):
        return True, badge, left, past
    return False, badge, left, past


def normalize_phone(value):
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 11 and digits.startswith("7"):
        return "+" + digits
    return None


def resolve_place(name, lat, lon, allow_here=False):
    cleaned = (name or "").strip()
    if allow_here and cleaned == HERE:
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            return None, "Выберите адрес из списка"
        if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
            return None, "Выберите адрес из списка"
        return {"name": HERE, "lat": lat_f, "lon": lon_f}, None
    city = CITY_BY_NAME.get(cleaned)
    if not city:
        head = cleaned.split(",")[0].strip()
        city = CITY_BY_NAME.get(head)
    if not city:
        return None, "Выберите адрес из списка"
    return city, None


def parse_ride_date(value):
    try:
        day = datetime.strptime(value or "", "%Y-%m-%d").date()
    except ValueError:
        return None, "Выберите дату"
    if day < datetime.now().date():
        return None, "Выберите сегодня или будущую дату"
    return day, None


def ensure_csrf():
    token = session.get("csrf")
    if not token:
        token = secrets.token_hex(16)
        session["csrf"] = token
    return token


def check_csrf():
    sent = request.form.get("csrf") or ""
    saved = session.get("csrf") or ""
    if not saved or not hmac.compare_digest(sent, saved):
        abort(400)


def current_user():
    if hasattr(g, "me"):
        return g.me
    g.expired = False
    g.me = None
    token = request.cookies.get("along_sid")
    if not token:
        return None
    digest = hash_token(token)
    row = db().execute(
        """
        SELECT u.*, s.expires_at
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = ?
        """,
        (digest,),
    ).fetchone()
    if not row:
        return None
    if row["expires_at"] < now_ts() or row["status"] == "blocked":
        db().execute("DELETE FROM sessions WHERE token = ?", (digest,))
        db().commit()
        g.expired = row["expires_at"] < now_ts()
        return None
    g.me = row
    return row


def require_user(verified=False):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_user()
            target = request.full_path if request.query_string else request.path
            if g.expired:
                return redirect(url_for("login", next=target, expired=1))
            if not g.me:
                return redirect(url_for("login", next=target))
            if verified and not g.me["verified"]:
                flash("Подтвердите почту, чтобы продолжить.")
                return redirect(url_for("me_page"))
            return func(*args, **kwargs)
        return wrapper
    return decorator


def require_admin(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        current_user()
        target = request.full_path if request.query_string else request.path
        if g.expired:
            return redirect(url_for("login", next=target, expired=1))
        if not g.me:
            return redirect(url_for("login", next=target))
        if g.me["role"] != "admin":
            return render_template("denied.html"), 403
        return func(*args, **kwargs)
    return wrapper


def safe_next(value):
    if not value or not value.startswith("/") or value.startswith("//"):
        return url_for("home")
    return value


def verify_link(token, nxt=""):
    """Абсолютная ссылка подтверждения: для письма и для демо-показа."""
    path = url_for("verify_token", token=token, next=nxt)
    if BASE_URL:
        return BASE_URL + path
    return request.url_root.rstrip("/") + path


def haversine(lat1, lon1, lat2, lon2):
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


_CACHE = {}
_CACHE_LOCK = threading.Lock()


def cache_get(key):
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if not item:
            return None
        expires, value = item
        if expires < time.time():
            _CACHE.pop(key, None)
            return None
        return value


def cache_set(key, value, ttl=600):
    with _CACHE_LOCK:
        if len(_CACHE) > 500:
            _CACHE.clear()
        _CACHE[key] = (time.time() + ttl, value)


_RATE = {}
_RATE_LOCK = threading.Lock()


def rate_limit(key, limit, window=60):
    """Возвращает True, если за окно исчерпан лимит действий."""
    if not key:
        return False
    moment = time.time()
    with _RATE_LOCK:
        if len(_RATE) > 2000:
            for old in [name for name, item in _RATE.items() if item[0] < moment]:
                _RATE.pop(old, None)
        bucket = _RATE.get(key)
        if not bucket or bucket[0] < moment:
            _RATE[key] = [moment + window, 1]
            return False
        if bucket[1] >= limit:
            return True
        bucket[1] += 1
        return False


def client_key(prefix):
    return prefix + ":" + (request.remote_addr or "local")


PASSWORD_RESET_SALT = "along-password-reset"
PASSWORD_RESET_MAX_AGE = 30 * 60


def password_serializer():
    return URLSafeTimedSerializer(app.secret_key, salt=PASSWORD_RESET_SALT)


def password_fingerprint(password_hash):
    return hashlib.sha256((password_hash or "").encode("utf-8")).hexdigest()[:32]


def password_reset_token(user):
    payload = "{}:{}".format(user["id"], password_fingerprint(user["password_hash"]))
    return password_serializer().dumps(payload)


def password_reset_target(value):
    try:
        payload = password_serializer().loads(value, max_age=PASSWORD_RESET_MAX_AGE)
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    raw_id, _, fingerprint = str(payload).partition(":")
    try:
        user_id = int(raw_id)
    except (TypeError, ValueError):
        return None
    user = db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user or password_fingerprint(user["password_hash"]) != fingerprint:
        return None
    return user


def reset_password(user, new_password):
    db().execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(new_password), user["id"]),
    )
    db().execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    db().commit()


def password_problem(password, repeat):
    if len(password) < 8:
        return "Не меньше 8 символов"
    if password != repeat:
        return "Пароли не совпадают"
    return None


def demo_password_link(user, nxt=""):
    token = password_reset_token(user)
    path = url_for("password_reset", token=token)
    if nxt:
        path += "?" + urlencode({"next": nxt})
    link = (BASE_URL + path) if BASE_URL else (request.url_root.rstrip("/") + path)
    sent, reason = send_mail(
        user["email"],
        "ALONG: восстановление пароля",
        "Чтобы задать новый пароль, откройте ссылку в течение 30 минут:\n%s\n\n"
        "Если вы не просили восстановление, просто проигнорируйте письмо." % link,
    )
    return link, sent, reason


def csv_cell(value):
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def cleanup_sessions(connection=None):
    target = connection if connection is not None else db()
    try:
        target.execute("DELETE FROM sessions WHERE expires_at < ?", (now_ts(),))
        target.commit()
    except sqlite3.Error:
        try:
            target.rollback()
        except sqlite3.Error:
            pass


_LAST_SESSION_CLEAN = 0.0


def maybe_clean_sessions():
    global _LAST_SESSION_CLEAN
    if time.time() - _LAST_SESSION_CLEAN < 86400:
        return
    _LAST_SESSION_CLEAN = time.time()
    cleanup_sessions()


def nearest_city(lat, lon, limit_km=25):
    best = None
    for city in CITIES:
        try:
            distance = haversine(lat, lon, city["lat"], city["lon"])
        except (TypeError, ValueError):
            continue
        if distance <= limit_km and (best is None or distance < best[0]):
            best = (distance, city)
    return best[1] if best else None


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'admin')),
            city TEXT,
            phone TEXT,
            about TEXT,
            car TEXT,
            photo TEXT,
            rating REAL DEFAULT 5,
            trips_count INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'review', 'blocked')),
            verified INTEGER NOT NULL DEFAULT 0,
            verify_token TEXT,
            verify_sent REAL,
            created_at REAL NOT NULL,
            driver_status TEXT DEFAULT 'none'
        );
        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY,
            driver_id INTEGER NOT NULL REFERENCES users(id),
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            origin_lat REAL,
            origin_lon REAL,
            dest_lat REAL,
            dest_lon REAL,
            depart_at TEXT NOT NULL,
            price INTEGER NOT NULL,
            seats_total INTEGER NOT NULL,
            seats_taken INTEGER NOT NULL DEFAULT 0,
            pickup TEXT,
            dropoff TEXT,
            luggage TEXT,
            comment TEXT,
            status TEXT NOT NULL DEFAULT 'open'
                CHECK(status IN ('open', 'hidden', 'cancelled')),
            hide_reason TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY,
            trip_id INTEGER NOT NULL REFERENCES trips(id),
            passenger_id INTEGER NOT NULL REFERENCES users(id),
            seats INTEGER NOT NULL,
            status TEXT NOT NULL,
            meeting TEXT,
            phone TEXT,
            luggage TEXT,
            comment TEXT,
            reject_reason TEXT,
            passenger_ok INTEGER NOT NULL DEFAULT 0,
            driver_ok INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS booking_live
            ON bookings(trip_id, passenger_id)
            WHERE status NOT IN ('rejected', 'cancelled');
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY,
            mode TEXT NOT NULL CHECK(mode IN ('bus', 'plane', 'train')),
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            depart_at TEXT NOT NULL,
            title TEXT NOT NULL,
            sold_out INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY,
            author_id INTEGER NOT NULL REFERENCES users(id),
            trip_id INTEGER REFERENCES trips(id),
            body TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('open', 'done')),
            staff_note TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS saved_routes (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            origin_lat REAL,
            origin_lon REAL,
            dest_lat REAL,
            dest_lon REAL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            expires_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY,
            trip_id INTEGER REFERENCES trips(id),
            author_id INTEGER NOT NULL REFERENCES users(id),
            target_id INTEGER REFERENCES users(id),
            rating REAL NOT NULL,
            text TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS custom_offers (
            id INTEGER PRIMARY KEY,
            passenger_id INTEGER NOT NULL REFERENCES users(id),
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            offer_price INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    migrate_token_hashes(con)
    count = con.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    if count == 0:
        seed(con)
    migrate_reviews(con)
    migrate_driver_and_chat(con)
    migrate_offers_and_schedule(con)
    migrate_admin_log(con)
    create_indexes(con)
    con.execute("DELETE FROM sessions WHERE expires_at < ?", (now_ts(),))
    con.commit()
    con.close()


def migrate_admin_log(con):
    """Журнал действий администратора. Повторный запуск таблицу не дублирует."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_log (
            id INTEGER PRIMARY KEY,
            admin_id INTEGER REFERENCES users(id),
            action TEXT NOT NULL,
            entity TEXT NOT NULL,
            entity_id INTEGER,
            details TEXT,
            created_at REAL NOT NULL
        )
        """
    )


INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_trips_driver ON trips(driver_id)",
    "CREATE INDEX IF NOT EXISTS idx_trips_status ON trips(status)",
    "CREATE INDEX IF NOT EXISTS idx_trips_depart ON trips(depart_at)",
    "CREATE INDEX IF NOT EXISTS idx_bookings_trip ON bookings(trip_id)",
    "CREATE INDEX IF NOT EXISTS idx_bookings_passenger ON bookings(passenger_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_receiver ON messages(receiver_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_trip ON messages(trip_id)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_target ON reviews(target_id)",
    "CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_admin_log_created ON admin_log(created_at)",
)


def create_indexes(con):
    """Индексы по внешним ключам и частым фильтрам. Идемпотентно."""
    for statement in INDEX_STATEMENTS:
        con.execute(statement)


def migrate_token_hashes(con):
    """Сырые токены сессии и подтверждения почты заменяются хешем. Пароли не меняются."""
    for row in con.execute("SELECT token FROM sessions").fetchall():
        raw = row["token"]
        if raw and not token_is_hashed(raw):
            con.execute(
                "UPDATE sessions SET token = ? WHERE token = ?",
                (hash_token(raw), raw),
            )
    for row in con.execute(
        "SELECT id, verify_token FROM users WHERE verify_token IS NOT NULL AND verify_token != ''"
    ).fetchall():
        raw = row["verify_token"]
        if raw and not token_is_hashed(raw):
            con.execute(
                "UPDATE users SET verify_token = ? WHERE id = ?",
                (hash_token(raw), row["id"]),
            )


def migrate_reviews(con):
    """Дополняет reviews и сводит её к одному источнику истины: target_id и text."""
    cols = {row["name"] for row in con.execute("PRAGMA table_info(reviews)").fetchall()}
    additions = (
        (
            "trip_id",
            "ALTER TABLE reviews ADD COLUMN trip_id INTEGER REFERENCES trips(id)",
            "ALTER TABLE reviews ADD COLUMN trip_id INTEGER",
        ),
        (
            "target_id",
            "ALTER TABLE reviews ADD COLUMN target_id INTEGER REFERENCES users(id)",
            "ALTER TABLE reviews ADD COLUMN target_id INTEGER",
        ),
        (
            "text",
            "ALTER TABLE reviews ADD COLUMN text TEXT",
            "ALTER TABLE reviews ADD COLUMN text TEXT",
        ),
    )
    for name, statement, fallback in additions:
        if name not in cols:
            try:
                con.execute(statement)
            except sqlite3.OperationalError:
                con.execute(fallback)
    cols = {row["name"] for row in con.execute("PRAGMA table_info(reviews)").fetchall()}
    if "driver_id" in cols:
        con.execute(
            "UPDATE reviews SET target_id = driver_id WHERE target_id IS NULL AND driver_id IS NOT NULL"
        )
    if "body" in cols:
        con.execute(
            "UPDATE reviews SET text = body WHERE (text IS NULL OR text = '') AND body IS NOT NULL"
        )
    if "driver_id" in cols or "body" in cols:
        rebuild_canonical_reviews(con)
    con.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS reviews_one_pair
        ON reviews(trip_id, author_id, target_id)
        """
    )


def rebuild_canonical_reviews(con):
    """Удаляет legacy-колонки driver_id и body, сохраняя все отзывы."""
    rows = [dict(row) for row in con.execute("SELECT * FROM reviews").fetchall()]
    con.execute("DROP TABLE IF EXISTS reviews_new")
    con.execute(
        """
        CREATE TABLE reviews_new (
            id INTEGER PRIMARY KEY,
            trip_id INTEGER REFERENCES trips(id),
            author_id INTEGER NOT NULL REFERENCES users(id),
            target_id INTEGER REFERENCES users(id),
            rating REAL NOT NULL,
            text TEXT,
            created_at REAL NOT NULL
        )
        """
    )
    for row in rows:
        con.execute(
            """
            INSERT INTO reviews_new
            (id, trip_id, author_id, target_id, rating, text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("id"),
                row.get("trip_id"),
                row.get("author_id"),
                row.get("target_id") or row.get("driver_id"),
                row.get("rating"),
                row.get("text") or row.get("body"),
                row.get("created_at"),
            ),
        )
    con.execute("DROP TABLE reviews")
    con.execute("ALTER TABLE reviews_new RENAME TO reviews")


def migrate_driver_and_chat(con):
    """Статус водителя, заявки на отказ и сообщения. Повторный запуск не затирает решение админа."""
    cols = {row["name"] for row in con.execute("PRAGMA table_info(users)").fetchall()}
    if "driver_status" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN driver_status TEXT DEFAULT 'none'")
    con.execute(
        "UPDATE users SET driver_status = 'none' WHERE driver_status IS NULL OR driver_status = ''"
    )
    con.execute(
        """
        UPDATE users SET driver_status = 'approved'
        WHERE driver_status = 'none'
          AND id IN (SELECT DISTINCT driver_id FROM trips)
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS driver_resignations (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            sender_id INTEGER NOT NULL REFERENCES users(id),
            receiver_id INTEGER NOT NULL REFERENCES users(id),
            trip_id INTEGER REFERENCES trips(id),
            text TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )


def migrate_offers_and_schedule(con):
    """Заявки со своей ценой и справочная пересадка. Повторный запуск не плодит рейс."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_offers (
            id INTEGER PRIMARY KEY,
            passenger_id INTEGER NOT NULL REFERENCES users(id),
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            offer_price INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cols = {row["name"] for row in con.execute("PRAGMA table_info(schedules)").fetchall()}
    if "via" not in cols:
        con.execute("ALTER TABLE schedules ADD COLUMN via TEXT")
    if "layover_min" not in cols:
        con.execute("ALTER TABLE schedules ADD COLUMN layover_min INTEGER")
    if "leg2_at" not in cols:
        con.execute("ALTER TABLE schedules ADD COLUMN leg2_at TEXT")
    exists = con.execute(
        """
        SELECT id FROM schedules
        WHERE origin = ? AND destination = ? AND via = ?
        """,
        ("Москва", "Сочи", "Ростов-на-Дону"),
    ).fetchone()
    if exists:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    row = con.execute(
        """
        SELECT substr(depart_at, 1, 10) AS day
        FROM schedules
        WHERE substr(depart_at, 1, 10) >= ?
        ORDER BY day
        LIMIT 1
        """,
        (today,),
    ).fetchone()
    if row and row["day"]:
        day = row["day"]
    else:
        day = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    con.execute(
        """
        INSERT INTO schedules
        (mode, origin, destination, depart_at, title, sold_out, via, layover_min, leg2_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "train",
            "Москва",
            "Сочи",
            day + "T08:20",
            "Поезд с пересадкой",
            0,
            "Ростов-на-Дону",
            55,
            day + "T14:15",
        ),
    )


def add_user(con, name, email, password, role, city, phone, about, car, photo, rating, trips_count, status="active"):
    cur = con.execute(
        """
        INSERT INTO users
        (name, email, password_hash, role, city, phone, about, car, photo, rating,
         trips_count, status, verified, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (name, email, hash_password(password), role, city, phone, about, car, photo,
         rating, trips_count, status, now_ts()),
    )
    return cur.lastrowid


def seed(con):
    admin_password = os.environ.get("ALONG_ADMIN_PASSWORD") or secrets.token_urlsafe(9)
    user_password = os.environ.get("ALONG_USER_PASSWORD") or secrets.token_urlsafe(9)
    if not os.environ.get("ALONG_ADMIN_PASSWORD") or not os.environ.get("ALONG_USER_PASSWORD"):
        print(
            "ALONG: создана новая база. Пароли демо-аккаунтов (сохраните и смените):\n"
            f"  admin@along.local  ->  {admin_password}\n"
            f"  user@along.local   ->  {user_password}\n"
            "  остальные демо-профили используют пароль пользователя."
        )
    admin_id = add_user(
        con, "Служба ALONG", "admin@along.local", admin_password, "admin",
        "Москва", "", "Сотрудник сервиса.", "", "city.jpg", 5, 0,
    )
    user_id = add_user(
        con, "Дина Каримова", "user@along.local", user_password, "user",
        "Казань", "", "Ищу попутчиков по России и в соседние страны.", "",
        "darya.jpg", 5, 0,
    )
    alina = add_user(
        con, "Алина Сафина", "alina@along.local", user_password, "user",
        "Казань", "+79001112233", "В салоне тихо, можно работать.",
        "Kia Ceed, 2021, серый", "alina.jpg", 4.9, 128,
    )
    elena = add_user(
        con, "Елена Воронова", "elena@along.local", user_password, "user",
        "Москва", "+79002223344", "Езжу по трассе без лишних остановок.",
        "Hyundai Solaris, белый", "elena.jpg", 4.8, 86,
    )
    timur = add_user(
        con, "Тимур Хакимов", "timur@along.local", user_password, "user",
        "Ереван", "+79003334455", "Беру один чемодан, если багажник свободен.",
        "Skoda Octavia, серая", "timur.jpg", 4.7, 54,
    )
    marat = add_user(
        con, "Марат Юсупов", "marat@along.local", user_password, "user",
        "Бишкек", "+79004445566", "Выезжаю утром от аэропорта.",
        "Volkswagen Polo, синий", "marat.jpg", 4.6, 41,
    )
    ilya = add_user(
        con, "Илья Ким", "ilya@along.local", user_password, "user",
        "Казань", "+79005556677", "Часто езжу пассажиром.",
        "", "ilya.jpg", 5, 12,
    )
    trips = [
        (alina, "Казань", "Алматы", "2026-place", 7, 40, 4200, 3, 1,
         "метро «Площадь Тукая»", "Алматы, аэропорт", "небольшой рюкзак",
         "Выезд рано утром, одна ночёвка не нужна: это учебный рейс макета на двое суток дороги не изображает, цена за место.",
         "open", None),
        (elena, "Москва", "Минск", "x", 9, 10, 1800, 3, 0,
         "метро «Белорусская»", "Минск, вокзал", "сумка",
         "По трассе, остановка по просьбе в Смоленске.", "open", None),
        (timur, "Ереван", "Баку", "x", 11, 20, 2400, 2, 1,
         "Ереван, площадь Республики", "Баку, вокзал", "чемодан",
         "Одно место ещё свободно.", "open", None),
        (marat, "Бишкек", "Ташкент", "x", 8, 0, 1600, 3, 0,
         "аэропорт Манас", "Ташкент, северный вокзал", "рюкзак",
         "Утренняя посадка у аэропорта.", "open", None),
        (alina, "Казань", "Иннополис", "x", 18, 30, 350, 3, 3,
         "Кольцо", "Университетская, 1", "нет",
         "Все места уже заняты.", "open", None),
        (elena, "Москва", "Астана", "x", 6, 50, 5000, 2, 0,
         "ВДНХ", "Астана, вокзал", "чемодан",
         "Скрыта модерацией.", "hidden", "Жалоба на описание маршрута"),
    ]
    trip_ids = []
    for item in trips:
        driver, origin, dest, _mark, hour, minute, price, total, taken, pickup, dropoff, luggage, comment, status, reason = item
        origin_city = CITY_BY_NAME[origin]
        dest_city = CITY_BY_NAME[dest]
        depart = future_dt(2 if origin != "Казань" or dest != "Иннополис" else 3, hour, minute)
        if origin == "Казань" and dest == "Алматы":
            depart = future_dt(2, hour, minute)
        cur = con.execute(
            """
            INSERT INTO trips
            (driver_id, origin, destination, origin_lat, origin_lon, dest_lat, dest_lon,
             depart_at, price, seats_total, seats_taken, pickup, dropoff, luggage, comment,
             status, hide_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (driver, origin, dest, origin_city["lat"], origin_city["lon"], dest_city["lat"],
             dest_city["lon"], depart.strftime("%Y-%m-%dT%H:%M"), price, total, taken,
             pickup, dropoff, luggage, comment, status, reason, now_ts()),
        )
        trip_ids.append(cur.lastrowid)
    con.execute(
        """
        INSERT INTO bookings
        (trip_id, passenger_id, seats, status, meeting, phone, luggage, comment,
         passenger_ok, driver_ok, created_at)
        VALUES (?, ?, 1, 'confirmed', ?, '+79005556677', 'рюкзак', 'Сажусь у Тукая', 1, 1, ?)
        """,
        (trip_ids[0], ilya, "метро «Площадь Тукая»", now_ts()),
    )
    schedules = [
        ("bus", "Москва", "Минск", 2, 8, 0, "Автобус, ночной"),
        ("plane", "Москва", "Минск", 2, 12, 30, "Самолёт, мест мало"),
        ("train", "Москва", "Минск", 2, 22, 10, "Поезд"),
        ("bus", "Казань", "Алматы", 2, 19, 0, "Автобус"),
        ("plane", "Ереван", "Баку", 2, 15, 40, "Самолёт, мест нет"),
        ("train", "Бишкек", "Ташкент", 4, 7, 20, "Поезд"),
    ]
    for mode, origin, dest, day, hour, sold, title in schedules:
        depart = future_dt(day, hour, 15)
        con.execute(
            """
            INSERT INTO schedules (mode, origin, destination, depart_at, title, sold_out)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (mode, origin, dest, depart.strftime("%Y-%m-%dT%H:%M"), title, sold),
        )
    con.execute(
        """
        INSERT INTO reviews (author_id, target_id, text, rating, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (ilya, alina, "Выехали вовремя, в салоне спокойно.", 5, now_ts()),
    )
    con.execute(
        """
        INSERT INTO reviews (author_id, target_id, text, rating, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, elena, "До Минска без сюрпризов.", 5, now_ts()),
    )
    con.execute(
        """
        INSERT INTO complaints (author_id, trip_id, body, status, staff_note, created_at)
        VALUES (?, ?, ?, 'open', '', ?)
        """,
        (user_id, trip_ids[5], "В описании маршрут короче, чем дорога на карте.", now_ts()),
    )
    con.execute(
        """
        INSERT INTO complaints (author_id, trip_id, body, status, staff_note, created_at)
        VALUES (?, ?, ?, 'done', 'Описание поправили.', ?)
        """,
        (ilya, trip_ids[1], "Просьба уточнить остановку.", now_ts() - 86400),
    )
    return admin_id


def page_number():
    try:
        value = int(request.args.get("page") or 1)
    except (TypeError, ValueError):
        value = 1
    return max(1, value)


def paginate_query(sql, args, per_page=PER_PAGE):
    """Возвращает страницу выборки и метаданные для шаблона."""
    page = page_number()
    total = db().execute(
        "SELECT COUNT(*) AS n FROM (" + sql + ")", list(args)
    ).fetchone()["n"]
    pages = max(1, math.ceil(total / per_page))
    page = min(page, pages)
    rows = db().execute(
        sql + " LIMIT ? OFFSET ?", list(args) + [per_page, (page - 1) * per_page]
    ).fetchall()
    return rows, page, pages, total


def log_admin(action, entity, entity_id=None, details=""):
    """Пишет действие администратора в журнал. Ошибка журнала не ломает операцию."""
    try:
        admin_id = g.me["id"] if getattr(g, "me", None) else None
        db().execute(
            """
            INSERT INTO admin_log (admin_id, action, entity, entity_id, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (admin_id, action, entity, entity_id, (details or "")[:500], now_ts()),
        )
    except sqlite3.Error:
        log.warning("Не удалось записать действие администратора: %s %s", action, entity)


def refresh_user_stats(user_id):
    """Пересчитывает кэширующие поля users.rating и users.trips_count по фактам."""
    average = db().execute(
        "SELECT AVG(rating) AS value FROM reviews WHERE target_id = ?", (user_id,)
    ).fetchone()["value"]
    trips = db().execute(
        "SELECT COUNT(*) AS n FROM trips WHERE driver_id = ? AND status != 'cancelled'",
        (user_id,),
    ).fetchone()["n"]
    db().execute(
        "UPDATE users SET rating = ?, trips_count = ? WHERE id = ?",
        (round(float(average), 2) if average is not None else 5, int(trips or 0), user_id),
    )


def clean_login_attempts():
    """Удаляет попытки входа старше суток, чтобы таблица не росла бесконечно."""
    db().execute("DELETE FROM login_attempts WHERE created_at < ?", (now_ts() - 86400,))


@app.before_request
def open_db():
    g.db = sqlite3.connect(DB_PATH)
    g.db.row_factory = sqlite3.Row
    g.db.execute("PRAGMA foreign_keys = ON")
    g.db.execute("PRAGMA busy_timeout = 5000")
    try:
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.OperationalError:
        log.warning("Не удалось включить WAL: база занята другим процессом")
    maybe_clean_sessions()


@app.teardown_request
def close_db(_exc):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def chat_href(user_id, trip_id=None, admin=False):
    params = {"with": user_id}
    if trip_id:
        params["trip"] = trip_id
    return url_for("admin_messages" if admin else "chat", **params)


@app.template_filter("status_label")
def status_label(value):
    key = (value or "").strip().lower()
    return STATUS_LABELS.get(key, value or "")


COMPLAINT_LABELS = {"open": "на проверке", "done": "разобрана"}


@app.template_filter("complaint_label")
def complaint_label(value):
    key = (value or "").strip().lower()
    return COMPLAINT_LABELS.get(key, value or "")


EMPTY_NOTIFICATIONS = {"clarify": 0, "unread": 0, "problems": 0, "total": 0}


def notification_counts(user):
    """Счётчики шапки: новые заявки водителю, непрочитанные сообщения, отказы и отмены."""
    if not user or not getattr(g, "db", None):
        return dict(EMPTY_NOTIFICATIONS)
    moment = datetime.now().strftime("%Y-%m-%dT%H:%M")
    counts = dict(EMPTY_NOTIFICATIONS)
    try:
        counts["clarify"] = db().execute(
            """
            SELECT COUNT(*) AS n
            FROM bookings b JOIN trips t ON t.id = b.trip_id
            WHERE t.driver_id = ? AND b.status = 'clarify'
              AND t.status = 'open' AND t.depart_at >= ?
            """,
            (user["id"], moment),
        ).fetchone()["n"]
        counts["unread"] = db().execute(
            "SELECT COUNT(*) AS n FROM messages WHERE receiver_id = ? AND is_read = 0",
            (user["id"],),
        ).fetchone()["n"]
        counts["problems"] = db().execute(
            """
            SELECT COUNT(DISTINCT b.trip_id) AS n
            FROM bookings b JOIN trips t ON t.id = b.trip_id
            WHERE b.passenger_id = ?
              AND (b.status = 'rejected' OR t.status = 'cancelled')
              AND t.depart_at >= ?
            """,
            (user["id"], moment),
        ).fetchone()["n"]
    except sqlite3.Error:
        log.warning("Не удалось посчитать уведомления для пользователя %s", user["id"])
        return dict(EMPTY_NOTIFICATIONS)
    counts["total"] = counts["unread"] + counts["clarify"] + counts["problems"]
    return counts


@app.context_processor
def inject():
    user = current_user()
    return {
        "me": user,
        "csrf": ensure_csrf(),
        "fmt_dt": fmt_dt,
        "fmt_ts": fmt_ts,
        "trip_meta": trip_meta,
        "here_label": HERE,
        "chat_href": chat_href,
        "notifications": notification_counts(user),
    }


@app.route("/media/<path:name>")
def media(name):
    return send_from_directory(IMAGES, name)


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_UA = "ALONG-App/1.0 (course project; contact local)"
NOMINATIM_COUNTRIES = "ru,by,kz,am,kg,uz,tj,az"


def nominatim_places(query):
    cache_key = "geo:" + query.casefold()
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    params = urlencode({
        "format": "json",
        "q": query,
        "limit": 8,
        "accept-language": "ru",
        "countrycodes": NOMINATIM_COUNTRIES,
    })
    upstream = Request(
        NOMINATIM_URL + "?" + params,
        headers={
            "User-Agent": NOMINATIM_UA,
            "Accept": "application/json",
            "Accept-Language": "ru",
        },
    )
    try:
        with urlopen(upstream, timeout=8) as response:
            raw = response.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    places = []
    seen = set()
    for item in data[:8]:
        if not isinstance(item, dict):
            continue
        name = item.get("display_name")
        try:
            lat = float(item.get("lat"))
            lon = float(item.get("lon"))
        except (TypeError, ValueError):
            continue
        if not name or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        city = nearest_city(lat, lon)
        if not city:
            head = str(name).split(",")[0].strip()
            city = CITY_BY_NAME.get(head)
        if not city or city["name"] in seen:
            continue
        seen.add(city["name"])
        places.append({
            "display_name": city["name"],
            "lat": city["lat"],
            "lon": city["lon"],
        })
    cache_set(cache_key, places)
    return places


@app.route("/api/geocode")
def geocode():
    query = (request.args.get("q") or "").strip()
    if len(query) < 2:
        return Response("[]", mimetype="application/json")
    if rate_limit(client_key("geocode"), 60, 60):
        return Response(
            json.dumps({"error": "Слишком много запросов. Подождите минуту."}, ensure_ascii=False),
            status=429,
            mimetype="application/json",
        )
    try:
        places = nominatim_places(query[:120])
    except Exception:
        places = []
    return Response(json.dumps(places, ensure_ascii=False), mimetype="application/json")


def country_of(name):
    city = CITY_BY_NAME.get((name or "").strip())
    if not city:
        return None
    return city.get("country")


def trip_kind(origin, destination):
    """city — один пункт или агломерация, intercity — одна страна, international — разные страны из словаря."""
    left = (origin or "").strip()
    right = (destination or "").strip()
    if not left or not right:
        return None
    folded_left = left.casefold()
    folded_right = right.casefold()
    if folded_left == folded_right or folded_left in folded_right or folded_right in folded_left:
        return "city"
    if frozenset((left, right)) in CITY_CLUSTER:
        return "city"
    left_country = country_of(left)
    right_country = country_of(right)
    if not left_country or not right_country:
        return None
    if left_country != right_country:
        return "international"
    return "intercity"


def clean_kind(value):
    value = (value or "").strip()
    if value in TRIP_KINDS:
        return value
    return ""


def trip_day_counts(origin="", dest="", kind="", from_lat=None, from_lon=None):
    """Даты открытых поездок и число выездов. Чужие поля в ответ не попадают."""
    origin = (origin or "").strip()
    dest = (dest or "").strip()
    kind = clean_kind(kind)
    if origin and origin != HERE and origin not in CITY_BY_NAME:
        return []
    if dest and dest not in CITY_BY_NAME:
        return []
    here_point = None
    if origin == HERE:
        try:
            lat_f = float(from_lat)
            lon_f = float(from_lon)
            if -90 <= lat_f <= 90 and -180 <= lon_f <= 180:
                here_point = (lat_f, lon_f)
        except (TypeError, ValueError):
            here_point = None
        if not here_point:
            return []
    sql = """
        SELECT origin, destination, substr(depart_at, 1, 10) AS day
        FROM trips
        WHERE status = 'open' AND depart_at >= ?
    """
    args = [datetime.now().strftime("%Y-%m-%dT%H:%M")]
    if origin and origin in CITY_BY_NAME:
        sql += " AND origin = ?"
        args.append(origin)
    if dest and dest in CITY_BY_NAME:
        sql += " AND destination = ?"
        args.append(dest)
    try:
        rows = db().execute(sql, args).fetchall()
    except sqlite3.Error:
        return []
    counts = {}
    for row in rows:
        if kind and trip_kind(row["origin"], row["destination"]) != kind:
            continue
        if here_point:
            city = CITY_BY_NAME.get(row["origin"])
            if not city or haversine(here_point[0], here_point[1], city["lat"], city["lon"]) > 50:
                continue
        day = row["day"]
        if not day:
            continue
        counts[day] = counts.get(day, 0) + 1
    return [{"date": day, "count": counts[day]} for day in sorted(counts)]


def schedule_day_counts(mode, origin="", dest=""):
    if mode not in ("bus", "plane", "train"):
        mode = "bus"
    origin = (origin or "").strip()
    dest = (dest or "").strip()
    sql = """
        SELECT substr(depart_at, 1, 10) AS day
        FROM schedules
        WHERE mode = ? AND substr(depart_at, 1, 10) >= ?
    """
    args = [mode, datetime.now().strftime("%Y-%m-%d")]
    if origin in CITY_BY_NAME:
        sql += " AND origin = ?"
        args.append(origin)
    if dest in CITY_BY_NAME:
        sql += " AND destination = ?"
        args.append(dest)
    try:
        rows = db().execute(sql, args).fetchall()
    except sqlite3.Error:
        return []
    counts = {}
    for row in rows:
        day = row["day"]
        if not day:
            continue
        counts[day] = counts.get(day, 0) + 1
    return [{"date": day, "count": counts[day]} for day in sorted(counts)]


def place_coords(name, lat, lon):
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        lat_f = None
        lon_f = None
    if lat_f is not None and lon_f is not None and -90 <= lat_f <= 90 and -180 <= lon_f <= 180:
        return lat_f, lon_f
    city = CITY_BY_NAME.get((name or "").strip())
    if city:
        return city["lat"], city["lon"]
    query = (name or "").strip()
    if len(query) < 2:
        return None
    try:
        places = nominatim_places(query[:120])
    except Exception:
        places = []
    if not places:
        return None
    return places[0]["lat"], places[0]["lon"]


def driving_km(lat1, lon1, lat2, lon2):
    cache_key = "osrm:{:.4f},{:.4f};{:.4f},{:.4f}".format(lat1, lon1, lat2, lon2)
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    path = "{:.6f},{:.6f};{:.6f},{:.6f}".format(lon1, lat1, lon2, lat2)
    url = "https://router.project-osrm.org/route/v1/driving/" + path + "?overview=false"
    upstream = Request(
        url,
        headers={"User-Agent": NOMINATIM_UA, "Accept": "application/json"},
    )
    try:
        with urlopen(upstream, timeout=4) as response:
            raw = response.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return None
    try:
        if not isinstance(data, dict) or data.get("code") != "Ok":
            return None
        meters = float(data["routes"][0]["distance"])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    if meters <= 0:
        return None
    km = meters / 1000.0
    cache_set(cache_key, km)
    return km


def count_free_cars(origin, dest):
    """Активные поездки со свободными местами на этот маршрут или близкий."""
    try:
        rows = db().execute(
            """
            SELECT origin, destination, origin_lat, origin_lon, dest_lat, dest_lon
            FROM trips
            WHERE status = 'open' AND depart_at >= ? AND seats_total > seats_taken
            """,
            (datetime.now().strftime("%Y-%m-%dT%H:%M"),),
        ).fetchall()
    except sqlite3.Error:
        return 0
    origin_city = CITY_BY_NAME.get(origin)
    dest_city = CITY_BY_NAME.get(dest)
    total = 0
    for row in rows:
        same = row["origin"] == origin and row["destination"] == dest
        reverse = row["origin"] == dest and row["destination"] == origin
        close = False
        if origin_city and dest_city and row["origin_lat"] is not None and row["dest_lat"] is not None:
            try:
                start_km = haversine(origin_city["lat"], origin_city["lon"], row["origin_lat"], row["origin_lon"])
                finish_km = haversine(dest_city["lat"], dest_city["lon"], row["dest_lat"], row["dest_lon"])
                close = start_km <= 50 and finish_km <= 50
            except (TypeError, ValueError):
                close = False
        if same or reverse or close:
            total += 1
    return total


def recommend_price(origin, dest, kind, from_lat, from_lon, to_lat, to_lon):
    if kind not in KIND_RATE:
        return None, None, 0, "Выберите тип поездки, чтобы посчитать рекомендацию. Свою цену можно ввести вручную."
    cars = count_free_cars(origin, dest)
    start = place_coords(origin, from_lat, from_lon)
    finish = place_coords(dest, to_lat, to_lon)
    if not start or not finish:
        return None, None, cars, "Не удалось определить координаты городов. Укажите свою цену."
    try:
        km = driving_km(start[0], start[1], finish[0], finish[1])
    except Exception:
        km = None
    if km is None:
        return None, None, cars, "Не удалось получить расстояние: сервис маршрута не ответил. Укажите свою цену."
    raw = km * KIND_RATE[kind]
    if cars >= 3:
        raw = raw * 0.85
    quote = int(math.floor((raw / 10.0) + 0.5) * 10)
    if quote < 10:
        quote = 10
    return quote, int(round(km)), cars, None


@app.route("/")
def home():
    rows = db().execute(
        """
        SELECT t.*, u.name AS driver_name, u.photo, u.rating
        FROM trips t JOIN users u ON u.id = t.driver_id
        WHERE t.status = 'open' AND t.depart_at >= ?
        ORDER BY t.depart_at
        LIMIT 3
        """,
        (datetime.now().strftime("%Y-%m-%dT%H:%M"),),
    ).fetchall()
    try:
        days = trip_day_counts()
    except Exception:
        days = []
    return render_template("index.html", featured=rows, trip_days=days)


@app.route("/api/trip-days")
def api_trip_days():
    try:
        payload = trip_day_counts(
            request.args.get("from") or "",
            request.args.get("to") or "",
            request.args.get("kind") or "",
            request.args.get("from_lat"),
            request.args.get("from_lon"),
        )
    except Exception:
        payload = []
    return Response(json.dumps(payload, ensure_ascii=False), mimetype="application/json")


@app.route("/api/schedule-days")
def api_schedule_days():
    mode = request.args.get("mode") or "bus"
    if mode not in ("bus", "plane", "train"):
        mode = "bus"
    try:
        payload = schedule_day_counts(mode, request.args.get("from") or "", request.args.get("to") or "")
    except Exception:
        payload = []
    return Response(json.dumps(payload, ensure_ascii=False), mimetype="application/json")


@app.route("/trips")
def trips():
    origin = (request.args.get("from") or "").strip()
    dest = (request.args.get("to") or "").strip()
    kind = clean_kind(request.args.get("kind"))
    requested = (request.args.get("date") or "").strip()
    day, date_error = (None, None)
    if requested:
        day, date_error = parse_ride_date(requested)
    seats = request.args.get("seats") or ""
    price = request.args.get("price") or ""
    from_lat = request.args.get("from_lat")
    from_lon = request.args.get("from_lon")
    here_point = None
    if origin == HERE:
        try:
            lat_f = float(from_lat)
            lon_f = float(from_lon)
            if -90 <= lat_f <= 90 and -180 <= lon_f <= 180:
                here_point = (lat_f, lon_f)
        except (TypeError, ValueError):
            here_point = None
    place_error = None
    if origin and origin != HERE and origin not in CITY_BY_NAME:
        place_error = "Выберите адрес из списка"
    if dest and dest not in CITY_BY_NAME:
        place_error = "Выберите адрес из списка"
    if origin == HERE and not here_point:
        place_error = "Не удалось определить местоположение. Выберите город из списка."
    if origin and dest and origin == dest:
        place_error = "Укажите разные точки"
    sql = """
        SELECT t.*, u.name AS driver_name, u.photo, u.rating, u.car
        FROM trips t JOIN users u ON u.id = t.driver_id
        WHERE t.status = 'open' AND t.depart_at >= ?
    """
    args = [datetime.now().strftime("%Y-%m-%dT%H:%M")]
    if origin and origin in CITY_BY_NAME:
        sql += " AND t.origin = ?"
        args.append(origin)
    if dest and dest in CITY_BY_NAME:
        sql += " AND t.destination = ?"
        args.append(dest)
    sql += " ORDER BY t.depart_at"
    try:
        found = [] if place_error else db().execute(sql, args).fetchall()
    except sqlite3.Error:
        found = []
        place_error = place_error or "Поиск не выполнился. Повторите."
    if kind:
        found = [row for row in found if trip_kind(row["origin"], row["destination"]) == kind]
    if origin == HERE and here_point:
        near = []
        for row in found:
            city = CITY_BY_NAME.get(row["origin"])
            if city and haversine(here_point[0], here_point[1], city["lat"], city["lon"]) <= 50:
                near.append(row)
        found = near
    known_days = {}
    for row in found:
        stamp = (row["depart_at"] or "")[:10]
        if stamp:
            known_days[stamp] = known_days.get(stamp, 0) + 1
    trip_days = [{"date": stamp, "count": known_days[stamp]} for stamp in sorted(known_days)]
    date_value = ""
    if day and not date_error:
        date_value = day.isoformat()
    base_rows = [] if date_error else list(found)
    if day:
        base_rows = [row for row in base_rows if (row["depart_at"] or "")[:10] == day.isoformat()]
    filtered = False
    rows = list(base_rows)
    if seats.isdigit():
        need = int(seats)
        rows = [row for row in rows if (row["seats_total"] - row["seats_taken"]) >= need]
        filtered = True
    if price.isdigit():
        limit = int(price)
        rows = [row for row in rows if row["price"] <= limit]
        filtered = True
    failed = request.args.get("failed") == "1"
    route_ready = origin in CITY_BY_NAME and dest in CITY_BY_NAME and origin != dest
    show_offer = route_ready and not place_error and not date_error and not failed and not base_rows and not day
    quote_requested = request.args.get("quote") == "1"
    quote = quote_km = quote_cars = None
    quote_error = None
    if show_offer and quote_requested:
        if not kind:
            quote_error = "Выберите тип поездки, чтобы посчитать рекомендацию. Свою цену можно ввести вручную."
        else:
            try:
                quote, quote_km, quote_cars, quote_error = recommend_price(
                    origin, dest, kind, from_lat, from_lon,
                    request.args.get("to_lat"), request.args.get("to_lon"),
                )
            except Exception:
                quote_error = "Не удалось получить расстояние: сервис маршрута не ответил. Укажите свою цену."
            if quote is None and not quote_error:
                quote_error = "Расстояние временно недоступно. Укажите цену вручную."
    quote_args = {key: value for key, value in request.args.items()}
    quote_args["quote"] = "1"
    quote_link = url_for("trips", **quote_args)
    return render_template(
        "trips.html", rows=rows, origin=origin, dest=dest, kind=kind,
        date=date_value, seats=seats, price=price,
        place_error=place_error, date_error=date_error, filtered=filtered,
        failed=failed, had_base=bool(base_rows), trip_days=trip_days,
        show_offer=show_offer, quote=quote, quote_km=quote_km,
        quote_cars=quote_cars or 0, quote_error=quote_error,
        quote_requested=quote_requested, quote_link=quote_link,
        rate=KIND_RATE.get(kind),
    )


@app.route("/offers", methods=["POST"])
def create_offer():
    me = current_user()
    nxt = safe_next(request.form.get("next") or url_for("trips"))
    if g.expired:
        return redirect(url_for("login", next=nxt, expired=1))
    if not me:
        return redirect(url_for("login", next=nxt))
    if not me["verified"]:
        flash("Подтвердите почту, чтобы предложить цену.")
        return redirect(url_for("me_page"))
    if rate_limit("offer:" + str(me["id"]), 20, 60):
        flash("Слишком много предложений. Подождите минуту.")
        return redirect(nxt)
    check_csrf()
    origin = (request.form.get("origin") or "").strip()
    dest = (request.form.get("destination") or "").strip()
    if origin not in CITY_BY_NAME or dest not in CITY_BY_NAME or origin == dest:
        flash("Выберите адреса из списка.")
        return redirect(nxt)
    try:
        offer_price = int(request.form.get("offer_price") or "")
    except (TypeError, ValueError):
        offer_price = 0
    if offer_price < 50 or offer_price > 100000:
        flash("Укажите цену целым числом от 50 до 100000.")
        return redirect(nxt)
    day_ago = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    duplicate = db().execute(
        """
        SELECT id FROM custom_offers
        WHERE passenger_id = ? AND origin = ? AND destination = ?
          AND offer_price = ? AND created_at > ?
        LIMIT 1
        """,
        (me["id"], origin, dest, offer_price, day_ago),
    ).fetchone()
    if duplicate:
        flash("Такое предложение уже отправлено. Повторно можно через сутки.")
        return redirect(nxt)
    try:
        db().execute(
            """
            INSERT INTO custom_offers
            (passenger_id, origin, destination, offer_price, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (me["id"], origin, dest, offer_price, text_now()),
        )
        db().commit()
    except sqlite3.Error:
        db().rollback()
        flash("Не удалось сохранить предложение.")
        return redirect(nxt)
    flash("Предложение отправлено.")
    return redirect(nxt)


@app.route("/trips/new", methods=["GET", "POST"])
@require_user(verified=True)
def new_trip():
    errors = {}
    form = {
        "from": request.args.get("from") or request.form.get("from") or "",
        "to": request.args.get("to") or request.form.get("to") or "",
        "date": request.form.get("date") or request.args.get("date") or "",
        "time": request.form.get("time") or "08:00",
        "price": request.form.get("price") or "",
        "seats": request.form.get("seats") or "1",
        "pickup": request.form.get("pickup") or "",
        "dropoff": request.form.get("dropoff") or "",
        "luggage": request.form.get("luggage") or "",
        "comment": request.form.get("comment") or "",
        "from_lat": request.args.get("from_lat") or request.form.get("from_lat") or "",
        "from_lon": request.args.get("from_lon") or request.form.get("from_lon") or "",
        "to_lat": request.form.get("to_lat") or "",
        "to_lon": request.form.get("to_lon") or "",
    }
    if request.method == "POST":
        check_csrf()
        origin, err = resolve_place(form["from"], form["from_lat"], form["from_lon"], True)
        dest, err2 = resolve_place(form["to"], form["to_lat"], form["to_lon"], False)
        if err:
            errors["from"] = err
        if err2:
            errors["to"] = err2
        if origin and dest and origin["name"] == dest["name"]:
            errors["to"] = "Укажите разные точки"
        day, date_err = parse_ride_date(form["date"])
        if date_err:
            errors["date"] = date_err
        try:
            hour, minute = [int(part) for part in (form["time"] or "").split(":", 1)]
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            errors["time"] = "Укажите будущее время"
            hour = minute = 0
        if day and "time" not in errors:
            depart = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
            if depart <= datetime.now():
                errors["time"] = "Укажите будущее время"
        else:
            depart = None
        try:
            price = int(form["price"])
            if price <= 0:
                raise ValueError
        except ValueError:
            errors["price"] = "Укажите цену числом, больше нуля"
            price = 0
        try:
            seats = int(form["seats"])
            if seats < 1 or seats > 6:
                raise ValueError
        except ValueError:
            errors["seats"] = "Укажите хотя бы одно место"
            seats = 0
        if not (form["pickup"] or "").strip():
            errors["pickup"] = "Заполните поле"
        if (g.me["driver_status"] or "none") != "approved":
            errors["form"] = "Ваш статус водителя еще не подтвержден администратором"
        if not errors and origin and dest and depart:
            db().execute(
                """
                INSERT INTO trips
                (driver_id, origin, destination, origin_lat, origin_lon, dest_lat, dest_lon,
                 depart_at, price, seats_total, seats_taken, pickup, dropoff, luggage, comment,
                 status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, 'open', ?)
                """,
                (g.me["id"], origin["name"], dest["name"], origin["lat"], origin["lon"],
                 dest["lat"], dest["lon"], depart.strftime("%Y-%m-%dT%H:%M"), price, seats,
                 form["pickup"].strip(), form["dropoff"].strip(), form["luggage"].strip(),
                 form["comment"].strip(), now_ts()),
            )
            refresh_user_stats(g.me["id"])
            db().commit()
            flash("Поездка опубликована.")
            return redirect(url_for("me_page"))
    return render_template("plan.html", form=form, errors=errors, cities=CITIES)


@app.route("/trips/<int:trip_id>", methods=["GET", "POST"])
def trip_page(trip_id):
    row = db().execute(
        """
        SELECT t.*, u.name AS driver_name, u.photo, u.rating, u.trips_count, u.car, u.about, u.status AS driver_status
        FROM trips t JOIN users u ON u.id = t.driver_id
        WHERE t.id = ?
        """,
        (trip_id,),
    ).fetchone()
    if not row:
        return render_template("unavailable.html", kind="trip"), 404
    closed, badge, left, past = public_closed(row)
    me = current_user()
    is_driver = bool(me and me["id"] == row["driver_id"])
    passenger_any = None
    last_booking = None
    if me and not is_driver:
        passenger_any = db().execute(
            "SELECT id FROM bookings WHERE trip_id = ? AND passenger_id = ? LIMIT 1",
            (trip_id, me["id"]),
        ).fetchone()
        last_booking = db().execute(
            """
            SELECT * FROM bookings
            WHERE trip_id = ? AND passenger_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (trip_id, me["id"]),
        ).fetchone()
    hide_note = None
    if row["status"] == "hidden":
        hide_note = row["hide_reason"] or "Без пояснения."
    if closed and not is_driver and not (me and me["role"] == "admin"):
        allowed = bool(row["status"] == "cancelled" and passenger_any)
        if row["status"] == "hidden" and me:
            seat = db().execute(
                """
                SELECT id FROM bookings
                WHERE trip_id = ? AND passenger_id = ? AND status IN ('plan', 'confirmed')
                """,
                (trip_id, me["id"]),
            ).fetchone()
            allowed = bool(seat)
        if not allowed:
            return render_template("unavailable.html", kind="trip")
    booking = None
    if me and not is_driver:
        booking = db().execute(
            """
            SELECT * FROM bookings
            WHERE trip_id = ? AND passenger_id = ? AND status NOT IN ('rejected', 'cancelled')
            ORDER BY id DESC LIMIT 1
            """,
            (trip_id, me["id"]),
        ).fetchone()
    passengers = db().execute(
        """
        SELECT b.*, u.name FROM bookings b
        JOIN users u ON u.id = b.passenger_id
        WHERE b.trip_id = ? AND b.status IN ('clarify', 'plan', 'confirmed')
        ORDER BY b.id
        """,
        (trip_id,),
    ).fetchall()
    errors = {}
    if request.method == "POST":
        check_csrf()
        if g.expired:
            return redirect(url_for("login", next=request.path, expired=1))
        if not me:
            return redirect(url_for("login", next=request.path))
        action = request.form.get("action") or ""
        if not me["verified"] and action in ("request", "clarify", "plan_ok", "confirm", "complaint"):
            flash("Подтвердите почту, чтобы продолжить.")
            return redirect(url_for("me_page"))
        if action == "request":
            errors = apply_request(row, me, booking, left)
        elif action == "clarify" and booking and booking["passenger_id"] == me["id"]:
            errors = apply_clarify(booking)
        elif action == "agree" and is_driver:
            errors = apply_agree(row)
        elif action == "reject" and is_driver:
            errors = apply_reject(row)
        elif action == "plan_ok" and booking:
            mark_plan(booking, False)
        elif action == "plan_ok" and is_driver:
            mark_driver_plan(row)
        elif action == "confirm" and booking:
            errors = apply_confirm(row, booking)
        elif action == "cancel_booking" and booking and booking["passenger_id"] == me["id"]:
            cancel_booking(row, booking)
        elif action == "cancel_trip" and is_driver:
            cancel_trip(row)
        elif action == "complaint" and me["id"] != row["driver_id"]:
            body = (request.form.get("body") or "").strip()
            if rate_limit("complaint:" + str(me["id"]), 3, 86400):
                errors["complaint"] = "Не больше трёх жалоб в сутки. Повторите завтра."
            elif not body:
                errors["complaint"] = "Заполните поле"
            elif len(body) > FIELD_LIMITS["complaint"]:
                errors["complaint"] = "Не больше 2000 символов"
            else:
                db().execute(
                    """
                    INSERT INTO complaints (author_id, trip_id, body, status, staff_note, created_at)
                    VALUES (?, ?, ?, 'open', '', ?)
                    """,
                    (me["id"], trip_id, body, now_ts()),
                )
                db().commit()
                flash("Жалоба отправлена.")
        else:
            abort(403)
        if not errors:
            return redirect(url_for("trip_page", trip_id=trip_id))
        booking = db().execute(
            """
            SELECT * FROM bookings
            WHERE trip_id = ? AND passenger_id = ? AND status NOT IN ('rejected', 'cancelled')
            ORDER BY id DESC LIMIT 1
            """,
            (trip_id, me["id"]),
        ).fetchone() if me and not is_driver else booking
        if me and not is_driver:
            last_booking = db().execute(
                """
                SELECT * FROM bookings
                WHERE trip_id = ? AND passenger_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (trip_id, me["id"]),
            ).fetchone()
        row = db().execute(
            """
            SELECT t.*, u.name AS driver_name, u.photo, u.rating, u.trips_count, u.car, u.about, u.status AS driver_status
            FROM trips t JOIN users u ON u.id = t.driver_id WHERE t.id = ?
            """,
            (trip_id,),
        ).fetchone()
        closed, badge, left, past = public_closed(row)
    driver_bookings = []
    if is_driver or (me and me["role"] == "admin"):
        driver_bookings = db().execute(
            """
            SELECT b.*, u.name FROM bookings b
            JOIN users u ON u.id = b.passenger_id
            WHERE b.trip_id = ? ORDER BY b.id DESC
            """,
            (trip_id,),
        ).fetchall()
    can_review, review_targets = review_form_state(row, me)
    return render_template(
        "trip.html", trip=row, badge=badge, left=left, past=past,
        booking=booking, passengers=passengers, errors=errors,
        is_driver=is_driver, driver_bookings=driver_bookings,
        can_review=can_review, review_targets=review_targets,
        chat_with_driver=bool(passenger_any),
        last_booking=last_booking, hide_note=hide_note,
    )


def review_form_state(row, me):
    if not me or not row:
        return False, []
    try:
        finished = datetime.fromisoformat(row["depart_at"]) < datetime.now()
    except (TypeError, ValueError):
        return False, []
    if not finished:
        return False, []
    if me["id"] == row["driver_id"]:
        targets = db().execute(
            """
            SELECT u.id, u.name
            FROM bookings b
            JOIN users u ON u.id = b.passenger_id
            WHERE b.trip_id = ? AND b.status = 'confirmed'
              AND NOT EXISTS (
                SELECT 1 FROM reviews r
                WHERE r.trip_id = b.trip_id AND r.author_id = ? AND r.target_id = u.id
              )
            ORDER BY u.name
            """,
            (row["id"], me["id"]),
        ).fetchall()
        return bool(targets), targets
    confirmed = db().execute(
        """
        SELECT id FROM bookings
        WHERE trip_id = ? AND passenger_id = ? AND status = 'confirmed'
        """,
        (row["id"], me["id"]),
    ).fetchone()
    if not confirmed:
        return False, []
    already = db().execute(
        """
        SELECT id FROM reviews
        WHERE trip_id = ? AND author_id = ? AND target_id = ?
        """,
        (row["id"], me["id"], row["driver_id"]),
    ).fetchone()
    if already:
        return False, []
    return True, [{"id": row["driver_id"], "name": row["driver_name"]}]


@app.route("/trip/<int:trip_id>/review", methods=["POST"])
def trip_review(trip_id):
    me = current_user()
    if not me:
        abort(401)
    if not me["verified"]:
        flash("Подтвердите почту, чтобы оставить отзыв.")
        return redirect(url_for("me_page"))
    check_csrf()
    try:
        rating = int(request.form.get("rating") or "")
    except (TypeError, ValueError):
        rating = 0
    text = (request.form.get("text") or "").strip()
    if len(text) > REVIEW_TEXT_LIMIT:
        text = text[:REVIEW_TEXT_LIMIT]
    trip = db().execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
    if not trip:
        abort(404)
    back = url_for("trip_page", trip_id=trip_id)
    try:
        finished = datetime.fromisoformat(trip["depart_at"]) < datetime.now()
    except (TypeError, ValueError):
        finished = False
    if not finished:
        flash("Отзыв можно оставить после завершения поездки.")
        return redirect(back)
    if rating < 1 or rating > 5 or not text:
        flash("Укажите оценку от 1 до 5 и текст отзыва.")
        return redirect(back)
    is_driver = me["id"] == trip["driver_id"]
    if is_driver:
        try:
            target_id = int(request.form.get("target_id") or "")
        except (TypeError, ValueError):
            abort(400)
        if target_id == me["id"]:
            abort(403)
        passenger = db().execute(
            """
            SELECT id FROM bookings
            WHERE trip_id = ? AND passenger_id = ? AND status = 'confirmed'
            """,
            (trip_id, target_id),
        ).fetchone()
        if not passenger:
            abort(403)
    else:
        confirmed = db().execute(
            """
            SELECT id FROM bookings
            WHERE trip_id = ? AND passenger_id = ? AND status = 'confirmed'
            """,
            (trip_id, me["id"]),
        ).fetchone()
        if not confirmed:
            abort(403)
        target_id = trip["driver_id"]
    existing = db().execute(
        """
        SELECT id FROM reviews
        WHERE trip_id = ? AND author_id = ? AND target_id = ?
        """,
        (trip_id, me["id"], target_id),
    ).fetchone()
    if existing:
        flash("Отзыв по этой поездке уже оставлен.")
        return redirect(back)
    try:
        db().execute(
            """
            INSERT INTO reviews
            (trip_id, author_id, target_id, rating, text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (trip_id, me["id"], target_id, rating, text, now_ts()),
        )
        refresh_user_stats(target_id)
        db().commit()
    except sqlite3.IntegrityError:
        db().rollback()
        flash("Отзыв по этой поездке уже оставлен.")
        return redirect(back)
    except sqlite3.Error:
        db().rollback()
        flash("Не удалось сохранить отзыв.")
        return redirect(back)
    flash("Отзыв сохранён.")
    return redirect(back)


def apply_request(row, me, booking, left):
    if me["id"] == row["driver_id"]:
        return {"form": "Свою поездку забронировать нельзя."}
    if booking:
        return {}
    if row["status"] != "open" or datetime.fromisoformat(row["depart_at"]) < datetime.now():
        return {"form": "Поездка недоступна"}
    try:
        seats = int(request.form.get("seats") or "1")
    except ValueError:
        seats = 0
    fresh_left = row["seats_total"] - row["seats_taken"]
    if seats < 1 or seats > fresh_left or left < 1:
        return {"seats": "Столько мест уже нет" if fresh_left else "Мест не осталось"}
    try:
        db().execute(
            """
            INSERT INTO bookings
            (trip_id, passenger_id, seats, status, passenger_ok, driver_ok, created_at)
            VALUES (?, ?, ?, 'clarify', 0, 0, ?)
            """,
            (row["id"], me["id"], seats, now_ts()),
        )
        db().commit()
    except sqlite3.IntegrityError:
        db().rollback()
        return {"form": "Заявка уже отправлена. Обновите страницу."}
    flash("Заявка отправлена. Сейчас шаг «Уточнение».")
    return {}


def apply_clarify(booking):
    phone = normalize_phone(request.form.get("phone"))
    meeting = (request.form.get("meeting") or "").strip()
    luggage = (request.form.get("luggage") or "").strip()
    comment = (request.form.get("comment") or "").strip()
    errors = {}
    if not phone:
        errors["phone"] = "Введите телефон в формате +7 и 10 цифр. Без номера водитель не подтвердит посадку."
    if not meeting:
        errors["meeting"] = "Заполните поле"
    elif len(meeting) > FIELD_LIMITS["meeting"]:
        errors["meeting"] = "Не больше 200 символов"
    if len(luggage) > FIELD_LIMITS["luggage"]:
        errors["luggage"] = "Не больше 200 символов"
    if len(comment) > FIELD_LIMITS["comment"]:
        errors["comment"] = "Не больше 500 символов"
    if errors:
        return errors
    db().execute(
        """
        UPDATE bookings
        SET phone = ?, meeting = ?, luggage = ?, comment = ?, status = 'clarify'
        WHERE id = ? AND status = 'clarify'
        """,
        (phone, meeting, luggage, comment, booking["id"]),
    )
    db().commit()
    flash("Уточнение сохранено. Ждём ответ водителя.")
    return {}


def apply_agree(row):
    booking_id = request.form.get("booking_id")
    item = db().execute(
        "SELECT * FROM bookings WHERE id = ? AND trip_id = ? AND status = 'clarify'",
        (booking_id, row["id"]),
    ).fetchone()
    if not item or not item["phone"]:
        return {"form": "Пассажир ещё не заполнил уточнение."}
    db().execute(
        "UPDATE bookings SET status = 'plan', passenger_ok = 0, driver_ok = 0 WHERE id = ?",
        (item["id"],),
    )
    db().commit()
    return {}


def apply_reject(row):
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        return {"reason": "Укажите причину"}
    if len(reason) > FIELD_LIMITS["reason"]:
        return {"reason": "Не больше 500 символов"}
    item = db().execute(
        "SELECT * FROM bookings WHERE id = ? AND trip_id = ? AND status IN ('clarify', 'plan')",
        (request.form.get("booking_id"), row["id"]),
    ).fetchone()
    if not item:
        return {"form": "Заявка недоступна"}
    db().execute(
        "UPDATE bookings SET status = 'rejected', reject_reason = ? WHERE id = ?",
        (reason, item["id"]),
    )
    db().commit()
    return {}


def mark_plan(booking, _driver):
    if booking["status"] != "plan":
        abort(403)
    db().execute("UPDATE bookings SET passenger_ok = 1 WHERE id = ?", (booking["id"],))
    db().commit()


def mark_driver_plan(row):
    item = db().execute(
        "SELECT * FROM bookings WHERE id = ? AND trip_id = ? AND status = 'plan'",
        (request.form.get("booking_id"), row["id"]),
    ).fetchone()
    if not item:
        abort(403)
    db().execute("UPDATE bookings SET driver_ok = 1 WHERE id = ?", (item["id"],))
    db().commit()


def apply_confirm(row, booking):
    if booking["status"] != "plan" or not booking["passenger_ok"] or not booking["driver_ok"]:
        return {"form": "Сначала обе стороны отмечают план."}
    if row["status"] != "open":
        return {"form": "Поездка недоступна"}
    con = db()
    con.execute("BEGIN IMMEDIATE")
    fresh = con.execute("SELECT * FROM trips WHERE id = ?", (row["id"],)).fetchone()
    current = con.execute("SELECT * FROM bookings WHERE id = ?", (booking["id"],)).fetchone()
    if not current or current["status"] != "plan":
        con.rollback()
        return {"form": "Поездка недоступна"}
    if fresh["seats_taken"] + current["seats"] > fresh["seats_total"] or fresh["status"] != "open":
        con.rollback()
        return {"form": "Место уже занято"}
    con.execute(
        "UPDATE bookings SET status = 'confirmed' WHERE id = ?",
        (current["id"],),
    )
    con.execute(
        "UPDATE trips SET seats_taken = seats_taken + ? WHERE id = ?",
        (current["seats"], fresh["id"]),
    )
    con.commit()
    flash("Место подтверждено.")
    return {}


def cancel_booking(row, booking):
    if datetime.fromisoformat(row["depart_at"]) < datetime.now():
        flash("Поездка уже завершена.")
        return
    con = db()
    con.execute("BEGIN IMMEDIATE")
    current = con.execute("SELECT * FROM bookings WHERE id = ?", (booking["id"],)).fetchone()
    if not current or current["passenger_id"] != g.me["id"]:
        con.rollback()
        abort(403)
    if current["status"] == "confirmed":
        con.execute(
            "UPDATE trips SET seats_taken = MAX(seats_taken - ?, 0) WHERE id = ? AND status = 'open'",
            (current["seats"], row["id"]),
        )
    con.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (current["id"],))
    con.commit()
    flash("Заявка отменена.")


def cancel_trip(row):
    if datetime.fromisoformat(row["depart_at"]) < datetime.now():
        flash("Поездка уже завершена.")
        return
    con = db()
    con.execute("UPDATE trips SET status = 'cancelled', seats_taken = 0 WHERE id = ?", (row["id"],))
    con.execute(
        "UPDATE bookings SET status = 'cancelled' WHERE trip_id = ? AND status NOT IN ('rejected', 'cancelled')",
        (row["id"],),
    )
    refresh_user_stats(row["driver_id"])
    con.commit()
    flash("Поездка отменена.")


@app.route("/schedule")
def schedule():
    mode = request.args.get("mode") or "bus"
    if mode not in ("bus", "plane", "train"):
        mode = "bus"
    origin = (request.args.get("from") or "").strip()
    dest = (request.args.get("to") or "").strip()
    date_raw = request.args.get("date") or ""
    day, date_error = (None, None)
    if date_raw:
        day, date_error = parse_ride_date(date_raw)
    failed = request.args.get("failed") == "1"
    try:
        schedule_days = schedule_day_counts(mode, origin, dest)
    except Exception:
        schedule_days = []
    known = {item["date"] for item in schedule_days}
    date_value = ""
    if day and not date_error:
        date_value = day.isoformat()
    rows = []
    if not date_error and not failed and day:
        sql = "SELECT * FROM schedules WHERE mode = ? AND substr(depart_at, 1, 10) = ?"
        args = [mode, day.isoformat()]
        if origin in CITY_BY_NAME:
            sql += " AND origin = ?"
            args.append(origin)
        if dest in CITY_BY_NAME:
            sql += " AND destination = ?"
            args.append(dest)
        sql += " ORDER BY depart_at"
        try:
            rows = db().execute(sql, args).fetchall()
        except sqlite3.Error:
            rows = []
            failed = True
    neighbors = []
    if day and not rows and not failed:
        neighbors = db().execute(
            """
            SELECT DISTINCT substr(depart_at, 1, 10) AS day
            FROM schedules WHERE mode = ? AND substr(depart_at, 1, 10) > ?
            ORDER BY day LIMIT 3
            """,
            (mode, day.isoformat()),
        ).fetchall()
    return render_template(
        "schedule.html", rows=rows, mode=mode, origin=origin, dest=dest,
        date=date_value, date_error=date_error, failed=failed, neighbors=neighbors,
        schedule_days=schedule_days,
    )


@app.route("/route")
def route_page():
    origin, err1 = resolve_place(request.args.get("from"), request.args.get("from_lat"), request.args.get("from_lon"), True)
    dest, err2 = resolve_place(request.args.get("to"), request.args.get("to_lat"), request.args.get("to_lon"), False)
    error = err1 or err2
    if origin and dest and origin["name"] == dest["name"]:
        error = "Укажите разные точки"
    km = hours = None
    built = False
    if origin and dest and not error:
        straight = haversine(origin["lat"], origin["lon"], dest["lat"], dest["lon"])
        road = driving_km(origin["lat"], origin["lon"], dest["lat"], dest["lon"])
        km = round(road if road else straight * 1.25)
        hours = max(1, round(km / 70))
        built = False
    trips_near = []
    if origin and dest and not error:
        try:
            candidates = db().execute(
                """
                SELECT t.*, u.name AS driver_name FROM trips t
                JOIN users u ON u.id = t.driver_id
                WHERE t.status = 'open' AND t.depart_at >= ?
                ORDER BY t.depart_at LIMIT 50
                """,
                (datetime.now().strftime("%Y-%m-%dT%H:%M"),),
            ).fetchall()
        except sqlite3.Error:
            candidates = []

        def near(place, city_name):
            if place["name"] == city_name:
                return True
            city = CITY_BY_NAME.get(city_name)
            if not city or place["name"] != HERE:
                return False
            return haversine(place["lat"], place["lon"], city["lat"], city["lon"]) <= 50

        for item in candidates:
            if near(origin, item["origin"]) or near(dest, item["destination"]):
                trips_near.append(item)
            if len(trips_near) >= 5:
                break
    return render_template(
        "route.html", origin=origin, dest=dest, error=error, km=km, hours=hours,
        built=built, trips=trips_near,
        raw_from=request.args.get("from") or "", raw_to=request.args.get("to") or "",
    )


@app.route("/routes/save", methods=["POST"])
@require_user(verified=True)
def save_route():
    check_csrf()
    origin, err1 = resolve_place(request.form.get("from"), request.form.get("from_lat"), request.form.get("from_lon"), True)
    dest, err2 = resolve_place(request.form.get("to"), request.form.get("to_lat"), request.form.get("to_lon"), False)
    if err1 or err2 or not origin or not dest:
        flash(err1 or err2 or "Маршрут не построен. Проверьте точки или повторите позже.")
        return redirect(url_for("route_page"))
    db().execute(
        """
        INSERT INTO saved_routes
        (user_id, origin, destination, origin_lat, origin_lon, dest_lat, dest_lon, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (g.me["id"], origin["name"], dest["name"], origin["lat"], origin["lon"],
         dest["lat"], dest["lon"], now_ts()),
    )
    db().commit()
    flash("Маршрут сохранён в профиле.")
    return redirect(url_for("me_page"))


@app.route("/u/<int:user_id>")
def public_profile(user_id):
    person = db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not person or person["status"] == "blocked" or person["role"] == "admin":
        return render_template("unavailable.html", kind="profile")
    reviews = db().execute(
        """
        SELECT r.text, r.rating, r.created_at, u.name
        FROM reviews r
        JOIN users u ON u.id = r.author_id
        WHERE r.target_id = ?
          AND r.author_id != ?
        ORDER BY r.created_at DESC, r.id DESC
        """,
        (user_id, user_id),
    ).fetchall()
    upcoming = db().execute(
        """
        SELECT * FROM trips
        WHERE driver_id = ? AND status = 'open' AND depart_at >= ?
        ORDER BY depart_at
        """,
        (user_id, datetime.now().strftime("%Y-%m-%dT%H:%M")),
    ).fetchall()
    completed_trips = person["trips_count"] if person["trips_count"] is not None else None
    if completed_trips is None:
        past = db().execute(
            """
            SELECT COUNT(*) AS n FROM trips
            WHERE driver_id = ? AND depart_at < ? AND status != 'cancelled'
            """,
            (user_id, datetime.now().strftime("%Y-%m-%dT%H:%M")),
        ).fetchone()
        completed_trips = int(past["n"] or 0) if past else 0
    try:
        rating_value = float(person["rating"] or 0)
    except (TypeError, ValueError):
        rating_value = 0
    if rating_value < 0:
        rating_value = 0
    if rating_value > 5:
        rating_value = 5
    star_fill = int(rating_value + 0.5)
    if star_fill > 5:
        star_fill = 5
    return render_template(
        "profile.html", person=person, reviews=reviews, upcoming=upcoming,
        completed_trips=completed_trips, star_fill=star_fill,
    )


def offer_matches_trips(offer, trips):
    """Предложение видно водителю, если совпадает маршрут или точки рядом (до 50 км)."""
    for trip in trips:
        if offer["origin"] == trip["origin"] and offer["destination"] == trip["destination"]:
            return True
        origin = CITY_BY_NAME.get(offer["origin"])
        dest = CITY_BY_NAME.get(offer["destination"])
        trip_origin = CITY_BY_NAME.get(trip["origin"])
        trip_dest = CITY_BY_NAME.get(trip["destination"])
        if not (origin and dest and trip_origin and trip_dest):
            continue
        close_origin = (offer["origin"] == trip["origin"] or haversine(
            origin["lat"], origin["lon"], trip_origin["lat"], trip_origin["lon"]
        ) <= 50)
        close_dest = (offer["destination"] == trip["destination"] or haversine(
            dest["lat"], dest["lon"], trip_dest["lat"], trip_dest["lon"]
        ) <= 50)
        if close_origin and close_dest:
            return True
    return False


@app.route("/me", methods=["GET", "POST"])
@require_user()
def me_page():
    errors = {}
    if request.method == "POST":
        check_csrf()
        name = (request.form.get("name") or "").strip()
        city = (request.form.get("city") or "").strip()
        phone_raw = (request.form.get("phone") or "").strip()
        about = (request.form.get("about") or "").strip()
        car = (request.form.get("car") or "").strip()
        if not name:
            errors["name"] = "Введите имя"
        if city not in CITY_BY_NAME:
            errors["city"] = "Выберите город из списка ALONG"
        phone = ""
        if phone_raw:
            phone = normalize_phone(phone_raw) or ""
            if not phone:
                errors["phone"] = "Введите телефон в формате +7 и 10 цифр"
        if not errors:
            db().execute(
                "UPDATE users SET name = ?, city = ?, phone = ?, about = ?, car = ? WHERE id = ?",
                (name, city, phone, about, car, g.me["id"]),
            )
            db().commit()
            flash("Профиль сохранён.")
            return redirect(url_for("me_page"))
    mine = db().execute(
        "SELECT * FROM trips WHERE driver_id = ? ORDER BY depart_at DESC",
        (g.me["id"],),
    ).fetchall()
    bookings = db().execute(
        """
        SELECT b.*, t.origin, t.destination, t.depart_at, t.status AS trip_status
        FROM bookings b JOIN trips t ON t.id = b.trip_id
        WHERE b.passenger_id = ? ORDER BY b.id DESC
        """,
        (g.me["id"],),
    ).fetchall()
    routes = db().execute(
        "SELECT * FROM saved_routes WHERE user_id = ? ORDER BY id DESC",
        (g.me["id"],),
    ).fetchall()
    complaints = db().execute(
        "SELECT id, status, body FROM complaints WHERE author_id = ? ORDER BY id DESC",
        (g.me["id"],),
    ).fetchall()
    try:
        if (g.me["driver_status"] or "") == "approved":
            offers = db().execute(
                """
                SELECT o.id, o.passenger_id, o.origin, o.destination,
                       o.offer_price, o.created_at, u.name AS passenger_name
                FROM custom_offers o
                JOIN users u ON u.id = o.passenger_id
                ORDER BY o.id DESC
                """
            ).fetchall()
            offers = [item for item in offers if offer_matches_trips(item, mine)]
        else:
            offers = db().execute(
                """
                SELECT o.id, o.passenger_id, o.origin, o.destination,
                       o.offer_price, o.created_at, u.name AS passenger_name
                FROM custom_offers o
                JOIN users u ON u.id = o.passenger_id
                WHERE o.passenger_id = ?
                ORDER BY o.id DESC
                """,
                (g.me["id"],),
            ).fetchall()
    except sqlite3.Error:
        offers = []
    return render_template(
        "me.html", errors=errors, mine=mine, bookings=bookings, routes=routes,
        complaints=complaints, cities=CITIES, offers=offers,
        form_name=request.form.get("name") or g.me["name"],
        form_city=request.form.get("city") or (g.me["city"] or ""),
        form_phone=request.form.get("phone") if request.method == "POST" else (g.me["phone"] or ""),
        form_about=request.form.get("about") if request.method == "POST" else (g.me["about"] or ""),
        form_car=request.form.get("car") if request.method == "POST" else (g.me["car"] or ""),
        resign_sent=request.args.get("resign") == "sent",
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    errors = {}
    email = ""
    nxt = safe_next(request.args.get("next") or request.form.get("next"))
    expired = request.args.get("expired") == "1"
    if request.method == "POST":
        check_csrf()
        if rate_limit(client_key("login"), 60, 600):
            errors["form"] = "Слишком много попыток входа. Подождите немного."
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        if not email:
            errors["email"] = "Введите почту"
        elif not EMAIL_RE.match(email):
            errors["email"] = "Напишите почту целиком, например name@example.com"
        if len(password) < 8:
            errors["password"] = "Не меньше 8 символов"
        if not errors:
            clean_login_attempts()
            recent = db().execute(
                "SELECT COUNT(*) AS n FROM login_attempts WHERE email = ? AND created_at > ?",
                (email.lower(), now_ts() - 600),
            ).fetchone()["n"]
            if recent >= 5:
                errors["form"] = "Слишком много попыток. Попробуйте позже."
            else:
                user = db().execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
                if not user or not check_password(password, user["password_hash"]):
                    db().execute(
                        "INSERT INTO login_attempts (email, created_at) VALUES (?, ?)",
                        (email.lower(), now_ts()),
                    )
                    db().commit()
                    errors["form"] = "Неверная почта или пароль"
                elif user["status"] == "blocked":
                    errors["form"] = "Вход недоступен. Напишите в поддержку."
                elif user["status"] == "review":
                    errors["form"] = "Ваш аккаунт на проверке. Ожидайте решения администратора."
                else:
                    token = secrets.token_urlsafe(32)
                    db().execute(
                        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                        (hash_token(token), user["id"], now_ts() + SESSION_SECONDS),
                    )
                    db().execute(
                        """
                        DELETE FROM sessions WHERE user_id = ? AND token NOT IN (
                            SELECT token FROM sessions WHERE user_id = ?
                            ORDER BY expires_at DESC LIMIT 10
                        )
                        """,
                        (user["id"], user["id"]),
                    )
                    db().commit()
                    posted_next = (request.form.get("next") or "").strip()
                    target = nxt
                    if user["role"] == "admin" and posted_next in ("", "/"):
                        target = url_for("admin_home")
                    response = redirect(target)
                    response.set_cookie("along_sid", token, httponly=True, samesite="Lax", secure=SECURE_COOKIES, max_age=SESSION_SECONDS)
                    return response
    return render_template("auth.html", mode="login", errors=errors, email=email, nxt=nxt, expired=expired)


@app.route("/register", methods=["GET", "POST"])
def register():
    errors = {}
    form = {"name": "", "email": "", "city": "", "account_kind": "passenger"}
    nxt = safe_next(request.args.get("next") or request.form.get("next"))
    if request.method == "POST":
        check_csrf()
        if rate_limit(client_key("register"), 20, 3600):
            flash("Слишком много регистраций с этого адреса. Попробуйте позже.")
            return redirect(url_for("register"))
        form["name"] = (request.form.get("name") or "").strip()
        form["email"] = (request.form.get("email") or "").strip().lower()
        form["city"] = (request.form.get("city") or "").strip()
        kind = (request.form.get("account_kind") or "").strip()
        if kind not in ("passenger", "driver"):
            errors["account_kind"] = "Выберите: пассажир или водитель"
            kind = "passenger"
        form["account_kind"] = kind
        password = request.form.get("password") or ""
        if not form["name"]:
            errors["name"] = "Введите имя"
        if not form["email"]:
            errors["email"] = "Введите почту"
        elif not EMAIL_RE.match(form["email"]):
            errors["email"] = "Напишите почту целиком, например name@example.com"
        if len(password) < 8:
            errors["password"] = "Не меньше 8 символов"
        if form["city"] and form["city"] not in CITY_BY_NAME:
            errors["city"] = "Выберите город из списка ALONG"
        if not errors:
            exists = db().execute("SELECT id FROM users WHERE email = ?", (form["email"],)).fetchone()
            if exists:
                errors["email"] = "Эта почта уже зарегистрирована. Войдите или укажите другую."
            else:
                token = secrets.token_urlsafe(24)
                driver_status = "pending" if form["account_kind"] == "driver" else "none"
                db().execute(
                    """
                    INSERT INTO users
                    (name, email, password_hash, role, city, phone, about, car, photo, rating,
                     trips_count, status, verified, verify_token, verify_sent, created_at, driver_status)
                    VALUES (?, ?, ?, 'user', ?, '', '', '', 'darya.jpg', 5, 0, 'active', 0, ?, ?, ?, ?)
                    """,
                    (form["name"], form["email"], hash_password(password), form["city"],
                     hash_token(token), now_ts(), now_ts(), driver_status),
                )
                db().commit()
                session["pending_email"] = form["email"]
                link = verify_link(token, nxt)
                sent, reason = send_mail(
                    form["email"],
                    "ALONG: подтвердите почту",
                    "Здравствуйте, %s!\n\nПодтвердите почту по ссылке:\n%s\n\n"
                    "Если вы не регистрировались, просто проигнорируйте письмо."
                    % (form["name"], link),
                )
                if sent:
                    session.pop("pending_verify", None)
                    flash("Аккаунт создан. Письмо со ссылкой отправлено на %s." % form["email"])
                else:
                    session["pending_verify"] = token
                    if reason == "smtp":
                        log.info("Демо-режим почты: письмо для %s, ссылка %s", form["email"], link)
                        flash("Аккаунт создан. Демо-режим: письмо не отправлено, ссылка показана на странице.")
                    else:
                        log.warning("Письмо не отправлено (%s)", reason)
                        flash("Аккаунт создан, но письмо не ушло. Откройте ссылку на странице подтверждения.")
                return redirect(url_for("verify_wait", next=nxt))
    return render_template("auth.html", mode="register", errors=errors, form=form, nxt=nxt, cities=CITIES)


@app.route("/verify")
def verify_wait():
    email = session.get("pending_email")
    token = session.get("pending_verify") or ""
    if email and token:
        user = db().execute(
            "SELECT id FROM users WHERE email = ? AND verify_token = ?",
            (email, hash_token(token)),
        ).fetchone()
        if not user:
            token = ""
    elif not email:
        token = ""
    smtp_on = smtp_configured()
    if smtp_on:
        token = ""
    return render_template(
        "verify.html", email=email, token=token,
        nxt=request.args.get("next") or "", smtp_on=smtp_on,
    )


@app.route("/verify/resend", methods=["POST"])
def verify_resend():
    check_csrf()
    email = session.get("pending_email")
    user = db().execute("SELECT * FROM users WHERE email = ?", (email or "",)).fetchone() if email else None
    if not user:
        flash("Не удалось выполнить действие. Повторите позже.")
        return redirect(url_for("register"))
    if user["verify_sent"] and now_ts() - user["verify_sent"] < 60:
        flash("Подождите минуту и отправьте снова.")
        return redirect(url_for("verify_wait"))
    token = secrets.token_urlsafe(24)
    db().execute(
        "UPDATE users SET verify_token = ?, verify_sent = ? WHERE id = ?",
        (hash_token(token), now_ts(), user["id"]),
    )
    db().commit()
    link = verify_link(token)
    sent, reason = send_mail(
        user["email"],
        "ALONG: подтвердите почту",
        "Подтвердите почту по ссылке:\n%s" % link,
    )
    if sent:
        session.pop("pending_verify", None)
        flash("Ссылка обновлена. Письмо отправлено на %s." % user["email"])
    else:
        session["pending_verify"] = token
        if reason == "smtp":
            log.info("Демо-режим почты: повторная ссылка для %s: %s", user["email"], link)
            flash("Ссылка обновлена. Демо-режим: письмо не отправлено.")
        else:
            flash("Ссылка обновлена, но письмо не ушло.")
    return redirect(url_for("verify_wait"))


@app.route("/verify/<token>")
def verify_token(token):
    user = db().execute(
        "SELECT * FROM users WHERE verify_token = ?",
        (hash_token(token),),
    ).fetchone()
    if not user:
        flash("Ссылка недействительна.")
        return redirect(url_for("login"))
    db().execute("UPDATE users SET verified = 1, verify_token = NULL WHERE id = ?", (user["id"],))
    db().commit()
    session.pop("pending_verify", None)
    session.pop("pending_email", None)
    flash("Почта подтверждена. Войдите, чтобы продолжить.")
    nxt = (request.args.get("next") or "").strip()
    target = url_for("login", next=nxt) if nxt else url_for("login")
    return redirect(target)


@app.route("/password/forgot", methods=["GET", "POST"])
def password_forgot():
    errors = {}
    email = ""
    sent = request.args.get("sent") == "1"
    demo_link = session.pop("reset_demo_link", "")
    if request.method == "POST":
        check_csrf()
        if rate_limit(client_key("forgot"), 10, 3600):
            errors["form"] = "Слишком много запросов. Попробуйте через час."
        email = (request.form.get("email") or "").strip().lower()
        if not email:
            errors["email"] = "Введите почту"
        elif not EMAIL_RE.match(email):
            errors["email"] = "Напишите почту целиком, например name@example.com"
        if not errors:
            user = db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if user and user["status"] != "blocked":
                nxt = safe_next(request.args.get("next") or request.form.get("next"))
                link, delivered, reason = demo_password_link(
                    user, nxt if nxt != url_for("home") else ""
                )
                if delivered:
                    flash("Ссылка отправлена на %s." % user["email"])
                else:
                    session["reset_demo_link"] = link
                    if reason == "smtp":
                        log.info("Демо-режим почты: восстановление для %s: %s", user["email"], link)
                        flash("Демо-режим: письмо не отправлено, ссылка показана на странице.")
                    else:
                        flash("Письмо не ушло. Ссылка показана на странице.")
            else:
                flash("Если почта зарегистрирована, ссылка отправлена.")
            return redirect(url_for("password_forgot", sent=1))
    return render_template(
        "password.html", mode="forgot", errors=errors, email=email,
        sent=sent, demo_link=demo_link,
    )


@app.route("/password/reset/<token>", methods=["GET", "POST"])
def password_reset(token):
    user = password_reset_target(token)
    if not user:
        return render_template(
            "password.html", mode="invalid", errors={}, email="",
            sent=False, demo_link="",
        ), 400
    errors = {}
    if request.method == "POST":
        check_csrf()
        if rate_limit(client_key("reset"), 10, 3600):
            errors["form"] = "Слишком много попыток. Попробуйте позже."
        password = request.form.get("password") or ""
        repeat = request.form.get("repeat") or ""
        problem = password_problem(password, repeat)
        if problem:
            errors["password"] = problem
        if not errors:
            reset_password(user, password)
            flash("Пароль изменён. Войдите с новым паролем.")
            return redirect(url_for("login"))
    return render_template(
        "password.html", mode="reset", errors=errors, email=user["email"],
        sent=False, demo_link="",
    )


@app.route("/me/password", methods=["POST"])
@require_user()
def me_password():
    check_csrf()
    if rate_limit("password:" + str(g.me["id"]), 10, 3600):
        flash("Слишком много попыток. Попробуйте через час.")
        return redirect(url_for("me_page"))
    current = request.form.get("current_password") or ""
    password = request.form.get("password") or ""
    repeat = request.form.get("repeat") or ""
    if not check_password(current, g.me["password_hash"]):
        flash("Текущий пароль не совпадает.")
        return redirect(url_for("me_page"))
    problem = password_problem(password, repeat)
    if not problem and check_password(password, g.me["password_hash"]):
        problem = "Новый пароль совпадает с текущим"
    if problem:
        flash(problem)
        return redirect(url_for("me_page"))
    db().execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(password), g.me["id"]),
    )
    token = request.cookies.get("along_sid")
    if token:
        db().execute(
            "DELETE FROM sessions WHERE user_id = ? AND token != ?",
            (g.me["id"], hash_token(token)),
        )
    db().commit()
    flash("Пароль изменён. Остальные сеансы завершены.")
    return redirect(url_for("me_page"))


@app.route("/logout/all", methods=["POST"])
@require_user()
def logout_all():
    check_csrf()
    db().execute("DELETE FROM sessions WHERE user_id = ?", (g.me["id"],))
    db().commit()
    session.clear()
    flash("Все сеансы завершены. Войдите снова.")
    response = redirect(url_for("home"))
    response.delete_cookie("along_sid", httponly=True, samesite="Lax", secure=SECURE_COOKIES)
    return response


@app.route("/logout", methods=["POST"])
def logout():
    check_csrf()
    token = request.cookies.get("along_sid")
    if token:
        db().execute("DELETE FROM sessions WHERE token = ?", (hash_token(token),))
        db().commit()
    response = redirect(url_for("home"))
    response.delete_cookie("along_sid", httponly=True, samesite="Lax", secure=SECURE_COOKIES)
    return response


@app.route("/admin")
@require_admin
def admin_home():
    since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")
    stats = {
        "trips": db().execute("SELECT COUNT(*) AS n FROM trips WHERE depart_at >= ?", (since,)).fetchone()["n"],
        "clarify": db().execute("SELECT COUNT(*) AS n FROM bookings WHERE status = 'clarify'").fetchone()["n"],
        "users": db().execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"],
        "complaints": db().execute("SELECT COUNT(*) AS n FROM complaints WHERE status = 'open'").fetchone()["n"],
    }
    today = datetime.now().date()
    start_ts = datetime.combine(today - timedelta(days=6), datetime.min.time()).timestamp()
    grouped = db().execute(
        """
        SELECT date(created_at, 'unixepoch', 'localtime') AS day, COUNT(*) AS n
        FROM trips
        WHERE created_at >= ?
        GROUP BY day
        """,
        (start_ts,),
    ).fetchall()
    by_day = {row["day"]: row["n"] for row in grouped}
    chart = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        key = day.isoformat()
        chart.append({
            "day": key,
            "label": day.strftime("%d.%m"),
            "count": int(by_day.get(key, 0)),
        })
    chart_max = max((item["count"] for item in chart), default=0)
    return render_template("admin_home.html", stats=stats, chart=chart, chart_max=chart_max)


@app.route("/admin/trips")
@require_admin
def admin_trips():
    status = request.args.get("status") or ""
    sql = """
        SELECT t.*, u.name AS driver_name
        FROM trips t JOIN users u ON u.id = t.driver_id
        WHERE 1 = 1
    """
    args = []
    if status:
        sql += " AND t.status = ?"
        args.append(status)
    sql += " ORDER BY t.depart_at DESC"
    rows, page, pages, total = paginate_query(sql, args)
    return render_template(
        "admin_trips.html", rows=rows, status=status, page=page, pages=pages, total=total
    )


@app.route("/admin/trips/export")
@require_admin
def admin_trips_export():
    status = request.args.get("status") or ""
    sql = """
        SELECT t.id, t.depart_at, t.origin, t.destination, u.name AS driver_name,
               t.price, t.seats_total, t.seats_taken, t.status
        FROM trips t
        JOIN users u ON u.id = t.driver_id
        WHERE 1 = 1
    """
    args = []
    if status in ("open", "hidden", "cancelled"):
        sql += " AND t.status = ?"
        args.append(status)
    sql += " ORDER BY t.depart_at DESC"
    rows = db().execute(sql, args).fetchall()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "id", "depart_at", "origin", "destination", "driver",
        "price", "seats_total", "seats_taken", "status",
    ])
    for row in rows:
        writer.writerow([
            csv_cell(row["id"]), csv_cell(row["depart_at"]), csv_cell(row["origin"]),
            csv_cell(row["destination"]), csv_cell(row["driver_name"]),
            csv_cell(row["price"]), csv_cell(row["seats_total"]),
            csv_cell(row["seats_taken"]), csv_cell(row["status"]),
        ])
    payload = buffer.getvalue().encode("utf-8-sig")
    return Response(
        payload,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=trips.csv"},
    )


@app.route("/admin/trips/new", methods=["GET", "POST"])
@require_admin
def admin_trip_new():
    return admin_trip_form(None)


@app.route("/admin/trips/<int:trip_id>", methods=["GET", "POST"])
@require_admin
def admin_trip_edit(trip_id):
    return admin_trip_form(trip_id)


def admin_trip_form(trip_id):
    trip = None
    confirmed_seats = 0
    if trip_id:
        trip = db().execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
        if not trip:
            abort(404)
        confirmed_seats = db().execute(
            "SELECT COALESCE(SUM(seats), 0) AS n FROM bookings WHERE trip_id = ? AND status = 'confirmed'",
            (trip_id,),
        ).fetchone()["n"]
    drivers = db().execute(
        "SELECT id, name, status FROM users WHERE status = 'active' ORDER BY name"
    ).fetchall()
    errors = {}
    form = {
        "from": trip["origin"] if trip else "",
        "to": trip["destination"] if trip else "",
        "date": trip["depart_at"][:10] if trip else "",
        "time": trip["depart_at"][11:16] if trip else "08:00",
        "price": str(trip["price"]) if trip else "",
        "seats": str(trip["seats_total"]) if trip else "1",
        "pickup": trip["pickup"] if trip else "",
        "driver_id": str(trip["driver_id"]) if trip else "",
        "reason": "",
    }
    if request.method == "POST":
        check_csrf()
        action = request.form.get("action") or "save"
        for key in form:
            if key in request.form:
                form[key] = request.form.get(key) or ""
        if action == "hide" and trip:
            if not form["reason"].strip():
                errors["reason"] = "Укажите причину"
            elif trip["status"] == "hidden":
                flash("Поездка уже скрыта.")
            else:
                db().execute(
                    "UPDATE trips SET status = 'hidden', hide_reason = ? WHERE id = ?",
                    (form["reason"].strip(), trip["id"]),
                )
                log_admin("hide", "trip", trip["id"], form["reason"].strip())
                db().commit()
                flash("Поездка скрыта.")
                return redirect(url_for("admin_trips"))
        elif action == "restore" and trip and trip["status"] == "hidden":
            db().execute("UPDATE trips SET status = 'open', hide_reason = '' WHERE id = ?", (trip["id"],))
            log_admin("restore", "trip", trip["id"])
            db().commit()
            flash("Поездка снова в поиске.")
            return redirect(url_for("admin_trip_edit", trip_id=trip["id"]))
        else:
            origin, err1 = resolve_place(form["from"], None, None, False)
            dest, err2 = resolve_place(form["to"], None, None, False)
            if err1:
                errors["from"] = err1
            if err2:
                errors["to"] = err2
            if origin and dest and origin["name"] == dest["name"]:
                errors["to"] = "Укажите разные точки"
            day, date_err = parse_ride_date(form["date"])
            if date_err:
                errors["date"] = date_err
            try:
                price = int(form["price"])
                if price <= 0:
                    raise ValueError
            except ValueError:
                errors["price"] = "Укажите цену числом, больше нуля"
                price = 0
            try:
                seats = int(form["seats"])
                if seats < 1 or seats > 6:
                    raise ValueError
            except ValueError:
                errors["seats"] = "Укажите хотя бы одно место"
                seats = 0
            if trip and seats and seats < trip["seats_taken"]:
                errors["seats"] = "Нельзя поставить меньше мест, чем уже подтверждено"
            driver = db().execute("SELECT * FROM users WHERE id = ?", (form["driver_id"],)).fetchone()
            if not driver or driver["status"] != "active":
                errors["driver"] = "Выберите активного водителя"
            try:
                hour, minute = [int(part) for part in form["time"].split(":", 1)]
            except ValueError:
                errors["time"] = "Укажите будущее время"
                hour = minute = 0
            depart = None
            if day and "time" not in errors:
                depart = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
                if depart <= datetime.now():
                    errors["time"] = "Укажите будущее время"
            if trip and datetime.fromisoformat(trip["depart_at"]) < datetime.now() and trip["status"] == "open":
                errors["form"] = "Поездка завершена. Правка маршрута недоступна."
            changed_plan = False
            reconcile = request.form.get("reconcile") == "1"
            if trip and depart and not errors:
                changed_plan = (
                    trip["depart_at"] != depart.strftime("%Y-%m-%dT%H:%M")
                    or trip["pickup"] != form["pickup"].strip()
                )
            if changed_plan and confirmed_seats and not reconcile:
                errors["form"] = (
                    "В поездке {} подтверждённых мест. Отметьте «Пересогласовать брони», "
                    "чтобы вернуть их на шаг «Уточнение», иначе брони останутся как есть.".format(confirmed_seats)
                )
            if not errors and origin and dest and depart and driver:
                if trip:
                    db().execute(
                        """
                        UPDATE trips SET driver_id=?, origin=?, destination=?, origin_lat=?, origin_lon=?,
                        dest_lat=?, dest_lon=?, depart_at=?, price=?, seats_total=?, pickup=?
                        WHERE id=?
                        """,
                        (driver["id"], origin["name"], dest["name"], origin["lat"], origin["lon"],
                         dest["lat"], dest["lon"], depart.strftime("%Y-%m-%dT%H:%M"), price, seats,
                         form["pickup"].strip(), trip["id"]),
                    )
                    if changed_plan and reconcile:
                        db().execute(
                            """
                            UPDATE bookings SET status='clarify', passenger_ok=0, driver_ok=0
                            WHERE trip_id=? AND status IN ('plan', 'confirmed')
                            """,
                            (trip["id"],),
                        )
                        db().execute(
                            "UPDATE trips SET seats_taken = MAX(seats_taken - ?, 0) WHERE id = ?",
                            (confirmed_seats, trip["id"]),
                        )
                    elif changed_plan:
                        db().execute(
                            "UPDATE bookings SET passenger_ok=0, driver_ok=0 WHERE trip_id=? AND status='plan'",
                            (trip["id"],),
                        )
                else:
                    created = db().execute(
                        """
                        INSERT INTO trips
                        (driver_id, origin, destination, origin_lat, origin_lon, dest_lat, dest_lon,
                         depart_at, price, seats_total, seats_taken, pickup, dropoff, luggage, comment,
                         status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, '', '', '', 'open', ?)
                        """,
                        (driver["id"], origin["name"], dest["name"], origin["lat"], origin["lon"],
                         dest["lat"], dest["lon"], depart.strftime("%Y-%m-%dT%H:%M"), price, seats,
                         form["pickup"].strip(), now_ts()),
                    )
                    log_admin("create", "trip", created.lastrowid)
                    refresh_user_stats(driver["id"])
                if trip:
                    log_admin("save", "trip", trip["id"])
                db().commit()
                flash("Поездка сохранена.")
                return redirect(url_for("admin_trips"))
    return render_template("admin_trip_form.html", trip=trip, form=form, errors=errors, drivers=drivers, cities=CITIES, confirmed_seats=confirmed_seats)


@app.route("/admin/users")
@require_admin
def admin_users():
    rows, page, pages, total = paginate_query(
        """
        SELECT id, name, city, rating, trips_count, status, role, driver_status
        FROM users ORDER BY id
        """,
        [],
    )
    resignations = db().execute(
        """
        SELECT r.id, r.user_id, r.full_name, r.email, r.reason, r.status, r.created_at,
               u.name AS user_name
        FROM driver_resignations r
        JOIN users u ON u.id = r.user_id
        ORDER BY r.id DESC
        """
    ).fetchall()
    return render_template(
        "admin_users.html", rows=rows, resignations=resignations,
        page=page, pages=pages, total=total,
    )


@app.route("/admin/users/<int:user_id>/driver", methods=["POST"])
@require_admin
def admin_driver_review(user_id):
    check_csrf()
    action = request.form.get("action") or ""
    if action not in ("approve", "reject"):
        abort(403)
    person = db().execute(
        "SELECT id, role, driver_status FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not person:
        abort(404)
    if person["driver_status"] != "pending":
        abort(403)
    new_status = "approved" if action == "approve" else "rejected"
    try:
        db().execute(
            "UPDATE users SET driver_status = ? WHERE id = ? AND driver_status = 'pending'",
            (new_status, person["id"]),
        )
        log_admin("driver-" + action, "user", person["id"], new_status)
        db().commit()
    except sqlite3.Error:
        db().rollback()
        flash("Не удалось обновить статус водителя.")
        return redirect(url_for("admin_users"))
    flash("Статус водителя обновлён.")
    return redirect(url_for("admin_users"))


@app.route("/admin/resignations/<int:item_id>", methods=["POST"])
@require_admin
def admin_resignation(item_id):
    check_csrf()
    action = request.form.get("action") or ""
    if action not in ("approve", "reject"):
        abort(403)
    item = db().execute(
        "SELECT id, user_id, status FROM driver_resignations WHERE id = ?",
        (item_id,),
    ).fetchone()
    if not item or item["status"] != "pending":
        abort(404)
    try:
        if action == "approve":
            db().execute(
                "UPDATE driver_resignations SET status = 'approved' WHERE id = ? AND status = 'pending'",
                (item["id"],),
            )
            db().execute(
                "UPDATE users SET driver_status = 'none' WHERE id = ?",
                (item["user_id"],),
            )
        else:
            db().execute(
                "UPDATE driver_resignations SET status = 'rejected' WHERE id = ? AND status = 'pending'",
                (item["id"],),
            )
            db().execute(
                "UPDATE users SET driver_status = 'approved' WHERE id = ?",
                (item["user_id"],),
            )
        log_admin("resignation-" + action, "user", item["user_id"])
        db().commit()
    except sqlite3.Error:
        db().rollback()
        flash("Не удалось обновить заявку.")
        return redirect(url_for("admin_users"))
    flash("Заявка на отказ обновлена.")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>", methods=["GET", "POST"])
@require_admin
def admin_user(user_id):
    person = db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not person:
        abort(404)
    errors = {}
    if request.method == "POST":
        check_csrf()
        role = request.form.get("role") or ""
        status = request.form.get("status") or ""
        if role not in ("user", "admin"):
            errors["role"] = "Выберите роль"
        if status not in ("active", "review", "blocked"):
            errors["status"] = "Выберите статус"
        if not errors:
            if person["id"] == g.me["id"] and status == "blocked":
                errors["status"] = "Нельзя заблокировать свою учётную запись"
            if role != "admin" and person["role"] == "admin":
                admins = db().execute("SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND status != 'blocked'").fetchone()["n"]
                if admins <= 1:
                    errors["role"] = "Нужен хотя бы один администратор"
            if not errors:
                db().execute(
                    "UPDATE users SET role = ?, status = ? WHERE id = ?",
                    (role, status, person["id"]),
                )
                if status == "blocked" or (person["role"] == "admin" and role != "admin"):
                    db().execute("DELETE FROM sessions WHERE user_id = ?", (person["id"],))
                log_admin(
                    "user-update", "user", person["id"],
                    "роль: %s, статус: %s" % (role, status),
                )
                db().commit()
                flash("Пользователь обновлён.")
                return redirect(url_for("admin_users"))
    return render_template("admin_user.html", person=person, errors=errors)


@app.route("/admin/complaints")
@require_admin
def admin_complaints():
    status = request.args.get("status") or ""
    if status not in ("open", "done"):
        status = ""
    sql = """
        SELECT c.*, u.name AS author_name, t.origin, t.destination, t.status AS trip_status
        FROM complaints c
        JOIN users u ON u.id = c.author_id
        LEFT JOIN trips t ON t.id = c.trip_id
        WHERE 1 = 1
    """
    args = []
    if status:
        sql += " AND c.status = ?"
        args.append(status)
    sql += " ORDER BY c.id DESC"
    rows, page, pages, total = paginate_query(sql, args)
    return render_template(
        "admin_complaints.html", rows=rows, page=page, pages=pages, total=total,
        status=status,
    )


@app.route("/admin/complaints/<int:complaint_id>", methods=["POST"])
@require_admin
def admin_complaint_close(complaint_id):
    check_csrf()
    note = (request.form.get("staff_note") or "").strip()
    trip_action = request.form.get("trip_action") or "none"
    trip_reason = (request.form.get("trip_reason") or "").strip()
    item = db().execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,)).fetchone()
    if not item:
        abort(404)
    if item["status"] != "open":
        flash("Жалоба уже разобрана. Пометка не перезаписывается.")
        return redirect(url_for("admin_complaints"))
    if not note:
        flash("Напишите, чем закончилась проверка.")
        return redirect(url_for("admin_complaints"))
    if len(note) > FIELD_LIMITS["staff_note"]:
        flash("Пометка не длиннее 500 символов.")
        return redirect(url_for("admin_complaints"))
    if trip_action not in ("none", "hide", "restore"):
        flash("Неизвестное действие с поездкой.")
        return redirect(url_for("admin_complaints"))
    trip = None
    if trip_action != "none":
        if not item["trip_id"]:
            flash("У жалобы нет поездки — действие с поездкой недоступно.")
            return redirect(url_for("admin_complaints"))
        trip = db().execute("SELECT * FROM trips WHERE id = ?", (item["trip_id"],)).fetchone()
        if not trip:
            flash("Поездка уже удалена.")
            return redirect(url_for("admin_complaints"))
        if trip_action == "hide" and not (trip_reason or note):
            flash("Укажите причину скрытия поездки.")
            return redirect(url_for("admin_complaints"))
    db().execute(
        "UPDATE complaints SET status = 'done', staff_note = ? WHERE id = ? AND status = 'open'",
        (note, complaint_id),
    )
    if trip_action == "hide":
        reason = (trip_reason or note)[:FIELD_LIMITS["reason"]]
        db().execute(
            "UPDATE trips SET status = 'hidden', hide_reason = ? WHERE id = ?",
            (reason, trip["id"]),
        )
        log_admin("hide", "trip", trip["id"], reason)
    elif trip_action == "restore":
        db().execute(
            "UPDATE trips SET status = 'open', hide_reason = '' WHERE id = ?",
            (trip["id"],),
        )
        log_admin("restore", "trip", trip["id"], "по жалобе")
    log_admin("complaint-close", "complaint", complaint_id, note)
    db().commit()
    if trip_action == "hide":
        flash("Жалоба разобрана, поездка скрыта.")
    elif trip_action == "restore":
        flash("Жалоба разобрана, поездка снова в поиске.")
    else:
        flash("Жалоба разобрана.")
    return redirect(url_for("admin_complaints", status=request.args.get("status") or None))


@app.route("/admin/schedules")
@require_admin
def admin_schedules():
    mode = request.args.get("mode") or ""
    sql = """
        SELECT id, mode, origin, destination, depart_at, title, sold_out,
               via, layover_min, leg2_at
        FROM schedules
        WHERE 1 = 1
    """
    args = []
    if mode in ("bus", "plane", "train"):
        sql += " AND mode = ?"
        args.append(mode)
    else:
        mode = ""
    sql += " ORDER BY depart_at DESC"
    rows, page, pages, total = paginate_query(sql, args)
    return render_template(
        "admin_schedules.html", rows=rows, mode=mode,
        page=page, pages=pages, total=total,
    )


@app.route("/admin/schedules/new", methods=["GET", "POST"])
@require_admin
def admin_schedule_new():
    return admin_schedule_form(None)


@app.route("/admin/schedules/<int:item_id>", methods=["GET", "POST"])
@require_admin
def admin_schedule_edit(item_id):
    return admin_schedule_form(item_id)


def admin_schedule_form(item_id):
    item = None
    if item_id:
        item = db().execute("SELECT * FROM schedules WHERE id = ?", (item_id,)).fetchone()
        if not item:
            abort(404)
    errors = {}
    form = {
        "mode": item["mode"] if item else "bus",
        "from": item["origin"] if item else "",
        "to": item["destination"] if item else "",
        "date": item["depart_at"][:10] if item else "",
        "time": item["depart_at"][11:16] if item else "08:00",
        "title": item["title"] if item else "",
        "sold_out": "1" if item and item["sold_out"] else "",
        "via": (item["via"] or "") if item else "",
        "leg2_time": (item["leg2_at"] or "")[11:16] if item and item["leg2_at"] else "",
    }
    if request.method == "POST":
        check_csrf()
        for key in form:
            if key in request.form:
                form[key] = (request.form.get(key) or "").strip()
        form["sold_out"] = "1" if request.form.get("sold_out") else ""
        if form["mode"] not in ("bus", "plane", "train"):
            errors["mode"] = "Выберите вид транспорта"
        origin, err1 = resolve_place(form["from"], None, None, False)
        dest, err2 = resolve_place(form["to"], None, None, False)
        if err1:
            errors["from"] = err1
        if err2:
            errors["to"] = err2
        if origin and dest and origin["name"] == dest["name"]:
            errors["to"] = "Укажите разные точки"
        try:
            day = datetime.strptime(form["date"], "%Y-%m-%d")
        except ValueError:
            errors["date"] = "Укажите дату в формате ГГГГ-ММ-ДД"
            day = None
        try:
            hour, minute = [int(part) for part in form["time"].split(":", 1)]
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            errors["time"] = "Укажите время в формате ЧЧ:ММ"
            hour = minute = 0
        if not form["title"]:
            errors["title"] = "Введите название рейса"
        elif len(form["title"]) > 120:
            errors["title"] = "Не длиннее 120 символов"
        via_name = form["via"] or ""
        if via_name and via_name not in CITY_BY_NAME:
            errors["via"] = "Выберите город пересадки из списка"
        if via_name and origin and via_name == origin["name"]:
            errors["via"] = "Пересадка совпадает с отправлением"
        if via_name and dest and via_name == dest["name"]:
            errors["via"] = "Пересадка совпадает с прибытием"
        leg2 = None
        if form["leg2_time"]:
            try:
                leg_hour, leg_minute = [int(part) for part in form["leg2_time"].split(":", 1)]
                if not (0 <= leg_hour <= 23 and 0 <= leg_minute <= 59):
                    raise ValueError
            except ValueError:
                errors["leg2_time"] = "Укажите время в формате ЧЧ:ММ"
                leg_hour = leg_minute = 0
            if day is None:
                errors["leg2_time"] = "Сначала укажите дату"
            else:
                leg2 = day.replace(hour=leg_hour, minute=leg_minute)
                if "time" not in errors:
                    depart = day.replace(hour=hour, minute=minute)
                    if leg2 <= depart:
                        errors["leg2_time"] = "Второй участок должен начинаться позже"
        if not errors and origin and dest and day:
            depart_at = day.replace(hour=hour, minute=minute).strftime("%Y-%m-%dT%H:%M")
            leg2_at = leg2.strftime("%Y-%m-%dT%H:%M") if leg2 else None
            layover = None
            if leg2:
                layover = int(
                    (leg2 - day.replace(hour=hour, minute=minute)).total_seconds() // 60
                )
            try:
                if item:
                    db().execute(
                        """
                        UPDATE schedules SET mode = ?, origin = ?, destination = ?,
                        depart_at = ?, title = ?, sold_out = ?, via = ?, layover_min = ?,
                        leg2_at = ?
                        WHERE id = ?
                        """,
                        (form["mode"], origin["name"], dest["name"], depart_at,
                         form["title"], 1 if form["sold_out"] else 0, via_name or None,
                         layover, leg2_at, item["id"]),
                    )
                    log_admin("save", "schedule", item["id"])
                else:
                    created = db().execute(
                        """
                        INSERT INTO schedules
                        (mode, origin, destination, depart_at, title, sold_out, via,
                         layover_min, leg2_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (form["mode"], origin["name"], dest["name"], depart_at,
                         form["title"], 1 if form["sold_out"] else 0, via_name or None,
                         layover, leg2_at),
                    )
                    log_admin("create", "schedule", created.lastrowid)
                db().commit()
            except sqlite3.Error:
                db().rollback()
                flash("Не удалось сохранить рейс.")
                return render_template(
                    "admin_schedule_form.html", item=item, form=form,
                    errors=errors, cities=CITIES,
                )
            flash("Рейс сохранён.")
            return redirect(url_for("admin_schedules"))
    return render_template(
        "admin_schedule_form.html", item=item, form=form, errors=errors, cities=CITIES
    )


@app.route("/admin/schedules/<int:item_id>/delete", methods=["POST"])
@require_admin
def admin_schedule_delete(item_id):
    check_csrf()
    item = db().execute("SELECT id FROM schedules WHERE id = ?", (item_id,)).fetchone()
    if not item:
        abort(404)
    db().execute("DELETE FROM schedules WHERE id = ?", (item_id,))
    log_admin("delete", "schedule", item_id)
    db().commit()
    flash("Рейс удалён.")
    return redirect(url_for("admin_schedules"))


@app.route("/admin/reviews")
@require_admin
def admin_reviews():
    rating = request.args.get("rating") or ""
    query = (request.args.get("q") or "").strip()
    sql = """
        SELECT r.id, r.trip_id, r.target_id, r.rating, r.text, r.created_at,
               a.name AS author_name, b.name AS target_name,
               t.origin, t.destination
        FROM reviews r
        JOIN users a ON a.id = r.author_id
        LEFT JOIN users b ON b.id = r.target_id
        LEFT JOIN trips t ON t.id = r.trip_id
        WHERE 1 = 1
    """
    args = []
    if rating.isdigit() and 1 <= int(rating) <= 5:
        sql += " AND r.rating = ?"
        args.append(int(rating))
    else:
        rating = ""
    if query:
        like = "%" + query + "%"
        sql += " AND (r.text LIKE ? OR a.name LIKE ? OR b.name LIKE ?)"
        args.extend([like, like, like])
    sql += " ORDER BY r.id DESC"
    rows, page, pages, total = paginate_query(sql, args)
    return render_template(
        "admin_reviews.html", rows=rows, rating=rating, query=query,
        page=page, pages=pages, total=total,
    )


@app.route("/admin/reviews/<int:review_id>/delete", methods=["POST"])
@require_admin
def admin_review_delete(review_id):
    check_csrf()
    item = db().execute(
        "SELECT id, target_id FROM reviews WHERE id = ?", (review_id,)
    ).fetchone()
    if not item:
        abort(404)
    db().execute("DELETE FROM reviews WHERE id = ?", (review_id,))
    if item["target_id"]:
        refresh_user_stats(item["target_id"])
    log_admin("delete", "review", review_id)
    db().commit()
    flash("Отзыв удалён.")
    return redirect(url_for("admin_reviews"))


@app.route("/admin/log")
@require_admin
def admin_log():
    rows, page, pages, total = paginate_query(
        """
        SELECT l.*, u.name AS admin_name
        FROM admin_log l
        LEFT JOIN users u ON u.id = l.admin_id
        ORDER BY l.id DESC
        """,
        [],
    )
    return render_template(
        "admin_log.html", rows=rows, page=page, pages=pages, total=total
    )


@app.route("/driver/resign", methods=["POST"])
@require_user()
def driver_resign():
    check_csrf()
    if (g.me["driver_status"] or "none") != "approved":
        abort(403)
    full_name = (request.form.get("full_name") or "").strip()
    reason = (request.form.get("reason") or "").strip()
    email = (g.me["email"] or "").strip()
    if not full_name:
        flash("Укажите ФИО.")
        return redirect(url_for("me_page"))
    if len(full_name) > 200:
        flash("ФИО не длиннее 200 символов.")
        return redirect(url_for("me_page"))
    if not reason:
        flash("Укажите причину ухода.")
        return redirect(url_for("me_page"))
    if len(reason) > 1000:
        flash("Причина не длиннее 1000 символов.")
        return redirect(url_for("me_page"))
    if not email:
        flash("В профиле нет почты, заявку отправить нельзя.")
        return redirect(url_for("me_page"))
    pending = db().execute(
        """
        SELECT id FROM driver_resignations
        WHERE user_id = ? AND status = 'pending' LIMIT 1
        """,
        (g.me["id"],),
    ).fetchone()
    if pending:
        flash("Заявка уже отправлена.")
        return redirect(url_for("me_page"))
    try:
        updated = db().execute(
            """
            UPDATE users SET driver_status = 'pending_resignation'
            WHERE id = ? AND driver_status = 'approved'
            """,
            (g.me["id"],),
        )
        if updated.rowcount != 1:
            db().rollback()
            abort(403)
        db().execute(
            """
            INSERT INTO driver_resignations
            (user_id, full_name, email, reason, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (g.me["id"], full_name, email, reason, text_now()),
        )
        db().commit()
    except sqlite3.Error:
        db().rollback()
        flash("Не удалось отправить заявку. Повторите позже.")
        return redirect(url_for("me_page"))
    flash("Ваша заявка отправлена. Администратор рассмотрит её и примет решение. Будьте на связи, возможно, мы свяжемся с вами для уточнения деталей")
    return redirect(url_for("me_page", resign="sent"))


def parse_positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 1:
        return None
    return number


def support_admin():
    return db().execute(
        """
        SELECT id, name, email, role FROM users
        WHERE role = 'admin' AND status = 'active'
        ORDER BY id LIMIT 1
        """
    ).fetchone()


def users_share_trip(user_a, user_b, trip_id=None):
    sql = """
        SELECT t.id FROM trips t
        JOIN bookings b ON b.trip_id = t.id
        WHERE ((t.driver_id = ? AND b.passenger_id = ?)
            OR (t.driver_id = ? AND b.passenger_id = ?))
    """
    params = [user_a, user_b, user_b, user_a]
    if trip_id is not None:
        sql += " AND t.id = ?"
        params.append(trip_id)
    sql += " LIMIT 1"
    return db().execute(sql, params).fetchone() is not None


def message_thread_exists(user_a, user_b):
    return db().execute(
        """
        SELECT id FROM messages
        WHERE (sender_id = ? AND receiver_id = ?)
           OR (sender_id = ? AND receiver_id = ?)
        LIMIT 1
        """,
        (user_a, user_b, user_b, user_a),
    ).fetchone() is not None


def message_permission(sender, receiver, trip_id):
    if receiver is None or sender is None:
        return False, None, "Пользователь не найден."
    if sender["id"] == receiver["id"]:
        return False, None, "Нельзя написать самому себе."
    if trip_id:
        exists = db().execute("SELECT id FROM trips WHERE id = ?", (trip_id,)).fetchone()
        if not exists:
            trip_id = None
    share_specific = users_share_trip(sender["id"], receiver["id"], trip_id) if trip_id else False
    share_any = users_share_trip(sender["id"], receiver["id"])
    if receiver["role"] == "admin":
        return True, trip_id if share_specific else None, None
    if sender["role"] == "admin":
        known = share_any or message_thread_exists(sender["id"], receiver["id"])
        if trip_id and not share_specific:
            return False, None, "Этому пользователю нельзя написать."
        if known or share_specific:
            return True, trip_id if share_specific else None, None
        return False, None, "Этому пользователю нельзя написать."
    if trip_id:
        if share_specific:
            return True, trip_id, None
        return False, None, "Этому пользователю нельзя написать."
    if share_any:
        return True, None, None
    return False, None, "Этому пользователю нельзя написать."


def load_chat_user(raw_id):
    user_id = parse_positive_int(raw_id)
    if not user_id:
        return None
    return db().execute(
        "SELECT id, name, email, role, status FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()


def chat_author_label(sender_id, sender_role, sender_name, viewer):
    if sender_id == viewer["id"]:
        return "Вы"
    if sender_role == "admin":
        return "Служба ALONG"
    return sender_name


def chat_dialogs(user_id, admin_view, support):
    rows = db().execute(
        """
        SELECT g.other_id, g.trip_id, g.last_id, g.unread,
               u.name AS name, u.role AS role, t.origin, t.destination
        FROM (
            SELECT other_id, trip_id, MAX(last_id) AS last_id, SUM(unread) AS unread
            FROM (
                SELECT receiver_id AS other_id, trip_id, id AS last_id, 0 AS unread
                FROM messages WHERE sender_id = ?
                UNION ALL
                SELECT sender_id AS other_id, trip_id, id AS last_id,
                       CASE WHEN is_read = 0 THEN 1 ELSE 0 END AS unread
                FROM messages WHERE receiver_id = ?
            )
            GROUP BY other_id, trip_id
        ) g
        JOIN users u ON u.id = g.other_id
        LEFT JOIN trips t ON t.id = g.trip_id
        ORDER BY g.last_id DESC
        """,
        (user_id, user_id),
    ).fetchall()
    items = []
    for row in rows:
        if not admin_view and support and row["other_id"] == support["id"] and not row["trip_id"]:
            continue
        label = row["name"]
        if row["role"] == "admin" and row["other_id"] != user_id:
            label = "Служба ALONG"
        items.append({
            "other_id": row["other_id"],
            "trip_id": row["trip_id"],
            "unread": int(row["unread"] or 0),
            "label": label,
            "origin": row["origin"],
            "destination": row["destination"],
            "href": chat_href(row["other_id"], row["trip_id"], admin_view),
        })
    return items


def mark_dialog_read(viewer_id, peer_id, trip_id):
    if trip_id:
        db().execute(
            """
            UPDATE messages SET is_read = 1
            WHERE sender_id = ? AND receiver_id = ? AND trip_id = ? AND is_read = 0
            """,
            (peer_id, viewer_id, trip_id),
        )
    else:
        db().execute(
            """
            UPDATE messages SET is_read = 1
            WHERE sender_id = ? AND receiver_id = ? AND is_read = 0
            """,
            (peer_id, viewer_id),
        )
    db().commit()


def load_dialog_messages(viewer, peer_id, trip_id):
    sql = """
        SELECT m.id, m.sender_id, m.text, m.created_at, u.name AS sender_name, u.role AS sender_role
        FROM messages m
        JOIN users u ON u.id = m.sender_id
        WHERE ((m.sender_id = ? AND m.receiver_id = ?)
            OR (m.sender_id = ? AND m.receiver_id = ?))
    """
    params = [viewer["id"], peer_id, peer_id, viewer["id"]]
    if trip_id:
        sql += " AND m.trip_id = ?"
        params.append(trip_id)
    sql += " ORDER BY m.id ASC"
    rows = db().execute(sql, params).fetchall()
    prepared = []
    for msg in rows:
        prepared.append({
            "id": msg["id"],
            "sender_id": msg["sender_id"],
            "text": msg["text"],
            "created_at": msg["created_at"],
            "display_name": chat_author_label(
                msg["sender_id"], msg["sender_role"], msg["sender_name"], viewer,
            ),
        })
    return prepared


def chat_page(admin_view):
    me = g.me
    support = support_admin()
    access_error = None
    send_error = None
    draft = ""
    peer = None
    active_trip = None
    if request.method == "POST":
        check_csrf()
        draft = request.form.get("text") or ""
        peer = load_chat_user(request.form.get("receiver_id"))
        active_trip = parse_positive_int(request.form.get("trip_id"))
        text = draft.strip()
        if peer is None:
            access_error = "Пользователь не найден."
        elif not text:
            send_error = "Введите сообщение."
        elif len(text) > 2000:
            send_error = "Не больше 2000 символов."
        else:
            allowed, stored_trip, error = message_permission(me, peer, active_trip)
            if not allowed:
                access_error = error
                peer = None
            else:
                try:
                    db().execute(
                        """
                        INSERT INTO messages
                        (sender_id, receiver_id, trip_id, text, is_read, created_at)
                        VALUES (?, ?, ?, ?, 0, ?)
                        """,
                        (me["id"], peer["id"], stored_trip, text, text_now()),
                    )
                    db().commit()
                except sqlite3.Error:
                    db().rollback()
                    send_error = "Не удалось отправить сообщение."
                else:
                    return redirect(chat_href(peer["id"], stored_trip, admin_view))
    else:
        if request.args.get("with"):
            peer = load_chat_user(request.args.get("with"))
            active_trip = parse_positive_int(request.args.get("trip"))
            if peer is None:
                access_error = "Пользователь не найден."
            else:
                allowed, _, error = message_permission(me, peer, active_trip)
                if not allowed:
                    access_error = error
                    peer = None
                else:
                    try:
                        mark_dialog_read(me["id"], peer["id"], active_trip)
                    except sqlite3.Error:
                        db().rollback()
    messages = []
    peer_title = ""
    trip_label = ""
    if peer:
        peer_title = chat_author_label(peer["id"], peer["role"], peer["name"], me)
        if peer_title == "Вы":
            peer_title = peer["name"]
        messages = load_dialog_messages(me, peer["id"], active_trip)
        if active_trip:
            trip_row = db().execute(
                "SELECT origin, destination FROM trips WHERE id = ?",
                (active_trip,),
            ).fetchone()
            if trip_row:
                trip_label = trip_row["origin"] + " → " + trip_row["destination"]
    support_href = None
    support_unread = 0
    if support and support["id"] != me["id"]:
        support_href = chat_href(support["id"], None, admin_view)
        try:
            support_unread = db().execute(
                """
                SELECT COUNT(*) AS n FROM messages
                WHERE sender_id = ? AND receiver_id = ? AND is_read = 0
                """,
                (support["id"], me["id"]),
            ).fetchone()["n"]
        except sqlite3.Error:
            support_unread = 0
    return render_template(
        "admin_messages.html" if admin_view else "chat.html",
        dialogs=chat_dialogs(me["id"], admin_view, support),
        support=support,
        support_href=support_href,
        support_unread=support_unread,
        peer=peer,
        peer_title=peer_title,
        messages=messages,
        access_error=access_error,
        send_error=send_error,
        draft=draft,
        active_trip=active_trip,
        trip_label=trip_label,
        admin_view=admin_view,
        chat_action=url_for("admin_messages" if admin_view else "chat"),
    )


@app.route("/chat", methods=["GET", "POST"])
@require_user()
def chat():
    if request.method == "POST" and not current_user()["verified"]:
        flash("Подтвердите почту, чтобы писать в чат.")
        return redirect(url_for("me_page"))
    if request.method == "POST" and rate_limit("chat:" + str(g.me["id"]), 60, 60):
        flash("Слишком много сообщений. Подождите минуту.")
        return redirect(url_for("chat"))
    try:
        return chat_page(False)
    except sqlite3.Error:
        db().rollback()
        flash("Не удалось открыть сообщения.")
        return redirect(url_for("home"))


@app.route("/admin/messages", methods=["GET", "POST"])
@require_admin
def admin_messages():
    try:
        return chat_page(True)
    except sqlite3.Error:
        db().rollback()
        flash("Не удалось открыть сообщения.")
        return redirect(url_for("admin_home"))


@app.route("/robots.txt")
def robots_txt():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /me\n"
        "Disallow: /chat\n"
        "Disallow: /verify\n"
        "Disallow: /password\n"
        "Sitemap: %ssitemap.xml\n" % request.url_root
    )
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    pages = [url_for("home"), url_for("trips"), url_for("schedule")]
    items = "".join(
        "<url><loc>%s</loc></url>" % (request.url_root.rstrip("/") + path)
        for path in pages
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>'
        % items
    )
    return Response(body, mimetype="application/xml")


@app.errorhandler(401)
def unauthorized(_exc):
    return render_template(
        "error.html", code=401, text="Войдите, чтобы продолжить."
    ), 401


@app.errorhandler(403)
def forbidden(_exc):
    return render_template("denied.html"), 403


@app.errorhandler(404)
def not_found(_exc):
    return render_template("error.html", code=404, text="Такой страницы нет."), 404


@app.errorhandler(500)
def server_error(_exc):
    return render_template("error.html", code=500, text="Не удалось выполнить действие. Повторите позже."), 500


@app.errorhandler(400)
def bad_request(_exc):
    return render_template("error.html", code=400, text="Запрос отклонён. Обновите страницу и повторите."), 400


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5055, debug=False)
