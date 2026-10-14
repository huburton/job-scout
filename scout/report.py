"""Outputs: ntfy notifications and the daily digest (Markdown file)."""
import datetime as dt
import json
import logging
from pathlib import Path

import httpx

from . import config

log = logging.getLogger("scout.report")
TOP_SCORE = 85       # exceptional offer: separate notification, high priority
DIGEST_LINES = 6     # lines of a run summary


def quiet_hours() -> bool:
    return not (7 <= dt.datetime.now().hour < 22)


def _push(title: str, message: str, click: str | None = None, priority: int = 3, actions: list | None = None) -> bool:
    """Publish to ntfy (JSON publishing API). Does nothing while SCOUT_NTFY_TOPIC is empty."""
    if not config.NTFY_TOPIC:
        return False
    body = {"topic": config.NTFY_TOPIC, "title": title, "message": message, "tags": ["briefcase"],
            "priority": priority}
    if click:
        body["click"] = click
    if actions:
        body["actions"] = actions
    headers = {"Authorization": f"Bearer {config.NTFY_TOKEN}"} if config.NTFY_TOKEN else {}
    try:
        r = httpx.post(config.NTFY_URL, json=body, headers=headers, timeout=15)
        r.raise_for_status()
        return True
    except httpx.HTTPError as e:
        log.warning("notification: %s", e)
        return False


def _where(o) -> str:
    trip = f" ({o['commute_min']} min)" if o["commute_min"] is not None else ""
    return f"{o['city'] or (o['country'] or '?').upper()}{trip}"


def offer_line(o) -> str:
    """One summary line: « 76 · Automaticien — Acme, Luxembourg (64 min) · accessible »"""
    accessible = " · accessible" if json.loads(o["score_detail"] or "{}").get("accessible") else ""
    return f"{o['score']} · {o['title'][:60]} — {o['company'] or '?'}, {_where(o)}{accessible}"


def offer_message(o) -> str:
    """Body of a single-offer notification: where, why it is accessible, the judge's opinion."""
    d = json.loads(o["score_detail"] or "{}")
    lines = [f"{o['company'] or '?'} · {_where(o)}"]
    if d.get("accessible"):
        lines.append("Accessible : « " + " », « ".join(d["accessible"][:2]) + " »")
    if d.get("fit"):
        lines.append(f"Pour toi : {d['fit']}")
    else:
        lines.append(json.loads(o["extracted"] or "{}").get("summary_fr", ""))
    return "\n".join(line for line in lines if line)


def _jobs_actions(*first: dict, label: str = "Jobs") -> list:
    """Buttons of a notification: the given ones, plus a link to the dashboard when SCOUT_DASHBOARD_URL is set."""
    extra = [{"action": "view", "label": label, "url": config.DASHBOARD_URL}] if config.DASHBOARD_URL else []
    return [*first, *extra]


def notify_new(con, first_run: bool):
    """One notification per run: the detail when there is a single offer, otherwise a summary; offers >= 85 on top,
    separately. Nothing at night (22:00-07:00: they go out on the 07:00 run)."""
    rows = con.execute("SELECT * FROM offers WHERE notified = 0 AND score >= ? AND status = 'new' AND closed = 0 "
                       "ORDER BY score DESC", (config.NOTIFY_MIN_SCORE,)).fetchall()
    if not rows or quiet_hours():
        return
    n = len(rows)
    if first_run:
        _push(f"job-scout actif : {n} offres ≥ {config.NOTIFY_MIN_SCORE}",
              "Premier passage terminé. Le détail est dans le récap du jour.", config.DASHBOARD_URL or None)
    else:
        for o in [o for o in rows if o["score"] >= TOP_SCORE][:3]:
            _push(f"{o['score']} · {o['title']}", offer_message(o), o["url"], 4,
                  _jobs_actions({"action": "view", "label": "Offre", "url": o["url"]}))
        if n == 1 and rows[0]["score"] < TOP_SCORE:
            o = rows[0]
            _push(f"{o['score']} · {o['title']}", offer_message(o), o["url"], 3,
                  _jobs_actions({"action": "view", "label": "Offre", "url": o["url"]}))
        elif n > 1:
            more = f"\n+{n - DIGEST_LINES} autres dans le récap" if n > DIGEST_LINES else ""
            _push(f"{n} nouvelles offres pour toi", "\n".join(offer_line(o) for o in rows[:DIGEST_LINES]) + more,
                  config.DASHBOARD_URL or None, 3, _jobs_actions(label="Voir les offres"))
    con.executemany("UPDATE offers SET notified = 1 WHERE id = ?", [(o["id"],) for o in rows])
    con.commit()


def write_digest(con, stats: dict):
    """Digest of the day: OUT_DIR/digests/YYYY-MM-DD.md (rewritten on every run)."""
    today = dt.date.today()
    start = dt.datetime.combine(today, dt.time()).timestamp()
    new = con.execute("SELECT * FROM offers WHERE first_seen >= ? AND score >= ? AND status != 'duplicate' "
                      "ORDER BY score DESC", (start, config.DIGEST_MIN_SCORE)).fetchall()
    tracked = con.execute("SELECT * FROM offers WHERE status IN ('interested', 'applied') AND closed = 0 "
                          "ORDER BY status, score DESC").fetchall()
    out = Path(config.OUT_DIR) / "digests"
    out.mkdir(parents=True, exist_ok=True)
    lines = [
        "---", "type: job-digest", f"date: {today.isoformat()}", f"new_matches: {len(new)}",
        f"analysed_today: {stats.get('analysed', 0)}", "source: job-scout", "---", "",
        f"# Job digest — {today.isoformat()}", "",
        f"Offers found by job-scout scored ≥ {config.DIGEST_MIN_SCORE}/100 for the profile. Scoring: chances of "
        f"being hired, interest of the job family, practicality (commute, contract), judge's opinion.", "",
        f"## New matches ({len(new)})", "",
    ]
    for o in new:
        detail = json.loads(o["score_detail"] or "{}")
        infos = "; ".join(detail.get("infos", []))
        summary = json.loads(o["extracted"] or "{}").get("summary_fr", "")
        lines.append(f"- **{o['score']}** · [{o['title']}]({o['url']}) — {o['company'] or '?'} · {_where(o)}. {summary}"
                     + (f" _({infos})_" if infos else ""))
    if not new:
        lines.append("_Nothing new above the threshold today._")
    if tracked:
        lines += ["", "## Tracked", ""]
        lines += [f"- `{o['status']}` · [{o['title']}]({o['url']}) — {o['company'] or '?'}" for o in tracked]
    lines += ["", "## Run stats", "", "```json", json.dumps(stats, ensure_ascii=False, indent=1), "```", ""]
    (out / f"{today.isoformat()}.md").write_text("\n".join(lines))
