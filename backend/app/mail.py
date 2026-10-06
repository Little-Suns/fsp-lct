"""Отправка писем по SMTP (stdlib). Настройки — SMTP_* в config."""

import smtplib
import ssl
from email.message import EmailMessage

from app import config


def send(to: str, subject: str, text: str) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.SMTP_FROM, to, subject
    msg.set_content(text)
    ctx = ssl.create_default_context()  # сертификат сервера проверяется: иначе MITM увидит пароль SMTP и коды
    smtp = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=10, context=ctx) if config.SMTP_PORT == 465 else smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10)
    with smtp as s:
        if config.SMTP_PORT != 465 and config.SMTP_STARTTLS:
            s.starttls(context=ctx)
        if config.SMTP_USER:
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
        s.send_message(msg)
