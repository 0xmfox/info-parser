import os
import re

from topicparser import i18n


def _link_label(url: str) -> tuple[str, str]:
    """(source_tag, readable_label) for a link — so the .md shows `owner/repo`
    or `@handle` as a clickable label instead of a raw URL."""
    m = re.search(r"github\.com/([^/]+/[^/?#]+)", url)
    if m:
        return "GitHub", m.group(1)
    m = re.search(r"(?:x|twitter)\.com/([^/?#]+)/status", url)
    if m:
        return "X", "@" + m.group(1)
    # A video is the one case where the host names NOTHING: "youtube.com" says neither
    # who published it nor that it is an hour of watching rather than a page of reading,
    # and that changes which topic the owner picks out of the file. Tag it like the
    # other two sources instead. (A lab's blog is fine as a host — "openai.com" does
    # say who published it.)
    if re.search(r"https?://(?:www\.)?(youtube\.com|youtu\.be)/", url, re.I):
        return "YouTube", i18n.t("md.watch")
    # Anything else is a blog: the HOST is what names it ("openai.com"), while the raw
    # address is a slug nobody reads. The href keeps the whole URL.
    m = re.search(r"https?://(?:www\.)?([^/?#]+)", url)
    if m:
        return "", m.group(1)
    return "", url


def _local_today() -> str:
    """The owner's calendar day, not UTC — the file is dated for the person saving
    it, and `Api._md_filename` already names it the same way."""
    from datetime import date
    return date.today().isoformat()


def write_markdown(topics: list[dict], path: str, date: str = None,
                   alerts: list[dict] = None, context: list[dict] = None) -> str:
    if date is None:
        date = _local_today()
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_markdown(topics, date=date, alerts=alerts, context=context))
    return path


# source sections, IDENTICAL to the tool feed (ui `renderResults`): Twitter first,
# then GitHub, then anything else. The .md is what the user reviews/picks against, so
# its structure must mirror the feed exactly — no profile grouping (the feed has none).
_SOURCE_KEYS = [("tw", "source.twitter"), ("gh", "source.github"),
                ("feed", "kind.feeds"), ("pod", "kind.interviews"),
                ("other", "source.other")]


# THEMES — a sub-layer INSIDE a source section, never a replacement for it. Seventy
# GitHub topics in one score-ordered wall is what the owner asked to break up; the
# sections themselves still mirror the feed exactly.
#
# Matched on the TITLE plus the repo's own GitHub tags, both of which are English by
# construction (`_base.txt` demands an English title, tags come from the API). The
# `why` is deliberately NOT read: it is written in the interface language, so keying on
# it would make the grouping work in Ukrainian and quietly stop working in English.
#
# FIRST match wins, so the order below is the decision. `learning` leads because a
# curated list of agent skills is a reading pile before it is either; `skills` beats
# `agents` for the same reason GATE A separates them — a thing you install to code
# better is not a thing for building agents.
_THEMES = [
    ("learning", "md.theme.learning",
     ("awesome", "guide", "tutorial", "course", "roadmap", "cheatsheet", "handbook",
      "notebook", "beginner", "curated", "prompt-vault", "prompts", "learn")),
    ("skills", "md.theme.skills",
     ("skill", "plugin", "claude-code", "claude code", "cursor", "codex", "subagent",
      "slash-command", "extension")),
    ("agents", "md.theme.agents",
     ("agent", "agentic", "harness", "orchestrat", "mcp", "autonomous", "swarm",
      "crew", "workflow")),
    ("media", "md.theme.media",
     ("video", "image", "photo", "3d", "audio", "music", "voice", "render",
      "diffusion", "lora", "comfyui", "animation", "avatar", "film", "art")),
    ("models", "md.theme.models",
     ("model", "llm", "inference", "quantiz", "training", "fine-tun", "benchmark",
      "gpu", "chip", "transformer", "embedding", "dataset")),
    ("tools", "md.theme.tools",
     ("cli", "sdk", "api", "database", "backend", "editor", "dashboard", "terminal",
      "proxy", "gateway", "framework", "library", "server", "toolkit", "browser")),
    ("other", "md.theme.other", ()),
]

# Below this many topics a section stays FLAT. A section of five reads fine as one
# list, and splitting it produces headings with one item under them, which is more
# furniture than the wall it was meant to fix.
THEME_MIN = 8


def _theme(t: dict) -> str:
    hay = " ".join([_oneline(t.get("title")), " ".join(t.get("topics") or [])]).lower()
    for key, _label, pats in _THEMES:
        if any(p in hay for p in pats):
            return key
    return "other"


# GITHUB ONLY, and that is a measured limit rather than a preference. A repo names
# itself ("watch-skill", "harnessrouter") and carries its own tags; a news headline
# names an event, so the same keywords misfile it — over the 08-29 export, "OpenAI
# ends partnership with Cursor" landed in skills and "Kimi K3 model variants and
# orchestration" in agents. The wall the owner asked to break up is the GitHub one
# (70 of that file's topics); fourteen tweets read fine as one list.
_THEMED_SOURCES = ("gh",)


def _themed_body(rows: list[dict], source: str = "gh") -> str:
    """Rows of ONE source section, grouped into themes and joined.

    Falls back to the flat list when the source is not themed, when the section is
    short, or when everything lands in one theme: a single heading over the whole
    section says nothing."""
    buckets: dict[str, list[dict]] = {}
    for t in rows:
        buckets.setdefault(_theme(t), []).append(t)
    if source not in _THEMED_SOURCES or len(rows) < THEME_MIN or len(buckets) < 2:
        return _POST_GAP.join(_topic_block(t) for t in rows)
    out = []
    for key, label, _pats in _THEMES:
        got = buckets.get(key)
        if not got:
            continue
        head = f"{_THEME_RULE}  {i18n.t(label)}  ({len(got)})  {_THEME_RULE}"
        out.append(head + "\n\n\n"
                   + _POST_GAP.join(_topic_block(t) for t in got))
    return "\n\n\n".join(out)


def _summary_label(key: str) -> str:
    """The summary line reads "{n} from {source}", which in an inflected language is not
    the same word as the section heading: in Ukrainian the heading form is wrong there
    and the genitive is right.
    A catalogue may supply a `<key>_of` variant; English has no case to change, so it
    supplies none and this falls straight back to the heading."""
    of = i18n.t(key + "_of")
    return i18n.t(key) if of == key + "_of" else of


def _topic_source(t: dict) -> str:
    """'tw' / 'gh' / 'feed' / 'pod' / 'other', mirroring the feed's `sourceOf`.

    The topic CARRIES its source now (the ranker reads it off the signal). The link
    sniffing below is only the fallback for rows written before that column existed:
    it cannot tell a lab blog from any other address, which is exactly why official
    sources used to pile up in the catch-all section. It cannot tell a podcast from a
    lab either — a row written before `pod` existed stays `feed`, which is where it
    has always been shown."""
    from topicparser.ranker import _SOURCE_RANK  # one list, defined where it is stamped
    known = (t.get("source") or "").lower()
    if known in set(_SOURCE_RANK):
        return known
    links = t.get("links") or []
    l = (links[0] if links else "").lower()
    if "github.com" in l:
        return "gh"
    if "x.com" in l or "twitter.com" in l:
        return "tw"
    return "other"


# readability furniture (the file is a wall of many topics — space it out)
_RULE = "═" * 24            # boxed section header (box-drawing, not `=`, so no setext H1)
_POST_SEP = "· · · · · · · · · · · · ·"   # soft divider between posts in a section
_THEME_RULE = "─" * 8        # theme sub-header INSIDE a section (lighter than `═`)
# Blank lines EACH SIDE of that divider. One was not enough: a run of thirty topics
# read as a single wall, which is the state the owner reviews the file in.
_POST_GAP = f"\n\n\n{_POST_SEP}\n\n\n"


def _oneline(s: str) -> str:
    """A heading is a LINE. A `why` or a title carrying a newline ends its heading
    early and orphans the rest of the text at the top level of the file."""
    return " ".join(str(s or "").split())


def _topic_block(t: dict) -> str:
    b = [f"### {_oneline(t['title'])}", ""]
    if t.get("score") is not None:
        b += [f"`{i18n.t('md.score', score=t['score'])}`", ""]
    # Traction on its OWN lines, and the two numbers are separate facts: `stars` is how
    # many people have it, `velocity` is how fast that is moving. The file used to carry
    # neither, although the topic already holds both — so a GitHub topic read as a bare
    # title and a score, with nothing to judge it by.
    b += _traction_lines(t)
    if t.get("why"):
        b += [t["why"], ""]
    for l in t.get("links", []):
        src, label = _link_label(l)
        prefix = f"**{src}** " if src else ""
        b.append(f"→ {prefix}[{label}]({l})")
    return "\n".join(b)


def _traction_lines(t: dict) -> list[str]:
    """`Stars:` and `Growth:`, each on its own line, then a blank one.

    Growth is OMITTED rather than shown as zero when it is unknown: velocity needs two
    star snapshots at least 12 h apart, so a repo reaching a topic for the first time
    genuinely has none yet, and "+0 ★/day" would read as "nobody is starring it"."""
    out = []
    if t.get("stars") is not None:
        out.append(f"{i18n.t('md.stars_label')}: {_stars(t['stars'])}")
    if t.get("velocity") is not None:
        out.append(f"{i18n.t('md.growth_label')}: +{round(t['velocity'])} "
                   + i18n.t("md.velocity_unit"))
    return out + [""] if out else out


def _stars(n) -> str:
    """2654 -> '2 654' (uk) or '2,654' (en). The separator comes from the catalogue,
    same as the feed's — hardcoding it here meant the .md and the screen could show
    the same number two different ways."""
    return f"{int(n):,}".replace(",", i18n.t("locale.thousands"))


def _alert_block(a: dict) -> str:
    """One trending repo. Not a topic — no score, no kept flag; it comes off the
    watchlist and bypasses the whole topic pipeline, so it gets its own shape."""
    b = [f"### [{a.get('repo','')}]({a.get('url','')})"]
    metric = []
    if a.get("velocity") is not None:
        metric.append(f"`+{round(a['velocity'])} " + i18n.t('md.velocity_unit') + "`")
    if a.get("stars") is not None:
        metric.append(f"`{_stars(a['stars'])} ★`")
    if metric:
        b.append(" · ".join(metric))
    if a.get("description"):
        b += ["", a["description"]]
    return "\n".join(b)


def _trending_section(alerts: list[dict]) -> str:
    rows = sorted(alerts, key=lambda a: -(a.get("velocity") or 0))
    head = f"{_RULE}\n##  {i18n.t('md.trending_heading')}  ({len(rows)})\n{_RULE}"
    body = _POST_GAP.join(_alert_block(a) for a in rows)
    return f"{head}\n\n{body}"


def _context_section(context: list[dict]) -> str:
    """Raw announcements that were NOT scored: a lab's own tweets, its release and
    commit feeds. Not topics; material the writing project combines with one."""
    rows = sorted(context, key=lambda c: c.get("date") or "", reverse=True)
    head = (f"{_RULE}\n##  {i18n.t('md.context_heading')}  ({len(rows)})\n{_RULE}\n\n"
            f"_{i18n.t('md.context_note')}_")
    lines = []
    for c in rows:
        day = (c.get("date") or "")[:10]
        # whole, not cut: a lab's long post is the first source a topic is built on
        text = " ".join((c.get("text") or "").split())
        title = c.get("title") or ""
        body = f"**{title}** {text}".strip() if text and text != title else f"**{title}**"
        extra = _media_lines(c.get("media")) + _reply_lines(c.get("reply"))
        lines.append(f"- `{day}` {body} ({c.get('url', '')})"
                     + "".join("\n  " + e for e in extra))
    return head + "\n\n" + "\n".join(lines)


def _media_lines(media) -> list[str]:
    """One line per picture / video / article, with the links Claude can open."""
    out = []
    for m in media or []:
        kind = m.get("type")
        if kind == "article":
            out.append(f"{i18n.t('md.media_article')}: «{m.get('title', '')}»")
        elif kind == "photo":
            out.append(f"{i18n.t('md.media_photo')}: {m.get('url', '')}")
        elif kind in ("video", "gif"):
            what = i18n.t("md.media_" + kind)
            if m.get("seconds"):
                what += ", " + i18n.t("md.seconds", n=m["seconds"])
            line = f"{what}: {m.get('video') or m.get('url', '')}"
            if m.get("video") and m.get("url"):
                line += f" ({i18n.t('md.frame')}: {m['url']})"
            out.append(line)
    return out


def _reply_lines(reply) -> list[str]:
    if not reply:
        return []
    return [f"{i18n.t('md.author_reply')}: " + " ".join(reply.split())]


def to_markdown(topics: list[dict], date: str, alerts: list[dict] = None,
                context: list[dict] = None) -> str:
    tail = ("\n" + _context_section(context) + "\n") if context else ""
    # trending leads the file, exactly as it leads the feed
    trending = _trending_section(alerts) if alerts else ""

    title = f"# {i18n.t('md.title', date=date)}"
    kept = [t for t in topics if t.get("kept", 1)]
    if not kept:
        head = f"{title}\n\n_{i18n.t('md.empty')}_\n"
        return (f"{head}\n{trending}\n" if trending else head) + tail

    # group by SOURCE (not profile) so the file mirrors the tool feed exactly
    groups: dict[str, list[dict]] = {key: [] for key, _ in _SOURCE_KEYS}
    for t in kept:
        groups[_topic_source(t)].append(t)

    present = [(key, i18n.t(k), _summary_label(k)) for key, k in _SOURCE_KEYS if groups[key]]
    summary = " · ".join(i18n.t("md.summary_item", n=len(groups[key]), source=of)
                         for key, label, of in present)
    header = f"{title}\n\n**{summary}**"

    sections = []
    for key, label, _of in present:
        rows = sorted(groups[key], key=lambda x: -(x.get("score") or 0))
        head = f"{_RULE}\n##  {label.upper()}  ({len(rows)})\n{_RULE}"
        body = _themed_body(rows, key)
        sections.append(f"{head}\n\n{body}")

    if trending:
        sections.insert(0, trending)
    return header + "\n\n" + "\n\n".join(sections) + "\n" + tail


# --- trends -----------------------------------------------------------------------
# A separate file for a separate job: every fresh post of the owner's list of X authors
# who get views, unjudged, so Claude can read what is moving right now. No sections,
# no scores, newest first.
def _trend_block(p, usual=None, followers=False) -> str:
    m = p.metrics or {}
    nums = " · ".join(f"{_stars(m[k])} {i18n.t('trends.' + k)}"
                      for k in ("views", "likes", "bookmarks") if k in m)
    if followers and getattr(p, "followers", None) is not None:
        nums += f" · {_stars(p.followers)} {i18n.t('trends.followers')}"
    if usual and m.get("views") is not None:
        x = f"{m['views'] / usual:.1f}".rstrip("0").rstrip(".")
        nums += f" · ×{x} {i18n.t('trends.vs_usual')}"
    when = (p.date or "")[:16].replace("T", " ")
    head = f"### {p.title} · {when}" if when else f"### {p.title}"
    text = getattr(p, "full_text", "") or p.description
    extra = _media_lines(getattr(p, "media", None)) + _reply_lines(getattr(p, "reply", ""))
    return "\n".join([head] + ([f"`{nums}`"] if nums else []) + ["", text]
                     + ([""] + extra if extra else []) + ["", p.url])


# How a post did against its author's OWN usual is the half of "is this a trend" that
# Claude cannot see by eye in 700 posts: the median views of that author in this file.
# Under three posts there is no usual to speak of, so no ratio is printed at all.
_USUAL_MIN_POSTS = 3


def _usual_views(posts: list) -> dict:
    from statistics import median
    by: dict[str, list] = {}
    for p in posts:
        v = (p.metrics or {}).get("views")
        if v is not None:
            by.setdefault(p.title.lower(), []).append(v)
    return {a: median(vs) for a, vs in by.items() if len(vs) >= _USUAL_MIN_POSTS and median(vs) > 0}


# The file runs to ~700 posts, too many to read whole in every chat. What beat its
# author's usual this many times leads the file, hottest first, and the agent reads that
# part closely and searches the rest; every post is still in the file, once.
_HOT_X = 2
# A pinned post rides on top of every author's timeline however old it is, and with
# months of views it read as ×1646 and led the file (10-26: a May post first, 9 of the
# 139 "took off" older than two weeks). The hot section is about NOW; old posts stay in
# the rest, once.
_HOT_MAX_DAYS = 14


def _days_old(p, today: str):
    from datetime import date as _d
    try:
        return (_d.fromisoformat(today) - _d.fromisoformat((p.date or "")[:10])).days
    except ValueError:
        return None


def _trends_parts(posts: list, date: str, radar=None, official=None, max_days=None):
    """(head of the file, posts for the rest). `max_days` cuts what is SHOWN: the tail of
    every timeline is the three old posts that stopped the scroll, plus pinned ones. They
    still count towards the author's usual, which needs the history."""
    rows = sorted(posts, key=lambda p: p.date or "", reverse=True)
    usual = _usual_views(rows)

    def in_window(p):
        age = _days_old(p, date)
        return max_days is None or age is None or age <= max_days

    def ratio(p):
        u, v = usual.get(p.title.lower()), (p.metrics or {}).get("views")
        return v / u if u and v is not None else 0

    def is_hot(p):
        age = _days_old(p, date)
        return ratio(p) >= _HOT_X and age is not None and age <= _HOT_MAX_DAYS

    rows = [p for p in rows if in_window(p)]
    hot = sorted((p for p in rows if is_hot(p)), key=ratio, reverse=True)
    rest = [p for p in rows if not is_hot(p)]
    block = lambda ps: _POST_GAP.join(_trend_block(p, usual.get(p.title.lower())) for p in ps)
    summary = i18n.t("trends.md_summary", posts=len(rows),
                     authors=len({p.title.lower() for p in rows}))
    out = f"# {i18n.t('trends.md_title', date=date)}\n\n**{summary}**\n\n"
    # Radar goes FIRST: a small account's post that took off is the earliest sign of a
    # wave, and it is short, so it costs the agent little to read whole.
    if radar:
        out += (f"{_RULE}\n##  {i18n.t('trends.radar_heading', n=len(radar))}\n{_RULE}\n\n"
                + _POST_GAP.join(_trend_block(p, followers=True) for p in radar) + "\n\n\n")
    if hot:
        out += (f"{_RULE}\n##  {i18n.t('trends.hot_heading', n=len(hot))}\n{_RULE}\n\n"
                + block(hot) + "\n\n\n")
    labs = sorted((p for p in official or [] if in_window(p)),
                  key=lambda p: p.date or "", reverse=True)
    if labs:
        out += (f"{_RULE}\n##  {i18n.t('trends.official_heading', n=len(labs))}\n{_RULE}\n\n"
                + _POST_GAP.join(_trend_block(p) for p in labs) + "\n\n\n")
    return out, block(rest), bool(hot)


def trends_markdown(posts: list, date: str, radar: list = None, official: list = None,
                    max_days: int = None) -> str:
    head, rest, hot = _trends_parts(posts, date, radar, official, max_days)
    heading = f"{_RULE}\n##  {i18n.t('trends.rest_heading')}\n{_RULE}\n\n" if hot else ""
    return head + heading + rest + "\n"


def rest_path(path: str) -> str:
    folder, name = os.path.split(path)
    return os.path.join(folder, "rest-" + (name[7:] if name.startswith("trends-") else name))


def write_trends(posts: list, path: str, date: str = None, radar: list = None,
                 official: list = None, max_days: int = None) -> str:
    """Two files: the part that is read whole, and "the rest", which is only searched and
    was 62 % of a 1.5 MB file."""
    date = date or _local_today()
    head, rest, _ = _trends_parts(posts, date, radar, official, max_days)
    with open(path, "w", encoding="utf-8") as f:
        f.write(head)
    with open(rest_path(path), "w", encoding="utf-8") as f:
        f.write(f"# {i18n.t('trends.rest_heading')} · {date}\n\n{rest}\n")
    return path
