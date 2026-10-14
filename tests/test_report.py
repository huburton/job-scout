import json
import sqlite3

from scout import report


def offer(**kw):
    base = {"id": "x", "score": 76, "title": "Technicien helpdesk", "company": "Acme", "city": "Esch-sur-Alzette",
            "country": "lu", "commute_min": 63, "url": "https://example.test/o",
            "score_detail": json.dumps({"accessible": ["debutants acceptes"], "fit": "Fonce, c'est accessible."}),
            "extracted": json.dumps({"summary_fr": "Support aux utilisateurs."})}
    base.update(kw)
    return base


def test_offer_line_and_message():
    o = offer()
    assert report.offer_line(o) == "76 · Technicien helpdesk — Acme, Esch-sur-Alzette (63 min) · accessible"
    msg = report.offer_message(o)
    assert msg.splitlines() == ["Acme · Esch-sur-Alzette (63 min)", "Accessible : « debutants acceptes »",
                                "Pour toi : Fonce, c'est accessible."]


def db(rows):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE offers (id, score, title, company, city, country, commute_min, url, score_detail, "
                "extracted, notified DEFAULT 0, status DEFAULT 'new', closed DEFAULT 0)")
    for r in rows:
        con.execute("INSERT INTO offers (id, score, title, company, city, country, commute_min, url, score_detail, "
                    "extracted) VALUES (:id, :score, :title, :company, :city, :country, :commute_min, :url, "
                    ":score_detail, :extracted)", r)
    return con


def test_one_notification_per_run(monkeypatch):
    sent = []
    monkeypatch.setattr(report, "_push", lambda *a, **k: sent.append(a) or True)
    monkeypatch.setattr(report, "quiet_hours", lambda: False)
    con = db([offer(id=str(i), score=80 + i) for i in range(4)] + [offer(id="top", score=90)])
    report.notify_new(con, first_run=False)
    titles = [a[0] for a in sent]
    assert titles == ["90 · Technicien helpdesk", "5 nouvelles offres pour toi"]
    assert con.execute("SELECT COUNT(*) FROM offers WHERE notified = 1").fetchone()[0] == 5
    sent.clear()
    report.notify_new(con, first_run=False)
    assert sent == []  # déjà notifiées


def test_push_posts_to_ntfy_only_when_configured(monkeypatch):
    calls = []

    class Resp:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(report.httpx, "post", lambda url, **kw: calls.append((url, kw)) or Resp())
    monkeypatch.setattr(report.config, "NTFY_TOPIC", "")
    assert report._push("t", "m") is False and calls == []
    monkeypatch.setattr(report.config, "NTFY_TOPIC", "my-topic")
    monkeypatch.setattr(report.config, "NTFY_TOKEN", "tk_example")
    assert report._push("t", "m", priority=4) is True
    url, kw = calls[0]
    assert kw["json"]["topic"] == "my-topic" and kw["json"]["priority"] == 4
    assert kw["headers"] == {"Authorization": "Bearer tk_example"}
