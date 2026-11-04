"""Self-contained, themed MCP consent pages; no third-party assets or frontend dependency."""

# Literal HTML/SVG markup stays together for review.
# ruff: noqa: E501

import html
import secrets
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from starlette.responses import HTMLResponse

from ops_pilot.mcp.oauth_form import AUTHORIZATION_FIELDS

_BRAND = """<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 18V5a3 3 0 0 0-5.7-1.3A4 4 0 0 0 4 11a4 4 0 0 0 1 7.5A3.5 3.5 0 0 0 12 18Zm0-12a3 3 0 0 1 5.7-1.3A4 4 0 0 1 20 12a4 4 0 0 1-1 7.5A3.5 3.5 0 0 1 12 18M7 7h2m-4 6h4m6-5h3m-3 6h5M7 18h2m6 4v-4h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>"""
_SHIELD = """<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z" stroke="currentColor" stroke-width="1.5"/><path d="m8 12 3 3 5-6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>"""


@lru_cache(maxsize=1)
def _stylesheet() -> str:
    return Path(__file__).with_name("oauth_login.css").read_text(encoding="utf-8")


def redirect_origin(uri: str) -> str:
    parsed = urlsplit(uri)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else f"{parsed.scheme}:"


def render_login(
    *,
    values: Mapping[str, str] | None = None,
    client_name: str = "",
    scopes: Sequence[str] = (),
    csrf_token: str = "",
    email: str = "",
    error: str = "",
    status_code: int = 200,
    retry_after: int | None = None,
    verification_url: str = "",
) -> HTMLResponse:
    nonce = secrets.token_urlsafe(18)
    esc = html.escape
    is_form = values is not None
    destination = redirect_origin(values["redirect_uri"]) if values else ""
    hidden = (
        "".join(
            f'<input type="hidden" name="{key}" value="{esc(values.get(key, ""), quote=True)}">'
            for key in AUTHORIZATION_FIELDS
        )
        if values
        else ""
    )
    error_box = (
        f'<div class="form-error" role="alert" tabindex="-1">{esc(error)}</div>' if error else ""
    )
    verification_link = (
        f'<p class="connection-details"><a href="{esc(verification_url, quote=True)}" target="_blank" rel="noopener noreferrer">Open email verification ↗</a></p>'
        if verification_url
        else ""
    )
    write_permission = (
        """<article class="permission"><span class="permission-icon">↗</span><div><strong>Investigate and request actions</strong><p>Start investigations and use permitted write tools. Sensitive actions still require human approval.</p></div><span class="permission-tag">WRITE</span></article>"""
        if "ops-pilot:write" in scopes
        else ""
    )
    if is_form:
        panel = f'''
          <div class="mode-marker"><span></span> CONNECT YOUR AI WORKSPACE</div>
          <h1 id="page-title">A smarter connection.<br><em>Your control.</em></h1>
          <p class="introduction">Sign in to OpsPilot to connect the application below to your workspace.</p>
          <div class="client-card"><span class="client-icon">↗</span><div><span class="small-label">CONNECTING APPLICATION</span><strong>{esc(client_name)}</strong></div><span class="connection-dot" aria-hidden="true"></span></div>
          <div class="permissions" aria-label="Requested access"><article class="permission"><span class="permission-icon">▤</span><div><strong>Read workspace context</strong><p>Read incidents, search knowledge, and inspect records allowed by your role.</p></div><span class="permission-tag">READ</span></article>{write_permission}</div>
          <details class="connection-details"><summary>Review connection details <span aria-hidden="true">＋</span></summary><dl><dt>Return address</dt><dd><code>{esc(destination)}</code></dd><dt>Requested scopes</dt><dd><code>{esc(" ".join(scopes))}</code></dd></dl><p>Application names are supplied by the connecting app. Check that the return address belongs to the app you intended to connect.</p></details>
          {error_box}{verification_link}
          <form method="post" action="/oauth/login" id="authorization-form">
            {hidden}<input type="hidden" name="csrf_token" value="{esc(csrf_token, quote=True)}">
            <label for="email">Email address<input id="email" type="email" name="email" required maxlength="320" autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="you@company.com" value="{esc(email, quote=True)}"></label>
            <label for="password">Password<span class="password-field"><input id="password" type="password" name="password" required maxlength="128" autocomplete="current-password" placeholder="Enter your password"><button id="password-toggle" type="button" aria-controls="password" aria-pressed="false" hidden>Show</button></span></label>
            <button class="authorize-button" type="submit" name="decision" value="allow"><span id="authorize-label">Sign in &amp; connect</span><span class="submit-arrow" aria-hidden="true">↗</span></button>
            <button class="cancel-button" type="submit" name="decision" value="deny" formnovalidate>Cancel connection</button>
            <span class="sr-only" id="connection-status" role="status" aria-live="polite"></span>
          </form>
          <div class="trust-note">{_SHIELD}<p>Your password stays with OpsPilot.<br>The app receives scoped access, never your password.</p></div>
        '''
    else:
        panel = f"""
          <div class="mode-marker"><span></span> CONNECTION NEEDS ATTENTION</div>
          <h1 id="page-title">Let’s reconnect.<br><em>With clarity.</em></h1>
          <p class="introduction">We couldn’t continue this connection securely.</p>{error_box}
          <div class="restart-note">{_SHIELD}<div><strong>Start a fresh connection</strong><p>Return to your AI application and connect OpsPilot again. You can close this window.</p></div></div>
        """
    script = """const toggle=document.getElementById('password-toggle');const password=document.getElementById('password');if(toggle&&password){toggle.hidden=false;toggle.addEventListener('click',()=>{const reveal=password.type==='password';password.type=reveal?'text':'password';toggle.textContent=reveal?'Hide':'Show';toggle.setAttribute('aria-pressed',String(reveal));});}const form=document.getElementById('authorization-form');if(form){form.addEventListener('submit',event=>{if(form.dataset.pending==='true'){event.preventDefault();return;}form.dataset.pending='true';form.setAttribute('aria-busy','true');const denied=event.submitter&&event.submitter.value==='deny';document.getElementById('connection-status').textContent=denied?'Returning to your application…':'Signing in and connecting…';if(!denied)document.getElementById('authorize-label').textContent='Connecting…';});}const error=document.querySelector('[role="alert"]');if(error)error.focus();"""
    body = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"><title>Connect your AI workspace · OpsPilot</title><style nonce="{nonce}">{_stylesheet()}</style></head><body>
      <main class="auth-stage"><aside class="visual-panel" aria-label="OpsPilot connection overview">
        <div class="visual-top"><div class="brand"><span class="brand-icon">{_BRAND}</span><span>opspilot<small>INTELLIGENCE WORKSPACE</small></span></div><span class="edition">CONTEXT, CONNECTED.</span></div>
        <div class="visual-copy"><span class="overline">INTELLIGENCE. WITH BOUNDARIES.</span><h2>Your AI.<br>The right context.<br><em>You, in control.</em></h2><p>Connect the tools you work with.<br>Keep your workspace permissions intact.</p></div>
        <div class="connection-scene" aria-hidden="true"><div class="scene-grid"></div><div class="scene-orbit orbit-one"></div><div class="scene-orbit orbit-two"></div><div class="scene-route route-one"><i></i></div><div class="scene-route route-two"><i></i></div><div class="scene-node client-node"><span>↗</span><strong>YOUR AI APP</strong><small>Scoped connection</small></div><div class="scene-core">{_BRAND}<span>OPSPILOT</span></div><div class="scene-node context-node"><span>▤</span><strong>YOUR WORKSPACE</strong><small>Evidence &amp; context</small></div><div class="scene-seal">{_SHIELD}<span>Access follows your role</span></div></div>
        <div class="visual-bottom"><span>EVIDENCE BEFORE ACTION.</span><span>HUMAN REVIEW, BUILT IN.</span></div>
      </aside><section class="form-panel" aria-labelledby="page-title"><header class="form-header"><span class="mobile-brand">◈ opspilot</span><span class="connection-label">{_SHIELD} PRIVATE SIGN-IN</span></header><div class="form-content">{panel}</div><footer><span>OPSPILOT / MCP CONNECTION</span><span>Context. Clarity. Control.</span></footer></section></main><script nonce="{nonce}">{script}</script></body></html>'''
    headers = {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": (
            f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
            f"form-action 'self'{(' ' + destination) if destination else ''}; "
            "frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
        ),
    }
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return HTMLResponse(body, status_code=status_code, headers=headers)
