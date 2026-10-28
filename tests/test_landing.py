"""The signed-out landing page (static/landing.html, served at / in accounts mode): a strict CSP with nothing inline,
no vendor names, self-hosted fonts, the invite mailto from `invite_email`, and the operator's note only off the
hosted server."""

from __future__ import annotations

import re
import shutil

import pytest
from fastapi.testclient import TestClient
from test_easy_connect import _manager

from openmob import server
from openmob.accounts import AccountStore
from openmob.config import check_invite_email, load_config
from openmob.server import LANDING_CSP, create_app, render_landing

STATIC = server.STATIC
VENDORS = ["anthropic", "claude", "jev", "typesafe", "openai", "gemini", "qwen", "xai", "grok", "gatekeeper",
           "keystore"]
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


@pytest.fixture
def make(tmp_path, monkeypatch):
    """make(invite_email=None) -> (TestClient, AccountStore) for an accounts-mode server, not on Fly."""
    monkeypatch.delenv("FLY_APP_NAME", raising=False)

    def build(invite_email=None):
        manager = _manager(tmp_path)
        manager.cfg.invite_email = invite_email
        store = AccountStore(tmp_path / "accounts.json")
        return TestClient(create_app(manager, store=store)), store
    return build


def page_files() -> dict[str, str]:
    return {name: (STATIC / name).read_text() for name in ("landing.html", "landing.css", "landing.js")}


def test_nothing_inline():
    html = (STATIC / "landing.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html, re.I)  # every script is a file
    assert "<style" not in html.lower()
    assert not re.search(r"\sstyle\s*=", html, re.I)
    assert not re.search(r"\son[a-z]+\s*=", html, re.I)  # no inline event handlers either


def test_the_csp_is_exact_on_the_landing_page_only(make):
    client, _ = make()
    r = client.get("/")
    assert r.status_code == 200 and "Give any AI agent a real Android phone." in r.text
    assert r.headers["content-security-policy"] == CSP == LANDING_CSP
    assert r.headers["cache-control"] == "no-store"  # the same address is the dashboard once signed in
    assert client.get("/safety").headers["content-security-policy"] == "frame-ancestors 'none'"


def test_no_vendor_names_or_implementation_details():
    for name, text in page_files().items():
        for word in VENDORS:
            assert not re.search(word, text, re.I), f"{word!r} in {name}"
    for word in ("hmac", "0.77", "2.9 s", "[N]"):
        assert word.lower() not in page_files()["landing.html"].lower()


def test_no_http_or_third_party_urls(make):
    for name, text in page_files().items():
        assert "http://" not in text and "https://" not in text, name
    client, _ = make("invites@example.com")
    html = client.get("/", headers={"host": "openmob.example"}).text
    links = re.findall(r"""(?:href|src)\s*=\s*["']([^"']*)["']""", html)
    assert links and all(link.startswith(("/", "#", "mailto:")) and not link.startswith("//") for link in links), links
    css = (STATIC / "landing.css").read_text()
    assert all(u.startswith("/static/") for u in re.findall(r"""url\(["']?([^"')]+)""", css))
    assert "@import" not in css


def test_the_code_samples_show_this_servers_own_address(make):
    client, _ = make()
    html = client.get("/", headers={"host": "phones.example.org:8443"}).text
    assert '"url": "http://phones.example.org:8443/mcp"' in html
    assert "curl -X POST http://phones.example.org:8443/v1/devices/" in html
    # A forged Host can't put markup on the page: anything but a plain host becomes a placeholder.
    html = client.get("/", headers={"host": 'evil"><b>x'}).text
    assert "<b>x" not in html and "https://your-openmob-server/mcp" in html


def test_the_invite_mailto_is_shown_with_invite_email_set(make):
    client, _ = make("invites+beta@example.com")
    html = client.get("/").text
    href = "mailto:invites%2Bbeta@example.com?subject=OpenMob%20invite%20request"
    assert html.count(f'href="{href}"') == 3  # header, hero, invite section
    assert 'href="/login">I have an invite' in html
    # The value is escaped whatever it holds (config refuses such an address, but the page doesn't rely on it).
    page = render_landing("https://openmob.example", 'a"<b>&@example.com', True, False, False)
    assert '"<b>' not in page and "<b>&" not in page and "mailto:a%22%3Cb%3E%26@example.com" in page


def test_the_invite_buttons_hide_without_invite_email(make):
    client, _ = make()
    html = client.get("/").text
    assert "mailto:" not in html and "Request an invite" not in html
    assert 'href="/login">I have an invite' in html


def test_invite_email_config(tmp_path, monkeypatch):
    assert check_invite_email(None) is None and check_invite_email("  ") is None
    assert check_invite_email(" invites@example.com ") == "invites@example.com"
    for bad in ("not an email", "a@b", 'x"@example.com', "a@example.com?cc=b@example.com", 42):
        with pytest.raises(ValueError):
            check_invite_email(bad)
    path = tmp_path / "config.yaml"
    path.write_text("invite_email: hello@example.com\n")
    monkeypatch.delenv("OPENMOB_INVITE_EMAIL", raising=False)
    assert load_config(path).invite_email == "hello@example.com"
    monkeypatch.setenv("OPENMOB_INVITE_EMAIL", "env@example.com")
    assert load_config(path).invite_email == "env@example.com"


def test_the_operator_note_shows_only_off_the_hosted_server(make, monkeypatch):
    note = "openmob account invite"
    client, _ = make()
    assert note in client.get("/").text  # a local or self-hosted server
    client, _ = make("invites@example.com")
    assert note not in client.get("/").text  # an invite address means a hosted server
    monkeypatch.setenv("FLY_APP_NAME", "openmob")
    client, _ = make()
    assert note not in client.get("/").text


def test_privacy_and_terms_only_when_their_files_exist(make, tmp_path, monkeypatch):
    client, _ = make()
    html = client.get("/").text
    assert 'href="/privacy"' not in html and 'href="/terms"' not in html and "privacy policy" not in html
    assert client.get("/privacy").status_code == 404 and client.get("/terms").status_code == 404
    assert 'href="/safety">Safety' in html and 'href="/developer#/docs/quickstart">Docs' in html
    assert "Status" not in html

    copy = tmp_path / "static"
    shutil.copytree(STATIC, copy)
    (copy / "privacy.html").write_text("<!doctype html><title>Privacy</title><p>The policy.</p>")
    monkeypatch.setattr(server, "STATIC", copy)
    client, _ = make()
    html = client.get("/").text
    assert html.count('href="/privacy"') == 2 and 'href="/terms"' not in html  # footer and "Who sees your screen"
    assert "The policy." in client.get("/privacy").text and client.get("/terms").status_code == 404
    (copy / "terms.html").write_text("<!doctype html><title>Terms</title><p>The terms.</p>")
    assert 'href="/terms">Terms' in client.get("/").text and "The terms." in client.get("/terms").text


def test_the_fonts_and_assets_are_served_locally(make):
    client, _ = make()
    css = client.get("/static/landing.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    fonts = re.findall(r'url\("(/static/fonts/[^"]+\.woff2)"\)', css.text)
    assert len(fonts) == 5
    for font in fonts:
        r = client.get(font)
        assert r.status_code == 200 and r.headers["content-type"] == "font/woff2" and r.content[:4] == b"wOF2"
    assert "Open Font License" in client.get("/static/fonts/OFL.txt").text
    for theme in ("light", "dark"):
        r = client.get(f"/static/img/app-home-{theme}.webp")
        assert r.status_code == 200 and r.content[8:12] == b"WEBP" and len(r.content) < 150_000
    for path in ("/static/index.html", "/static/../server.py", "/static/fonts/../landing.html", "/static/nope.css"):
        assert client.get(path).status_code == 404, path
    assert client.get("/static/ds.css").headers["content-type"].startswith("text/css")


def test_the_signed_in_redirect_still_works(make):
    client, store = make()
    js = client.get("/static/landing.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert 'fetch("/api/auth/me"' in js.text and "location.replace" in js.text and "openmob.theme" in js.text
    assert '<script src="/static/landing.js"></script>' in client.get("/").text
    store.create_account("owner@example.com", "password123")
    assert client.post("/api/auth/login", json={"email": "owner@example.com", "password": "password123"}).status_code == 200
    r = client.get("/")
    assert "Give any AI agent" not in r.text and "Tell your phone what to do…" in r.text  # the dashboard
    assert r.headers["content-security-policy"] == "frame-ancestors 'none'"
