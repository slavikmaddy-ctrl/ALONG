# -*- coding: utf-8 -*-
"""Сборка статических HTML-макетов ALONG для импорта в Figma.

Скрипт заходит на запущенный сервер, скачивает готовые страницы, убирает
скрипты и серверные токены, переписывает ссылки и пути к картинкам на
локальные. На выходе — папка mockups-figma с чистыми HTML и CSS.

Перед запуском сервер должен работать на http://127.0.0.1:5055.
Ассеты (assets/, styles.css) уже лежат в папке макетов.

Примеры:
    python scripts/build_figma_mockups.py
    python scripts/build_figma_mockups.py --base-url http://127.0.0.1:5055
"""

import argparse
import os
import re
import shutil
import sys
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "mockups-figma")
STATIC_DIR = os.path.join(ROOT, "app", "static")

ADMIN_EMAIL = "admin@along.local"
USER_EMAIL = "user@along.local"

# путь на сервере -> (локальный файл, роль для входа)
PAGES = {
    "/": ("index.html", None),
    "/trips": ("trips.html", None),
    "/trips/2": ("trip.html", "user"),
    "/trips/new": ("trip-new.html", "user"),
    "/schedule": ("schedule.html", None),
    "/route?from=%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B0&to=%D0%9C%D0%B8%D0%BD%D1%81%D0%BA": ("route.html", None),
    "/login": ("login.html", None),
    "/register": ("register.html", None),
    "/me": ("profile.html", "user"),
    "/support": ("support.html", None),
    "/admin": ("admin.html", "admin"),
    "/admin/trips": ("admin-trips.html", "admin"),
}

LINK_MAP = {
    "/": "index.html",
    "/trips": "trips.html",
    "/trips/2": "trip.html",
    "/trips/new": "trip-new.html",
    "/schedule": "schedule.html",
    "/route": "route.html",
    "/login": "login.html",
    "/register": "register.html",
    "/me": "profile.html",
    "/support": "support.html",
    "/admin": "admin.html",
    "/admin/trips": "admin-trips.html",
}

CSRF_RE = re.compile(r'name="csrf" value="([^"]+)"')


def login(session, base_url, email, password):
    response = session.get(base_url + "/login", timeout=20)
    response.raise_for_status()
    match = CSRF_RE.search(response.text)
    if not match:
        raise RuntimeError("На странице входа нет CSRF-токена")
    response = session.post(
        base_url + "/login",
        data={"email": email, "password": password, "csrf": match.group(1)},
        timeout=20,
        allow_redirects=True,
    )
    response.raise_for_status()
    if "/login" in urlparse(response.url).path:
        raise RuntimeError(f"Не удалось войти: {email}")


def make_session(base_url, accounts, role):
    session = requests.Session()
    session.headers["User-Agent"] = "ALONG-Figma-Mockups/1.0"
    if role:
        login(session, base_url, *accounts[role])
    return session


def local_static(path):
    path = path.split("?")[0]
    if path.startswith("/static/"):
        return "assets/" + path[len("/static/"):]
    if path.startswith("/media/"):
        return "assets/images/" + path[len("/media/"):]
    return path


def transform_url(value, base_url):
    if not value:
        return value
    if value.startswith(base_url):
        value = value[len(base_url):] or "/"
    if value.startswith(("http://", "https://", "data:", "mailto:", "#")):
        return value
    if value.startswith("/static/") or value.startswith("/media/"):
        return local_static(value)
    return value


def map_link(value, base_url):
    if not value:
        return value
    if value.startswith(base_url):
        value = value[len(base_url):] or "/"
    if value.startswith(("http://", "https://", "mailto:", "#", "tel:")):
        return value
    if value.startswith("/"):
        path = urlparse(value).path
        return LINK_MAP.get(path, "#")
    return value


MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def pretty_date(value):
    try:
        year, month, day = (int(part) for part in value.split("-"))
        return f"{day} {MONTHS[month - 1]} {year}"
    except (ValueError, IndexError):
        return ""


def static_calendar(soup, cal):
    """Рисует календарь без JS: кнопка с выбранной или пустой датой."""
    input_id = cal.get("data-input")
    value = ""
    if input_id:
        hidden = soup.find("input", id=input_id)
        if hidden:
            value = pretty_date(hidden.get("value", ""))
    blank = cal.get("data-blank") or "Любая дата"
    label = value or blank

    button = soup.new_tag("button", type="button")
    button["class"] = ["day-pick__btn"] + ([] if value else ["is-empty"])
    button["title"] = label
    span = soup.new_tag("span", **{"class": "day-pick__value"})
    span.string = label
    chev = soup.new_tag("span", **{"class": "day-pick__chev", "aria-hidden": "true"})
    button.append(span)
    button.append(chev)
    cal.append(button)


def clean_document(html, base_url):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all("script"):
        tag.decompose()
    for tag in soup.find_all("link", rel="manifest"):
        tag.decompose()
    for tag in soup.find_all("link", rel="canonical"):
        tag.decompose()

    for tag in soup.find_all("a"):
        href = tag.get("href")
        if href:
            tag["href"] = map_link(href, base_url)

    for tag in soup.find_all("form"):
        action = tag.get("action")
        if action:
            tag["action"] = map_link(action, base_url)

    for tag in soup.find_all(["img", "source", "video", "link"]):
        for attr in ("src", "poster", "href"):
            value = tag.get(attr)
            if value:
                tag[attr] = transform_url(value, base_url)
        srcset = tag.get("srcset")
        if srcset:
            parts = []
            for item in srcset.split(","):
                url = item.strip().split(" ")[0]
                parts.append(item.replace(url, transform_url(url, base_url)))
            tag["srcset"] = ", ".join(parts)

    # Стили: локальный CSS и небольшие правки поверх него.
    for tag in soup.find_all("link", rel="stylesheet"):
        href = tag.get("href") or ""
        if "styles.css" in href:
            tag["href"] = "styles.css"
            extra = soup.new_tag("link", rel="stylesheet", href="mockup.css")
            tag.insert_after(extra)

    # Анимации появления не работают без JS — сразу показываем блоки.
    for tag in soup.select(".reveal"):
        tag["class"] = list(tag.get("class", [])) + ["is-in"]

    # В макете у пустых полей должны быть видимые подсказки.
    placeholders = {
        "from": "Город или адрес",
        "to": "Город или адрес",
        "pickup": "Адрес или ориентир",
        "dropoff": "Адрес или ориентир",
        "luggage": "Например, рюкзак",
        "price": "Например, 1500",
    }
    for field in soup.find_all("input"):
        name = field.get("name")
        if name in placeholders and not field.get("placeholder") and not field.get("value"):
            field["placeholder"] = placeholders[name]

    # Календарь в приложении строит JS — в макете рисуем кнопку сразу.
    for cal in soup.select(".along-cal"):
        static_calendar(soup, cal)

    # Видео в Figma не нужно: подставляем кадр из ролика.
    video = soup.select_one("video.hero-video")
    if video:
        image = soup.new_tag("img", src="assets/hero-still.jpg")
        image["class"] = ["hero-video"]
        image["alt"] = ""
        video.replace_with(image)

    # Карта без JS не отрисуется: подставляем снимок карты.
    for map_id, image_name, alt in (
        ("trip-map", "assets/map-trip.png", "Карта маршрута"),
        ("route-map", "assets/map-route.png", "Карта маршрута"),
    ):
        map_tag = soup.find(id=map_id)
        if map_tag:
            image = soup.new_tag("img", src=image_name)
            image["class"] = ["trip-map" if map_id == "trip-map" else "route-map"]
            image["alt"] = alt
            map_tag.replace_with(image)

    # Токены и служебные поля форм в статическом макете не нужны.
    for tag in soup.select('input[name="csrf"]'):
        tag.decompose()
    for tag in soup.select('input[name="next"]'):
        tag.decompose()

    for tag in soup.find_all(True):
        tag.attrs.pop("loading", None)
        tag.attrs.pop("decoding", None)

    return soup.prettify()


def prepare_assets():
    assets = os.path.join(OUT_DIR, "assets")
    images = os.path.join(assets, "images")
    os.makedirs(images, exist_ok=True)
    source_images = os.path.join(STATIC_DIR, "images")
    for name in os.listdir(source_images):
        source = os.path.join(source_images, name)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(images, name))
    for name in ("logo.png", "icon-192.png", "icon-512.png", "apple-touch-icon.png"):
        source = os.path.join(STATIC_DIR, name)
        if os.path.exists(source):
            shutil.copy2(source, os.path.join(assets, name))

    css_source = os.path.join(STATIC_DIR, "styles.css")
    with open(css_source, encoding="utf-8") as handle:
        css = handle.read()
    css = css.replace('url("images/', 'url("assets/images/')
    with open(os.path.join(OUT_DIR, "styles.css"), "w", encoding="utf-8") as handle:
        handle.write(css)


def main():
    parser = argparse.ArgumentParser(description="Статические макеты ALONG для Figma")
    parser.add_argument("--base-url", default="http://127.0.0.1:5055")
    parser.add_argument("--admin-password", default=os.environ.get("ALONG_ADMIN_PASSWORD") or "TestAdminPass1")
    parser.add_argument("--user-password", default=os.environ.get("ALONG_USER_PASSWORD") or "TestUserPass1")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    accounts = {
        "admin": (ADMIN_EMAIL, args.admin_password),
        "user": (USER_EMAIL, args.user_password),
    }

    if not os.path.isdir(OUT_DIR):
        raise SystemExit("Нет папки mockups-figma")
    prepare_assets()

    sessions = {}
    for path, (filename, role) in PAGES.items():
        if role not in sessions:
            sessions[role] = make_session(base_url, accounts, role)
        response = sessions[role].get(base_url + path, timeout=30)
        response.raise_for_status()
        html = clean_document(response.text, base_url)
        target = os.path.join(OUT_DIR, filename)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(html)
        print(f"{path:16} -> {filename} ({len(html) // 1024} КБ)")

    print(f"\nГотово: {OUT_DIR}")


if __name__ == "__main__":
    main()
