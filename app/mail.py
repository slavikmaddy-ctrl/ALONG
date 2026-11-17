# -*- coding: utf-8 -*-
"""Почта ALONG: SMTP, если он настроен, иначе локальный демо-режим."""

import os
import smtplib
import ssl
from email.message import EmailMessage


def smtp_configured():
    return bool((os.environ.get("ALONG_SMTP_HOST") or "").strip())


def smtp_settings():
    try:
        port = int(os.environ.get("ALONG_SMTP_PORT") or 587)
    except (TypeError, ValueError):
        port = 587
    return {
        "host": (os.environ.get("ALONG_SMTP_HOST") or "").strip(),
        "port": port,
        "user": (os.environ.get("ALONG_SMTP_USER") or "").strip(),
        "password": os.environ.get("ALONG_SMTP_PASSWORD") or "",
        "sender": (
            os.environ.get("ALONG_SMTP_FROM")
            or os.environ.get("ALONG_SMTP_USER")
            or "along@localhost"
        ),
        "ssl": (os.environ.get("ALONG_SMTP_SSL") or "").strip() == "1",
    }


def send_mail(to, subject, body):
    """Отправляет письмо и возвращает (отправлено, причина).

    Если ALONG_SMTP_HOST не задан, письмо не уходит: приложение работает
    в демо-режиме, а текст письма пишется в журнал.
    """
    settings = smtp_settings()
    if not settings["host"]:
        return False, "smtp"
    message = EmailMessage()
    message["From"] = settings["sender"]
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        if settings["ssl"]:
            client = smtplib.SMTP_SSL(
                settings["host"], settings["port"],
                context=ssl.create_default_context(), timeout=15,
            )
        else:
            client = smtplib.SMTP(settings["host"], settings["port"], timeout=15)
            client.starttls(context=ssl.create_default_context())
        with client:
            if settings["user"]:
                client.login(settings["user"], settings["password"])
            client.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        return False, "error: %s" % exc
    return True, "sent"
