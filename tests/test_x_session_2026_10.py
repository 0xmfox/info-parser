"""Two ways X broke the scrape in October 2026, both of them silent.

Measured on 2026-10-12 with the scrape account: the headless shell Playwright
launches by default got a 403 on every x.com page, cookies or not, while the full
Chromium build loaded the same page. And a dead session now redirects to
`/i/jf/onboarding/...`, which `is_login_url` did not know, so a dead cookie jar
came back as zero tweets and no red banner.
"""
import playwright.sync_api

from topicparser.collectors import x


def test_the_new_onboarding_redirect_reads_as_a_dead_session():
    url = "https://x.com/i/jf/onboarding/web?redirect_after_login=%2Fhome&mode=login"
    assert x.is_login_url(url) is True


def test_an_ordinary_page_under_i_is_still_not_a_login():
    assert x.is_login_url("https://x.com/i/lists/1234567890123456789") is False


class _Ctx:
    def add_init_script(self, script): pass


class _Browser:
    def new_context(self, **kw): return _Ctx()


class _Chromium:
    def __init__(self): self.kwargs = None
    def launch(self, **kw):
        self.kwargs = kw
        return _Browser()


class _PW:
    def __init__(self): self.chromium = _Chromium()
    def start(self): return self


def test_the_scrape_launches_the_full_chromium_not_the_headless_shell(tmp_path, monkeypatch):
    jar = tmp_path / "cookies.json"
    jar.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    pw = _PW()
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: pw)
    monkeypatch.setattr(x, "use_installed_browsers", lambda: None)
    x._PlaywrightSession(str(jar), limit=1, max_scrolls=1).__enter__()
    assert pw.chromium.kwargs.get("channel") == "chromium"
