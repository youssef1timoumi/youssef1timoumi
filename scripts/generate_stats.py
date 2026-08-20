#!/usr/bin/env python3
"""Draw stats.svg -- the contribution year, as a hero total and a sparkline.

Standard library only, so the workflow needs no install step.

Two ways in, same shape of data out:
  * GITHUB_TOKEN set (how the workflow runs it) -> the GraphQL API.
  * no token (how you run it by hand) -> the public contributions fragment
    at github.com/users/<login>/contributions, which needs no auth.

The window is pinned to whole UTC days rather than measured from request time.
Otherwise "the past year" drifts by a few hours every night, days slide between
week buckets, the sparkline moves a fraction of a pixel, and the workflow
commits noise forever.

Env:
  GH_LOGIN      user to summarise (default: youssef1timoumi)
  GITHUB_TOKEN  optional; uses the API instead of the public page
"""
import base64
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, "scripts", "fonts")
OUT = os.path.join(ROOT, "stats.svg")
LOGIN = os.environ.get("GH_LOGIN") or "youssef1timoumi"

WIDTH, HEIGHT = 620, 148
REVEAL = 1.30           # seconds; matches the portrait's typing cadence
UA = f"{LOGIN}-profile-stats"

# The portrait's ink is the data ink, so the whole header reads as one material.
LIGHT = dict(data="#6e7681", emph="#424a53", dim="#8c959f", surface="#ffffff")
DARK = dict(data="#c9d1d9", emph="#f0f6fc", dim="#8b949e", surface="#0d1117")
MONO = ("JBMono,ui-monospace,SFMono-Regular,Menlo,Consolas,"
        "&apos;Liberation Mono&apos;,monospace")

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { contributionCount date } }
      }
    }
  }
}
"""


# ------------------------------------------------------------------ data

def window():
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=364)
    return f"{start.isoformat()}T00:00:00Z", f"{today.isoformat()}T23:59:59Z"


def get(url, headers=None, data=None):
    req = urllib.request.Request(url, data=data,
                                 headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def from_api(token):
    since, until = window()
    body = json.dumps({"query": QUERY,
                       "variables": {"login": LOGIN, "from": since,
                                     "to": until}}).encode()
    payload = json.loads(get("https://api.github.com/graphql",
                             {"Authorization": f"bearer {token}",
                              "Content-Type": "application/json"}, body))
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    user = (payload.get("data") or {}).get("user")
    if not user:
        raise RuntimeError(f"no such user: {LOGIN}")
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    return [(d["date"], d["contributionCount"])
            for w in weeks for d in w["contributionDays"]]


def from_page():
    """The calendar GitHub renders on the profile, without a token.

    The <td> carries the date, the <tool-tip> that points at it carries the
    count -- 'No contributions on ...' or 'N contributions on ...'.
    """
    html = get(f"https://github.com/users/{LOGIN}/contributions").decode()
    counts = {}
    for cell, text in re.findall(
            r'<tool-tip[^>]*\bfor="(contribution-day-component-[\d-]+)"[^>]*>'
            r'([^<]*)</tool-tip>', html):
        m = re.match(r"\s*([\d,]+)\s+contribution", unescape(text))
        counts[cell] = int(m.group(1).replace(",", "")) if m else 0

    days = []
    for td in re.findall(r"<td[^>]*ContributionCalendar-day[^>]*>", html):
        date = re.search(r'data-date="([\d-]+)"', td)
        cell = re.search(r'id="(contribution-day-component-[\d-]+)"', td)
        if date:
            days.append((date.group(1), counts.get(cell.group(1) if cell
                                                   else "", 0)))
    if not days:
        raise SystemExit(f"could not read the calendar for {LOGIN}")
    return days


def collect():
    """The API when a token is around, the public calendar otherwise.

    The API is the better source -- it is what the profile itself reports --
    but a page-shaped fallback means a token problem degrades to slightly
    staler numbers instead of a red workflow and a stale graphic.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        try:
            return from_api(token)
        except Exception as exc:                      # noqa: BLE001
            print(f"API path failed ({exc}); reading the public calendar")
    return from_page()


def summarise(days):
    """Days -> the three numbers and the week buckets the sparkline draws."""
    start = datetime.fromisoformat(window()[0][:10]).date()
    days = [(d, c) for d, c in sorted(set(days))
            if datetime.fromisoformat(d).date() >= start]
    if not days:
        raise SystemExit(f"no contribution days in range for {LOGIN}")

    first = datetime.fromisoformat(days[0][0]).date()
    first -= timedelta(days=(first.weekday() + 1) % 7)   # back to Sunday
    weekly = {}
    for d, c in days:
        bucket = (datetime.fromisoformat(d).date() - first).days // 7
        weekly[bucket] = weekly.get(bucket, 0) + c

    return dict(total=sum(c for _, c in days),
                active=sum(1 for _, c in days if c > 0),
                best_week=max(weekly.values()) if weekly else 0,
                weekly=[weekly.get(i, 0) for i in range(max(weekly) + 1)])


# --------------------------------------------------------------- drawing

def font_face(filename, weight):
    """One @font-face with the subset inlined.

    An external font URL cannot work here: the SVG is loaded through <img>,
    and browsers refuse to fetch subresources for an image document.
    """
    with open(os.path.join(FONT_DIR, filename), "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return (f"@font-face{{font-family:JBMono;font-style:normal;"
            f"font-weight:{weight};font-display:block;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")


def style():
    def ink(t):
        return (f".d-f{{fill:{t['data']}}}.d-s{{stroke:{t['data']}}}"
                f".e-f{{fill:{t['emph']}}}.m-f{{fill:{t['dim']}}}"
                f".r{{stroke:{t['surface']}}}")
    return (f"<style>{font_face('jbmono-400.woff2', 400)}"
            f"{font_face('jbmono-600.woff2', 600)}"
            f"{ink(LIGHT)}.w{{fill:{LIGHT['data']};opacity:.13}}"
            f"@media(prefers-color-scheme:dark){{{ink(DARK)}"
            f".w{{fill:{DARK['data']};opacity:.16}}}}</style>")


def fade(delay, dur=0.45):
    return (f'<animate attributeName="opacity" from="0" to="1" '
            f'begin="{delay:.2f}s" dur="{dur}s" fill="freeze"/>')


def text(x, y, body, size, cls, anchor="start", bold=False):
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    w = ' font-weight="600"' if bold else ""
    return f'<text x="{x}" y="{y}" class="{cls}" font-size="{size}"{a}{w}>{body}</text>'


def draw(s):
    weekly = s["weekly"] or [0]
    peak = max(weekly) or 1
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
         f'height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" fill="none" '
         f'font-family="{MONO}">', style()]

    p.append(f'<g opacity="0">{fade(0.10)}'
             + text(0, 50, s["total"], 52, "e-f", bold=True)
             + text(0, 72, "contributions in the last year", 12, "m-f")
             + "</g>")
    for i, (val, lab) in enumerate([(s["active"], "active days"),
                                    (s["best_week"], "best week")]):
        p.append(f'<g opacity="0">{fade(0.30 + i * 0.12)}'
                 + text(WIDTH, 30 + i * 40, val, 19, "e-f", "end", bold=True)
                 + text(WIDTH, 47 + i * 40, lab, 11, "m-f", "end") + "</g>")

    base, top = HEIGHT - 10, HEIGHT - 58
    span, step = base - top, WIDTH / max(len(weekly) - 1, 1)
    pts = [(i * step, base - (v / peak) * span) for i, v in enumerate(weekly)]
    line = "".join(f"L{x:.1f} {y:.1f}" for x, y in pts)
    tail = "".join(f"L{x:.1f} {y:.1f}" for x, y in pts[1:])

    p.append(f'<clipPath id="sp"><rect x="0" y="{top - 6}" '
             f'height="{span + 8}" width="0"><animate attributeName="width" '
             f'from="0" to="{WIDTH}" begin="0.50s" dur="{REVEAL}s" '
             f'fill="freeze"/></rect></clipPath>')
    p.append('<g clip-path="url(#sp)">')
    p.append(f'<path d="M{pts[0][0]:.1f} {base:.1f}{line}'
             f'L{pts[-1][0]:.1f} {base:.1f}Z" class="w"/>')
    p.append(f'<path d="M{pts[0][0]:.1f} {pts[0][1]:.1f}{tail}" '
             f'class="d-s" stroke-width="2" stroke-linejoin="round" '
             f'stroke-linecap="round"/>')
    p.append("</g>")
    # the cursor that rides the reveal's edge, as in the portrait
    p.append(f'<rect y="{top - 6}" width="2" height="{span + 8}" class="d-f" '
             f'opacity="0"><animate attributeName="x" from="0" to="{WIDTH}" '
             f'begin="0.50s" dur="{REVEAL}s" fill="freeze"/>'
             f'<set attributeName="opacity" to="0.55" begin="0.50s"/>'
             f'<set attributeName="opacity" to="0" '
             f'begin="{0.50 + REVEAL:.2f}s"/></rect>')
    ex, ey = pts[-1]
    p.append(f'<circle cx="{ex - 2:.1f}" cy="{ey:.1f}" r="4.5" class="e-f r" '
             f'stroke-width="2" opacity="0">{fade(0.50 + REVEAL, 0.35)}</circle>')
    p.append("</svg>")
    return "".join(p)


def main():
    s = summarise(collect())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(draw(s))
    print(f"stats.svg: {s['total']} contributions, {s['active']} active days, "
          f"best week {s['best_week']}, {len(s['weekly'])} weeks")


if __name__ == "__main__":
    main()
