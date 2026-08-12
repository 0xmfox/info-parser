import datetime
import html
import re
import requests
from topicparser.models import Signal
from topicparser import i18n

API = "https://api.github.com"
TRENDING = "https://github.com/trending"
_TREND_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}


def parse_trending(page: str) -> list[tuple[str, int]]:
    """(owner/repo, stars gained in the period) for every row of a github.com/trending page.
    Rubbish or a new layout gives [] — the caller reports that, it does not raise."""
    out = []
    for row in re.findall(r'<article class="Box-row">(.*?)</article>', page or "", re.S):
        name = re.search(r'<h2[^>]*>.*?href="/([^/"]+/[^/"]+)"', row, re.S)
        gain = re.search(r"([\d,]+) stars (?:today|this week|this month)", row)
        if name:
            out.append((html.unescape(name.group(1)),
                        int(gain.group(1).replace(",", "")) if gain else 0))
    return out


def _selected_first(topics: list[str], wanted: list[str]) -> list[str]:
    """Order a repo's own tags so the ones the owner actually searches lead. A repo
    self-tags 10-20 tags and the card shows only the first few, so without this the
    card fills up with `python` / `rust`. Nothing is dropped, only reordered."""
    want = {w.lower() for w in wanted}
    return [t for t in topics if t.lower() in want] + \
           [t for t in topics if t.lower() not in want]


class GitHubCollector:
    source = "github"
    def __init__(self, token: str, created_within_days: int = 90, per_page: int = 100,
                 trending: tuple = ()):
        # Only surface repos CREATED within this window, ranked by stars — i.e. new
        # launches that already gathered traction, not "yet another 1-star clone" that
        # merely got a commit today. `sort=updated` used to flood the results with those.
        self.created_within_days = created_within_days
        # How deep into each topic's star ranking to look. The pool is far larger than
        # any sane limit (`topic:mcp` created in 90 days matches ~24 500 repos), so this
        # is purely a cost/coverage dial — it changes nothing about how repos are judged.
        # GitHub answers 422 above 100, so a bad `.env` value is clamped, not sent.
        self.per_page = max(1, min(100, int(per_page)))
        # github.com/trending periods to read on top of the topic search ("daily",
        # "weekly"). The search only sees repos CREATED in the window with the right tag,
        # and the circle's hits sat on old, big, often untagged ones (REA, gstack): on
        # 2026-10-17 none of the 46 trending repos was among the 454 signals of the last
        # run. Off by default; main turns it on. Rides on the profile's GitHub topics, so
        # a profile with none gets no trending either and no new picker row is needed.
        self.trending = tuple(trending)
        self.headers = {"Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json"}

    def collect(self, profile_name: str, profile_cfg: dict) -> list[Signal]:
        gh = profile_cfg.get("github")
        if not gh:
            return []
        # a repo can carry several of the profile's topics; keep it once (first hit)
        out: dict[str, Signal] = {}
        warn = getattr(self, "warn", None)
        for topic in gh.get("topics", []):
            # one topic hitting a 403 secondary rate limit (or any transient error)
            # must not discard the repos already gathered from the other topics
            try:
                results = self._search(topic, profile_name)
            except Exception as e:
                if warn is not None:
                    warn(i18n.t("warn.github_topic_skipped", topic=topic, error=e))
                continue
            for s in results:
                out.setdefault(s.url, s)
        if gh.get("topics") and self.trending:
            self._trending(profile_name, out, warn)
        wanted = list(gh.get("topics", []))
        for s in out.values():
            s.topics = _selected_first(s.topics, wanted)
        return list(out.values())

    def _search(self, topic: str, profile: str) -> list[Signal]:
        cutoff = (datetime.date.today()
                  - datetime.timedelta(days=self.created_within_days)).isoformat()
        r = requests.get(f"{API}/search/repositories",
                         headers=self.headers,
                         params={"q": f"topic:{topic} created:>{cutoff}",
                                 "sort": "stars", "order": "desc",
                                 "per_page": self.per_page}, timeout=20)
        r.raise_for_status()
        sigs = []
        for it in r.json().get("items", []):
            if it.get("archived") or it.get("fork"):
                continue
            sigs.append(Signal.make(
                source="github", title=it["full_name"],
                description=it.get("description") or "",
                url=it["html_url"], date=it.get("pushed_at", ""),
                profile=profile, stars=it.get("stargazers_count"),
                created=it.get("created_at", ""), topics=it.get("topics") or []))
        return sigs

    def _trending(self, profile: str, out: dict, warn) -> None:
        """Add trending repos to `out` (keyed by url). The stars gained become the velocity,
        the one honest traction number a repo outside the watchlist has. A dead or reshaped
        page is reported once per period and never touches what the topics found."""
        for period in self.trending:
            try:
                r = requests.get(TRENDING, params={"since": period}, timeout=20,
                                 headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                rows = parse_trending(r.text)
                if not rows:
                    raise ValueError("no repositories on the page")
            except Exception as e:
                if warn is not None:
                    warn(i18n.t("warn.github_trending_failed", period=period, error=e))
                continue
            days = _TREND_DAYS.get(period, 7)
            for name, gained in rows:
                url = f"https://github.com/{name}"
                rate = round(gained / days, 1)
                if url in out:
                    out[url].velocity = max(out[url].velocity or 0, rate)
                    continue
                try:
                    it = requests.get(f"{API}/repos/{name}", headers=self.headers, timeout=20)
                    it.raise_for_status()
                    it = it.json()
                except Exception as e:
                    if warn is not None:
                        warn(i18n.t("warn.stars_repo_skipped", repo=name, error=e))
                    continue
                if it.get("archived") or it.get("fork"):
                    continue
                out[url] = Signal.make(
                    source="github", title=it["full_name"],
                    description=it.get("description") or "", url=it["html_url"],
                    date=it.get("pushed_at", ""), profile=profile,
                    stars=it.get("stargazers_count"), velocity=rate,
                    created=it.get("created_at", ""), topics=it.get("topics") or [])

    def measure_tracked(self):
        # A repo that cannot be re-measured shows a stale velocity and can never
        # trend, so the miss goes to the warning banner like every other collector
        # failure. It used to print to stderr, which a windowed build has nowhere.
        from topicparser import store
        warn = getattr(self, "warn", None)
        # The watchlist grows every run and is culled only after 21 days, so this is
        # N sequential calls with N rising. Once GitHub says 403/429 the next 150 will
        # say it too: stop, report once, and let the run get on with its work rather
        # than spending minutes collecting the same refusal.
        for repo in store.get_tracked_repos():
            try:
                r = requests.get(f"{API}/repos/{repo}", headers=self.headers, timeout=20)
                if getattr(r, "status_code", None) in (403, 429):
                    if warn is not None:
                        warn(i18n.t("warn.stars_rate_limited", status=r.status_code))
                    return
                if getattr(r, "status_code", None) == 404:
                    # deleted or made private: it will never answer again, and waiting
                    # for the stagnant cull meant the same red banner for three weeks
                    store.remove_tracked_repo(repo)
                    continue
                r.raise_for_status()
                store.record_stars(repo, r.json().get("stargazers_count", 0))
            except Exception as e:
                if warn is not None:
                    warn(i18n.t("warn.stars_repo_skipped", repo=repo, error=e))

    def attach_velocity(self, signals):
        from topicparser import store
        for s in signals:
            if s.source == "github":
                # the watchlist's measure wins; a trending repo nobody tracks yet keeps
                # the rate the trending page gave it instead of losing it to None
                v = store.velocity(s.title)        # title == full_name
                if v is not None:
                    s.velocity = v
        return signals
