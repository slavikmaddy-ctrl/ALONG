# -*- coding: utf-8 -*-
"""Общие фикстуры тестов ALONG.

Тесты работают на копии схемы во временной папке и никогда не открывают
app/along.db. Переменные окружения выставляются до импорта server.py,
потому что путь к базе читается на уровне модуля.
"""

import os
import re
import shutil
import sqlite3
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

TEMP_DIR = tempfile.mkdtemp(prefix="along-tests-")
TEMPLATE_DB = os.path.join(TEMP_DIR, "template.db")

os.environ["ALONG_ENV"] = "dev"
os.environ["ALONG_DB"] = TEMPLATE_DB
os.environ["ALONG_SECRET_KEY"] = "test-secret-key"
os.environ["ALONG_ADMIN_PASSWORD"] = "TestAdminPass1"
os.environ["ALONG_USER_PASSWORD"] = "TestUserPass1"
os.environ.pop("ALONG_SMTP_HOST", None)
os.environ.pop("ALONG_SMTP_PORT", None)
os.environ.pop("ALONG_SECURE_COOKIES", None)
os.environ.pop("ALONG_BASE_URL", None)

import server  # noqa: E402

ADMIN = ("admin@along.local", "TestAdminPass1")
USER = ("user@along.local", "TestUserPass1")
DRIVER = ("alina@along.local", "TestUserPass1")

CSRF_RE = re.compile(r'name="csrf" value="([^"]+)"')


def get_csrf(client, path="/"):
    """Берёт CSRF-токен из формы уже открытой страницы."""
    response = client.get(path)
    assert response.status_code == 200, f"GET {path} -> {response.status_code}"
    match = CSRF_RE.search(response.get_data(as_text=True))
    assert match, f"На странице {path} нет поля csrf"
    return match.group(1)


def login(client, email, password, path="/login"):
    token = get_csrf(client, path)
    response = client.post(
        "/login",
        data={"email": email, "password": password, "csrf": token},
    )
    assert response.status_code == 302, (
        f"Вход {email} не удался: {response.status_code}"
    )
    return response


@pytest.fixture(scope="session")
def template_db():
    server.DB_PATH = TEMPLATE_DB
    server.init_db()
    assert os.path.exists(TEMPLATE_DB)
    return TEMPLATE_DB


@pytest.fixture()
def db_path(tmp_path, template_db):
    target = tmp_path / "along.db"
    shutil.copyfile(template_db, target)
    server.DB_PATH = str(target)
    return target


@pytest.fixture()
def db(db_path):
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture()
def app(db_path):
    server.app.config.update(TESTING=True)
    return server.app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_client(app):
    made = app.test_client()
    login(made, *ADMIN)
    return made


@pytest.fixture()
def user_client(app):
    made = app.test_client()
    login(made, *USER)
    return made


@pytest.fixture()
def driver_client(app):
    made = app.test_client()
    login(made, *DRIVER)
    return made
