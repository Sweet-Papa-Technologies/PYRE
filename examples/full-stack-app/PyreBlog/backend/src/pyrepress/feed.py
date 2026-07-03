"""RSS 2.0 feed, hand-built XML.

Why string-building: the stdlib matrix confirms xml.etree works in-canister,
but RSS needs so little structure that explicit escaping is simpler to audit
than tree-building — and `email.utils` (the stdlib RFC-822 date formatter)
is broken in-canister (`_socket`), so dates are hand-formatted from
`time.gmtime`, which is consensus-time-backed and deterministic.
"""

import time as _time
from html import escape as _escape

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def xml_escape(s):
    """Escape text for XML PCDATA/attributes (&, <, >, quotes)."""
    return _escape(str(s), quote=True)


def rfc822(epoch_seconds):
    """RFC-822 date, e.g. 'Wed, 01 Jul 2026 12:34:56 GMT'."""
    t = _time.gmtime(int(epoch_seconds))
    return "%s, %02d %s %04d %02d:%02d:%02d GMT" % (
        _WEEKDAYS[t.tm_wday],
        t.tm_mday,
        _MONTHS[t.tm_mon - 1],
        t.tm_year,
        t.tm_hour,
        t.tm_min,
        t.tm_sec,
    )


def build_feed(meta, docs):
    """RSS 2.0 for the given published post docs (newest first)."""
    base = (meta.get("base_url") or "").rstrip("/")
    feed_link = base + "/api/feed.xml" if base else "/api/feed.xml"
    last_build = max((d["published_at"] for d in docs), default=0)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "<channel>",
        "<title>%s</title>" % xml_escape(meta.get("title", "")),
        "<link>%s</link>" % xml_escape(base or "/"),
        "<description>%s</description>" % xml_escape(meta.get("description", "")),
    ]
    if last_build:
        lines.append("<lastBuildDate>%s</lastBuildDate>" % rfc822(last_build))
    for doc in docs:
        link = "%s/posts/%s" % (base, doc["slug"]) if base else "/posts/%s" % doc["slug"]
        lines.extend(
            [
                "<item>",
                "<title>%s</title>" % xml_escape(doc["title"]),
                "<link>%s</link>" % xml_escape(link),
                '<guid isPermaLink="false">%s</guid>' % xml_escape(doc["slug"]),
                "<pubDate>%s</pubDate>" % rfc822(doc["published_at"]),
                "<description>%s</description>" % xml_escape(doc["html"]),
                "</item>",
            ]
        )
    lines.extend(["</channel>", "</rss>"])
    return "\n".join(lines)
