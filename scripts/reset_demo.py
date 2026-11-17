# -*- coding: utf-8 -*-
"""Ротация демо-паролей и удаление мусорных аккаунтов ALONG.

Скрипт идемпотентен: повторный запуск снова меняет пароли на указанные
и не падает, если мусорных аккаунтов уже нет.

Примеры:
    python scripts/reset_demo.py
    python scripts/reset_demo.py --admin-password "N3w-Admin-Pass" --user-password "N3w-User-Pass"
    ALONG_DB=C:\\data\\along.db python scripts/reset_demo.py
"""

import argparse
import os
import secrets
import shutil
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

DB_PATH = os.path.abspath(os.environ.get("ALONG_DB") or os.path.join(APP_DIR, "along.db"))

import server  # noqa: E402

DEMO_ACCOUNTS = {
    "admin@along.local": "ALONG_ADMIN_PASSWORD",
    "user@along.local": "ALONG_USER_PASSWORD",
}
JUNK_EMAILS = ("name@example.com", "slavikmaddy@gmail.com")

RELATED_TABLES = (
    ("messages", "sender_id"),
    ("messages", "receiver_id"),
    ("complaints", "author_id"),
    ("bookings", "passenger_id"),
    ("custom_offers", "passenger_id"),
    ("saved_routes", "user_id"),
    ("driver_resignations", "user_id"),
    ("sessions", "user_id"),
    ("reviews", "author_id"),
    ("reviews", "target_id"),
)


def backup_database(path):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = f"{path}.bak-{stamp}"
    shutil.copy2(path, target)
    return target


def delete_user(con, user_id):
    for table, column in RELATED_TABLES:
        con.execute(f"DELETE FROM {table} WHERE {column} = ?", (user_id,))
    con.execute("DELETE FROM users WHERE id = ?", (user_id,))


def main():
    parser = argparse.ArgumentParser(description="Ротация демо-паролей ALONG")
    parser.add_argument("--admin-password", default=os.environ.get("ALONG_ADMIN_PASSWORD") or "")
    parser.add_argument("--user-password", default=os.environ.get("ALONG_USER_PASSWORD") or "")
    parser.add_argument(
        "--keep-junk", action="store_true",
        help="не удалять мусорные аккаунты name@example.com и slavikmaddy@gmail.com",
    )
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        raise SystemExit(f"База не найдена: {DB_PATH}")

    backup = backup_database(DB_PATH)
    print(f"Бэкап базы: {backup}")

    passwords = {
        "admin@along.local": args.admin_password or secrets.token_urlsafe(9),
        "user@along.local": args.user_password or secrets.token_urlsafe(9),
    }

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    changed = []
    removed = []
    blocked = []
    try:
        for email, password in passwords.items():
            row = con.execute("SELECT id, name FROM users WHERE email = ?", (email,)).fetchone()
            if not row:
                print(f"Пропущено: {email} не найден")
                continue
            con.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (server.hash_password(password), row["id"]),
            )
            con.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
            changed.append((email, row["name"], password))

        if not args.keep_junk:
            for email in JUNK_EMAILS:
                row = con.execute("SELECT id, name FROM users WHERE email = ?", (email,)).fetchone()
                if not row:
                    continue
                drives = con.execute(
                    "SELECT COUNT(*) AS n FROM trips WHERE driver_id = ?", (row["id"],)
                ).fetchone()["n"]
                if drives:
                    con.execute("UPDATE users SET status = 'blocked' WHERE id = ?", (row["id"],))
                    con.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
                    blocked.append((email, row["name"], drives))
                else:
                    delete_user(con, row["id"])
                    removed.append((email, row["name"]))

        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    print("\nНовые пароли (сохраните и передайте владельцу):")
    for email, name, password in changed:
        print(f"  {email}  ({name})  ->  {password}")
    if not changed:
        print("  демо-аккаунты не найдены")
    if removed:
        print("\nУдалены мусорные аккаунты:")
        for email, name in removed:
            print(f"  {email} ({name})")
    if blocked:
        print("\nПереведены в blocked (у них есть поездки):")
        for email, name, drives in blocked:
            print(f"  {email} ({name}), поездок: {drives}")
    if not removed and not blocked and not args.keep_junk:
        print("\nМусорных аккаунтов не найдено.")
    print(f"\nБэкап для отката: {backup}")


if __name__ == "__main__":
    main()
