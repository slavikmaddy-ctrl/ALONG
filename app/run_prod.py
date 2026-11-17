# -*- coding: utf-8 -*-
"""Прод-запуск ALONG: waitress, без debug и с настройками из окружения.

Пример:
    cd app
    python run_prod.py

Переменные окружения: ALONG_ENV=prod, ALONG_SECRET_KEY, ALONG_DB,
ALONG_HOST, ALONG_PORT, ALONG_SECURE_COOKIES, ALONG_SMTP_*.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

os.environ.setdefault("ALONG_ENV", "prod")

from waitress import serve  # noqa: E402

from server import app, init_db  # noqa: E402


def main():
    init_db()
    host = os.environ.get("ALONG_HOST") or "0.0.0.0"
    try:
        port = int(os.environ.get("ALONG_PORT") or 5055)
    except ValueError:
        port = 5055
    threads = int(os.environ.get("ALONG_THREADS") or 8)
    print(f"ALONG: waitress на http://{host}:{port} (threads={threads})")
    serve(app, host=host, port=port, threads=threads)


if __name__ == "__main__":
    main()
