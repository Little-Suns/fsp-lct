"""Отправка писем по SMTP (stdlib). Настройки — SMTP_* в config."""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app import config

log = logging.getLogger("uvicorn.error")  # как в main: видно в выводе сервера без настройки logging


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


def invite_notice(to: str) -> None:
    """Письмо кандидату о новом приглашении. Идёт фоном после ответа работодателю: медленный или упавший SMTP
    приглашение не тормозит и не отменяет. В письме нет ни компании, ни рекрутера — только ссылка в кабинет."""
    text = (
        "Здравствуйте!\n\nВам пришло новое приглашение с вилкой в ФСП Карьере. "
        f"Посмотреть его и ответить — в кабинете: {config.PUBLIC_URL}/candidate\n\n"
        "Письма о приглашениях отключаются там же, в блоке «Уведомления»."
    )
    try:
        send(to, "Новое приглашение в ФСП Карьере", text)
    except Exception as e:  # noqa: BLE001 — сбой почты не должен всплыть трейсбэком: в нём адрес получателя
        log.warning("Письмо о приглашении не отправлено: %s", type(e).__name__)  # без адреса — 152-ФЗ
