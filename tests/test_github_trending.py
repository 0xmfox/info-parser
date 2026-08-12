"""GitHub Trending as a second GitHub net. The topic search only sees repos CREATED in the last
90 days that carry the right tag, and the 2026-10-16 study found the circle's hits sitting on
old, big, often untagged repos (REA, gstack, video-use); on 10-17 not one of the 46 trending
repos was among the 454 GitHub signals of the latest run."""
import responses
from topicparser.collectors.github import GitHubCollector, parse_trending

# Trimmed from the real page (2026-10-17): the structure the parser keys on, nothing else.
ROW = """<article class="Box-row">
  <div class="float-right d-flex"><a href="/login?return_to=%2F{o}%2F{r}">Star</a></div>
  <h2 class="h3 lh-condensed">
    <a data-hydro-click="{{}}" href="/{o}/{r}" data-view-component="true" class="Link">
      <span class="text-normal">{o} /</span> {r}</a>  </h2>
    <p class="col-9 color-fg-muted my-1 tmp-pr-4">desc</p>
  <div class="f6 color-fg-muted mt-2">
      <a href="/{o}/{r}/stargazers" class="Link">296,409</a>
      <span class="d-inline-block float-sm-right">{gain} stars {period}</span>
  </div>
</article>"""


def page(*rows):
    return "<html><body>" + "".join(ROW.format(o=o, r=r, gain=g, period=p)
                                    for o, r, g, p in rows) + "</body></html>"


def repo_json(name, **kw):
    d = {"full_name": name, "description": "d", "html_url": f"https://github.com/{name}",
         "stargazers_count": 1000, "pushed_at": "2026-10-16T00:00:00Z",
         "created_at": "2025-01-01T00:00:00Z", "topics": ["ai"],
         "archived": False, "fork": False}
    d.update(kw)
    return d


def test_parse_trending_reads_name_and_gain():
    html = page(("morluto", "rea", "248,962", "this week"), ("a", "b", "12", "today"))
    assert parse_trending(html) == [("morluto/rea", 248962), ("a/b", 12)]


def test_parse_trending_is_empty_on_rubbish():
    assert parse_trending("<html>no rows</html>") == []


@responses.activate
def test_trending_repos_join_the_topic_search_with_velocity():
    responses.add(responses.GET, "https://api.github.com/search/repositories",
                  json={"items": [repo_json("t/topic-hit")]}, status=200)
    responses.add(responses.GET, "https://github.com/trending",
                  body=page(("old", "big", "1,400", "this week")), status=200)
    responses.add(responses.GET, "https://api.github.com/repos/old/big",
                  json=repo_json("old/big", stargazers_count=90000), status=200)
    c = GitHubCollector(token="t", trending=("weekly",))
    sigs = {s.title: s for s in c.collect("AI", {"github": {"topics": ["mcp"]}})}
    assert set(sigs) == {"t/topic-hit", "old/big"}
    assert sigs["old/big"].stars == 90000
    assert sigs["old/big"].velocity == 200          # 1,400 stars in 7 days


@responses.activate
def test_a_repo_found_both_ways_is_kept_once_and_gets_the_trending_velocity():
    responses.add(responses.GET, "https://api.github.com/search/repositories",
                  json={"items": [repo_json("same/repo")]}, status=200)
    responses.add(responses.GET, "https://github.com/trending",
                  body=page(("same", "repo", "30", "today")), status=200)
    c = GitHubCollector(token="t", trending=("daily",))
    sigs = c.collect("AI", {"github": {"topics": ["mcp"]}})
    assert [s.title for s in sigs] == ["same/repo"]
    assert sigs[0].velocity == 30


@responses.activate
def test_no_topics_means_no_trending_either():
    c = GitHubCollector(token="t", trending=("weekly",))
    assert c.collect("Crypto", {"github": {"topics": []}}) == []
    assert len(responses.calls) == 0


@responses.activate
def test_a_dead_trending_page_warns_and_keeps_the_topic_results():
    responses.add(responses.GET, "https://api.github.com/search/repositories",
                  json={"items": [repo_json("t/topic-hit")]}, status=200)
    responses.add(responses.GET, "https://github.com/trending", status=503)
    c = GitHubCollector(token="t", trending=("weekly",))
    warned = []
    c.warn = warned.append
    sigs = c.collect("AI", {"github": {"topics": ["mcp"]}})
    assert [s.title for s in sigs] == ["t/topic-hit"]
    assert len(warned) == 1


@responses.activate
def test_a_page_that_parses_to_nothing_is_a_warning_not_silence():
    # GitHub reshaping the page must reach the banner, not quietly empty the net
    responses.add(responses.GET, "https://api.github.com/search/repositories",
                  json={"items": []}, status=200)
    responses.add(responses.GET, "https://github.com/trending",
                  body="<html>new layout</html>", status=200)
    c = GitHubCollector(token="t", trending=("weekly",))
    warned = []
    c.warn = warned.append
    c.collect("AI", {"github": {"topics": ["mcp"]}})
    assert len(warned) == 1


@responses.activate
def test_archived_and_forked_trending_repos_are_skipped():
    responses.add(responses.GET, "https://api.github.com/search/repositories",
                  json={"items": []}, status=200)
    responses.add(responses.GET, "https://github.com/trending",
                  body=page(("a", "arch", "5", "today"), ("a", "fork", "5", "today")), status=200)
    responses.add(responses.GET, "https://api.github.com/repos/a/arch",
                  json=repo_json("a/arch", archived=True), status=200)
    responses.add(responses.GET, "https://api.github.com/repos/a/fork",
                  json=repo_json("a/fork", fork=True), status=200)
    c = GitHubCollector(token="t", trending=("daily",))
    assert c.collect("AI", {"github": {"topics": ["mcp"]}}) == []


def test_attach_velocity_keeps_the_trending_rate_for_an_untracked_repo(monkeypatch):
    from topicparser import store
    from topicparser.models import Signal
    monkeypatch.setattr(store, "velocity", lambda name: None)
    s = Signal.make(source="github", title="old/big", description="", url="u",
                    date="", profile="AI", velocity=200)
    GitHubCollector(token="t").attach_velocity([s])
    assert s.velocity == 200


def test_main_turns_trending_on():
    # the collector defaults it off (every older test stays offline); the app must not
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
    assert 'trending=("daily", "weekly")' in src
