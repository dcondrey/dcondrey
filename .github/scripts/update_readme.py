"""Rewrites the BLOG and ACTIVITY marker blocks in README.md from live sources.

Run on a schedule by .github/workflows/update-readme.yml. Stdlib only —
no dependency install step needed in CI.
"""

import os
import re
import urllib.request
import xml.etree.ElementTree as ET

README_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "README.md")
SITEMAP_URL = "https://writerslogic.com/sitemap.xml"
GITHUB_USER = "dcondrey"
MAX_BLOG_ITEMS = 3
MAX_ACTIVITY_ITEMS = 5

EVENT_LABELS = {
    "PullRequestEvent": {
        "opened": "Opened PR in [{repo}](https://github.com/{repo})",
        "closed_merged": "Merged PR in [{repo}](https://github.com/{repo})",
    },
    "IssuesEvent": {
        "opened": "Opened issue in [{repo}](https://github.com/{repo})",
    },
    "ReleaseEvent": {
        "published": "Released in [{repo}](https://github.com/{repo})",
    },
    "CreateEvent": {
        "repository": "Created [{repo}](https://github.com/{repo})",
    },
    "PublicEvent": {
        "_any": "Made [{repo}](https://github.com/{repo}) public",
    },
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "dcondrey-profile-readme-bot"})
    token = os.environ.get("GH_TOKEN")
    if token and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


ACRONYMS = {"ai", "zwc", "iiw", "loi", "mcp"}


def _title_from_slug(url):
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    words = slug.split("-")
    return " ".join(w.upper() if w in ACRONYMS else w.capitalize() for w in words)


def get_blog_items():
    # writerslogic.com has no RSS/Atom feed (both return the SPA's HTML shell).
    # sitemap.xml is real XML with per-page lastmod dates, so that's the source.
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    try:
        raw = fetch(SITEMAP_URL)
        root = ET.fromstring(raw)
    except Exception as exc:
        return [f"_Couldn't fetch the sitemap ({exc})._"]

    posts = []
    for url_el in root.findall("sm:url", ns):
        loc = (url_el.findtext("sm:loc", namespaces=ns) or "").strip()
        lastmod = (url_el.findtext("sm:lastmod", namespaces=ns) or "").strip()
        if "/blog/" not in loc or loc.rstrip("/").endswith("/blog"):
            continue
        posts.append((lastmod, loc))

    posts.sort(reverse=True)  # ISO dates sort correctly as strings
    if not posts:
        return ["_No posts found._"]

    lines = []
    for lastmod, loc in posts[:MAX_BLOG_ITEMS]:
        lines.append(f"- [{_title_from_slug(loc)}]({loc}) — {lastmod}")
    return lines


def get_activity_items():
    import json

    try:
        raw = fetch(f"https://api.github.com/users/{GITHUB_USER}/events/public")
        events = json.loads(raw)
    except Exception as exc:
        return [f"_Couldn't fetch recent activity ({exc})._"]

    lines = []
    seen = set()
    for event in events:
        etype = event.get("type")
        repo = event.get("repo", {}).get("name", "")
        payload = event.get("payload", {})
        action = payload.get("action", "")

        label = None
        rules = EVENT_LABELS.get(etype)
        if rules:
            if etype == "PullRequestEvent" and action == "closed" and payload.get("pull_request", {}).get("merged"):
                label = rules.get("closed_merged")
            else:
                label = rules.get(action) or rules.get("_any")

        if not label or not repo:
            continue

        text = label.format(repo=repo)
        dedupe_key = (etype, repo)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        lines.append(f"- {text}")
        if len(lines) >= MAX_ACTIVITY_ITEMS:
            break

    if not lines:
        lines = ["_No recent public activity._"]
    return lines


def get_owned_repos():
    """This user's owned, non-fork repos: [{"name": ..., "stargazerCount": ...}, ...]."""
    import json

    query = {
        "query": (
            'query { user(login: "%s") { repositories(first: 100, '
            "ownerAffiliations: OWNER, isFork: false) { "
            "nodes { name stargazerCount } } } }" % GITHUB_USER
        )
    }
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps(query).encode("utf-8"),
        headers={
            "User-Agent": "dcondrey-profile-readme-bot",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("GH_TOKEN required for the GraphQL API")
    req.add_header("Authorization", f"Bearer {token}")

    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    return data["data"]["user"]["repositories"]["nodes"]


def get_total_stars(repos=None):
    # Computed server-side instead of relying on the shared public
    # github-readme-stats.vercel.app instance, which is frequently
    # rate-limited/paused (observed DEPLOYMENT_PAUSED / 503 in practice).
    repos = get_owned_repos() if repos is None else repos
    return sum(r["stargazerCount"] for r in repos)


def stars_badge_line(total):
    label = "total%20stars"
    url = (
        f"https://img.shields.io/badge/{label}-{total}-yellow?"
        "style=flat-square&logo=github"
    )
    return f"[![Total Stars]({url})](https://github.com/{GITHUB_USER}?tab=repositories&sort=stargazers)"


def get_traffic_total(repos=None):
    """Aggregate 14-day views + clones across all owned repos.

    Needs a classic PAT with `repo` scope (TRAFFIC_TOKEN) — the traffic
    endpoints require push access to each repo, which the default
    GITHUB_TOKEN in a workflow only has for the repo it's running in.
    Returns None if TRAFFIC_TOKEN isn't set, so callers can render a
    "not configured" fallback instead of failing the whole run.
    """
    import json

    token = os.environ.get("TRAFFIC_TOKEN")
    if not token:
        return None

    repos = get_owned_repos() if repos is None else repos
    total_views = 0
    total_clones = 0
    counted = 0
    for repo in repos:
        name = repo["name"]
        repo_total = {}
        for endpoint in ("views", "clones"):
            url = f"https://api.github.com/repos/{GITHUB_USER}/{name}/traffic/{endpoint}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "dcondrey-profile-readme-bot",
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    repo_total[endpoint] = json.loads(resp.read()).get("count", 0)
            except Exception:
                repo_total[endpoint] = None  # this repo's traffic wasn't readable
        if repo_total.get("views") is not None or repo_total.get("clones") is not None:
            total_views += repo_total.get("views") or 0
            total_clones += repo_total.get("clones") or 0
            counted += 1

    return {"views": total_views, "clones": total_clones, "repo_count": counted}


def traffic_line(result):
    if result is None:
        return (
            "_Not configured — add a classic PAT with `repo` scope as the "
            "`TRAFFIC_TOKEN` repo secret to enable this._"
        )
    views_url = (
        f"https://img.shields.io/badge/14d%20views-{result['views']}-2ea44f"
        "?style=flat-square&logo=github"
    )
    clones_url = (
        f"https://img.shields.io/badge/14d%20clones-{result['clones']}-2ea44f"
        "?style=flat-square&logo=github"
    )
    return (
        f"![14-day views]({views_url}) ![14-day clones]({clones_url}) "
        f"_aggregated across {result['repo_count']} repos_"
    )


def replace_block(content, marker, lines):
    start, end = f"<!-- {marker}:START -->", f"<!-- {marker}:END -->"
    pattern = re.compile(rf"({re.escape(start)}\n)(.*?)\n?({re.escape(end)})", re.DOTALL)

    body = "\n".join(lines)
    # Use a replacement function, not a string: lines come from external data
    # (blog titles, repo names) and a string replacement would misinterpret a
    # stray "\1"-shaped sequence in that text as a backreference.
    new_content, count = pattern.subn(
        lambda m: f"{m.group(1)}{body}\n{m.group(3)}", content
    )
    if count == 0:
        raise RuntimeError(f"Markers for {marker} not found in README.md")
    return new_content


def main():
    with open(README_PATH, encoding="utf-8") as f:
        content = f.read()

    repos = get_owned_repos()

    content = replace_block(content, "BLOG", get_blog_items())
    content = replace_block(content, "ACTIVITY", get_activity_items())
    content = replace_block(content, "STARS", [stars_badge_line(get_total_stars(repos))])
    content = replace_block(content, "TRAFFIC", [traffic_line(get_traffic_total(repos))])

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    main()
