"""Native first-party analytics: a tiny beacon, a privacy-preserving visitor
hash, and aggregation. No cookies, no third party."""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from collections import Counter
from urllib.parse import urlparse

from koyracloud.db import Database
from koyracloud.models import Hit

# Served at /_k/a.js. Reads its own data-site, sends a pageview on load and on
# SPA navigations via navigator.sendBeacon (text/plain → no CORS preflight).
BEACON_JS = """(function(){
  var s=document.currentScript;var site=s&&s.getAttribute('data-site');if(!site)return;
  var ep=new URL(s.src).origin+'/_k/e';
  function hit(){try{navigator.sendBeacon(ep,new Blob([JSON.stringify({
    site:site,path:location.pathname,ref:document.referrer,host:location.hostname
  })],{type:'text/plain'}));}catch(e){}}
  hit();
  var ps=history.pushState;history.pushState=function(){ps.apply(this,arguments);hit();};
  addEventListener('popstate',hit);
})();"""


def new_token() -> str:
    return secrets.token_urlsafe(12)


def visitor_hash(secret: str, site: str, ip: str, ua: str,
                 day: str | None = None) -> str:
    """Daily-rotating, cookieless visitor id. Rotates each day so visitors
    can't be tracked across days."""
    day = day or dt.date.today().isoformat()
    raw = f"{day}|{secret}|{site}|{ip}|{ua}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _ref_domain(referrer: str) -> str:
    if not referrer:
        return "direct"
    try:
        host = urlparse(referrer).netloc.lower()
        return host or "direct"
    except ValueError:
        return "direct"


def aggregate(db: Database, app_id: int, days: int = 7,
              now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=days)
    with db.session() as s:
        hits = s.query(Hit).filter(Hit.app_id == app_id, Hit.ts >= since).all()
    by_day: Counter = Counter()
    for h in hits:
        by_day[h.ts.date().isoformat()] += 1
    series = [{"date": (since + dt.timedelta(days=i)).date().isoformat(),
               "views": by_day.get((since + dt.timedelta(days=i)).date().isoformat(), 0)}
              for i in range(days + 1)]
    return {
        "views": len(hits),
        "visitors": len({h.visitor for h in hits}),
        "series": series,
        "top_paths": [{"path": p, "views": c}
                      for p, c in Counter(h.path for h in hits).most_common(8)],
        "top_referrers": [{"source": r, "views": c}
                          for r, c in Counter(_ref_domain(h.referrer) for h in hits).most_common(8)],
    }
