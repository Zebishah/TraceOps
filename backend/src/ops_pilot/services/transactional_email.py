"""Resend delivery over the existing async HTTP dependency; no third-party trackers."""

# Literal email markup keeps related attributes together.
# ruff: noqa: E501

from html import escape

import httpx

from ops_pilot.core.config import get_settings


class EmailDeliveryError(Exception):
    """A safe exception: never attach provider bodies, keys, recipients, or link tokens."""


def verification_message(url: str, minutes: int) -> tuple[str, str]:
    text = (
        "Verify your TraceOps email\n\n"
        "Confirm this email address to access your workspace and connect AI applications.\n\n"
        f"{url}\n\nThis link expires in {minutes} minutes and can be used once.\n"
        "If you did not request this, ignore this email."
    )
    html = f'''<!doctype html><html lang="en"><body style="margin:0;padding:32px 16px;background:#eeeae0;font-family:Arial,sans-serif;color:#283021">
<table role="presentation" style="max-width:560px;width:100%;margin:auto;border-collapse:collapse;background:#fcfaf5;border:1px solid #ded5c1">
<tr><td style="padding:28px 32px;background:#151a14;color:#d4b47e;font-size:24px;font-weight:bold">◈ TraceOps</td></tr>
<tr><td style="padding:32px"><p style="font-size:11px;letter-spacing:2px;color:#8a7045">YOUR WORKSPACE. YOUR IDENTITY.</p>
<h1 style="font-size:28px;font-weight:500">One step to a clearer connection.</h1>
<p style="line-height:1.8;color:#666b58">Confirm this email address to access your TraceOps workspace and connect your AI applications.</p>
<p style="margin:30px 0"><a href="{escape(url, quote=True)}" style="display:inline-block;background:#25301e;color:#fcfaf5;padding:16px 24px;border-radius:7px;text-decoration:none">Verify email address ↗</a></p>
<p style="font-size:13px;line-height:1.8;color:#827d6d">This link expires in {minutes} minutes and can be used once. If you did not request this, ignore this email.</p>
<p style="font-size:11px;line-height:1.8;word-break:break-all;color:#827d6d">Button not working? Copy this address into your browser:<br>{escape(url)}</p></td></tr>
<tr><td style="padding:20px 32px;border-top:1px solid #ded5c1;font-size:11px;color:#827d6d">TraceOps · Evidence before action.</td></tr></table></body></html>'''
    return text, html


def verification_code_message(code: str, minutes: int) -> tuple[str, str]:
    text = (
        f"Your TraceOps verification code is {code}.\n\n"
        "Enter this code on the verification screen to finish signup.\n"
        f"It expires in {minutes} minutes and can be used once.\n"
        "Do not share this code. If you did not request it, ignore this email."
    )
    html = f"""<!doctype html><html lang="en"><body style="margin:0;padding:32px 16px;background:#eeeae0;font-family:Arial,sans-serif;color:#283021">
<table role="presentation" style="max-width:560px;width:100%;margin:auto;border-collapse:collapse;background:#fcfaf5;border:1px solid #ded5c1;border-radius:16px">
<tr><td style="padding:28px 32px;background:#151a14;color:#d4b47e;font-size:24px;font-weight:bold">◈ TraceOps</td></tr>
<tr><td style="padding:32px"><p style="font-size:11px;letter-spacing:2px;color:#8a7045">COMPLETE YOUR SIGNUP</p>
<h1 style="font-size:28px;font-weight:500">Your verification code.</h1>
<p style="line-height:1.8;color:#666b58">Enter this code on the TraceOps verification screen to confirm your email and access your workspace.</p>
<p style="margin:28px 0;padding:22px;background:#f1ecdf;border:1px solid #ded5c1;border-radius:10px;text-align:center;font-size:36px;font-weight:bold;letter-spacing:10px;color:#25301e">{escape(code)}</p>
<p style="font-size:13px;line-height:1.8;color:#827d6d">This code expires in {minutes} minutes and can be used once. Never share it with anyone.</p>
<p style="font-size:12px;line-height:1.8;color:#827d6d">If you did not request this code, you can ignore this email.</p></td></tr>
<tr><td style="padding:20px 32px;border-top:1px solid #ded5c1;font-size:11px;color:#827d6d">TraceOps · Evidence before action.</td></tr></table></body></html>"""
    return text, html


async def send_verification_code(
    *, recipient: str, code: str, minutes: int, delivery_id: str
) -> None:
    text, html = verification_code_message(code, minutes)
    await _send_verification_message(
        recipient=recipient, text=text, html=html, delivery_id=delivery_id
    )


async def send_verification_email(*, recipient: str, url: str, delivery_id: str) -> None:
    text, html = verification_message(url, get_settings().email_verification_expire_minutes)
    await _send_verification_message(
        recipient=recipient, text=text, html=html, delivery_id=delivery_id
    )


async def _send_verification_message(
    *, recipient: str, text: str, html: str, delivery_id: str
) -> None:
    settings = get_settings()
    if not settings.resend_api_key or not settings.email_from:
        raise EmailDeliveryError("Email delivery is not configured")
    try:
        async with httpx.AsyncClient(timeout=settings.email_delivery_timeout_seconds) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key.get_secret_value()}",
                    "Idempotency-Key": f"email-verification/{delivery_id}",
                },
                json={
                    "from": settings.email_from,
                    "to": [recipient],
                    "subject": "Verify your TraceOps email",
                    "html": html,
                    "text": text,
                },
            )
        if not response.is_success:
            raise EmailDeliveryError("Email delivery was not accepted")
        result = response.json()
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("id"), str)
            or not result["id"]
        ):
            raise EmailDeliveryError("Email delivery returned an invalid acknowledgement")
    except (httpx.HTTPError, ValueError):
        raise EmailDeliveryError("Email delivery is temporarily unavailable") from None
