# -*- coding: utf-8 -*-
"""Обновление дат демо-поездок и рейсов ALONG.

Перед изменением создаётся резервная копия базы. Открытые поездки, кроме
нескольких самых ранних, и всё расписание сдвигаются так, чтобы ближайшие
рейсы попали на завтра. Прошлые и скрытые поездки не трогаются.

Примеры:
    python scripts/refresh_demo.py --dry-run
    python scripts/refresh_demo.py
    python scripts/refresh_demo.py --keep-past 1
"""

import argparse
import os
import shutil
import sqlite3
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.abspath(os.environ.get("ALONG_DB") or os.path.join(ROOT, "app", "along.db"))


def backup_database(path):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = f"{path}.bak-{stamp}"
    shutil.copy2(path, target)
    return target


def shift_rows(con, table, where, target_day, dry_run, params=()):
    sql = f"SELECT id, depart_at FROM {table} {where} ORDER BY depart_at"
    rows = con.execute(sql, params).fetchall()
    if not rows:
        print(f"{table}: нечего сдвигать")
        return
    first_day = date.fromisoformat(rows[0]["depart_at"][:10])
    delta = (target_day - first_day).days
    if delta <= 0:
        print(f"{table}: даты уже актуальны (первая {first_day.isoformat()})")
        return
    print(f"{table}: сдвиг на {delta} дн., {len(rows)} записей")
    for row in rows:
        old = datetime.fromisoformat(row["depart_at"])
        new = (old + timedelta(days=delta)).strftime("%Y-%m-%dT%H:%M")
        print(f"  #{row['id']}: {row['depart_at']} -> {new}")
        if not dry_run:
            con.execute(f"UPDATE {table} SET depart_at = ? WHERE id = ?", (new, row["id"]))


def main():
    parser = argparse.ArgumentParser(description="Сдвиг демо-дат ALONG")
    parser.add_argument("--dry-run", action="store_true", help="только показать изменения")
    parser.add_argument(
        "--keep-past", type=int, default=1,
        help="сколько самых ранних открытых поездок оставить в прошлом",
    )
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        raise SystemExit(f"База не найдена: {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    tomorrow = date.today() + timedelta(days=1)
    try:
        keep = max(0, args.keep_past)
        open_ids = [
            row["id"]
            for row in con.execute(
                "SELECT id FROM trips WHERE status = 'open' ORDER BY depart_at, id"
            ).fetchall()
        ]
        shifted_ids = open_ids[keep:]
        if shifted_ids:
            marks = ",".join("?" for _ in shifted_ids)
            where = f"WHERE id IN ({marks})"
            print(f"Открытые поездки: оставляем в прошлом {keep}, сдвигаем {len(shifted_ids)}")
            shift_rows(con, "trips", where, tomorrow, args.dry_run, shifted_ids)
        else:
            print("Открытые поездки: нет записей для сдвига")

        shift_rows(con, "schedules", "", tomorrow, args.dry_run)
        if args.dry_run:
            con.rollback()
            print("\nРежим проверки: база не изменена.")
        else:
            backup = backup_database(DB_PATH)
            con.commit()
            print(f"\nГотово. Бэкап: {backup}")
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()
