"""job-scout: collect -> prefilter -> details -> commute -> LLM analysis -> score -> notifications + digest.

Usage: python -m scout demo | run | serve | digest | reanalyse [min_score] | rejudge
  demo   : whole pipeline offline on synthetic offers (fake LLM, fake geo table), prints a ranked digest
  run    : one full pass
  serve  : HTTP API (SCOUT_BIND:SCOUT_PORT) + scheduled passes (config.RUN_HOURS)
"""
import datetime as dt
import json
import logging
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from . import config, db, demo, engines, extract, families, fit, geo, profile, report, score, sources

log = logging.getLogger("scout")
FULL_LIST_SOURCES = {"workday", "recruitee", "amazon", "ictjob", "list", "lsc", "demo"}  # complete lists: missing = closed
_run_lock = threading.Lock()
LAST_RUN: dict = {}


def run() -> dict:
    if not _run_lock.acquire(blocking=False):
        return {"error": "a run is already in progress"}
    try:
        return _run()
    finally:
        _run_lock.release()


def _offer(row) -> dict:
    offer = dict(row)
    offer["hints"] = json.loads(row["hints"] or "{}")
    offer["source_id"] = offer["id"][len(offer["source"]) + 1:]  # id = "source:source_id"
    return offer


def _save(con, offer: dict, commute, ex: dict, total: int, detail: dict):
    con.execute("""UPDATE offers SET city = ?, country = ?, description = ?, hints = ?, commute_min = ?,
                   extracted = ?, score = ?, score_detail = ? WHERE id = ?""",
                (offer.get("city"), offer.get("country"), offer.get("description"),
                 json.dumps(offer.get("hints") or {}, ensure_ascii=False), commute,
                 json.dumps(ex, ensure_ascii=False), total, json.dumps(detail, ensure_ascii=False), offer["id"]))


def _run() -> dict:
    con = db.connect()
    first_run = con.execute("SELECT COUNT(*) FROM offers").fetchone()[0] == 0
    stats = {"started": dt.datetime.now().isoformat(timespec="seconds"), "sources": {}, "analysed": 0,
             "skipped": 0, "errors": 0}
    collectors = demo.COLLECTORS if config.DEMO else {n: c for n, c in sources.COLLECTORS.items() if n in config.SOURCES}
    details = {} if config.DEMO else sources.DETAILS
    for name, collect in collectors.items():
        try:
            offers = collect()
        except Exception as e:
            log.exception("collector %s", name)
            stats["sources"][name] = f"error: {e}"
            continue
        new = sum(db.upsert(con, o) for o in offers)
        if name in FULL_LIST_SOURCES:
            for src in {o["source"] for o in offers}:
                db.close_missing(con, src, {f"{o['source']}:{o['source_id']}" for o in offers if o["source"] == src})
        con.commit()
        stats["sources"][name] = {"seen": len(offers), "new": new}
        log.info("%s: %d offers, %d new", name, len(offers), new)

    prof = profile.load()
    judge = engines.judge()
    stats["judge"] = judge.label
    pending = con.execute("SELECT * FROM offers WHERE extracted IS NULL AND status IN ('new', 'interested', 'applied') AND closed = 0 "
                          "ORDER BY first_seen DESC").fetchall()
    log.info("%d offers to analyse (judge: %s)", len(pending), judge.label)
    judged = 0
    for row in pending:
        offer = _offer(row)
        try:
            if judged and judged % 10 == 0 and not engines.still_free(judge):
                engines.release(judge)
                judge = engines.server()  # the user is back: the main model takes over, the big one comes back later
            family = families.from_title(offer["title"])
            reason = score.prefilter(offer)
            commute = None
            if not reason:
                detail_fn = details.get(offer["source"].split(":")[0])
                if detail_fn:
                    offer = detail_fn(offer)
                    time.sleep(0.5)
                commute = geo.commute(con, offer)
                if family:  # commute already prohibitive: no point analysing
                    reason = score.commute_gate(offer, family, commute, prof)
            ex = None
            if not reason:
                ex = extract.analyse(offer)
                family = families.resolve(offer["title"], ex.get("job_family"))
                reason = score.gate(ex, family, commute, offer, prof)
            if reason:
                _save(con, offer, commute, ex or {"skipped": reason}, 0, score.excluded_detail(reason, family))
                stats["skipped"] += 1
            else:
                try:
                    verdict = fit.judge(offer, ex, family, commute, prof, judge)
                except httpx.HTTPError:
                    if judge.label == "server":
                        raise
                    log.warning("big model unreachable: the main model takes over")
                    judge = engines.server()
                    verdict = fit.judge(offer, ex, family, commute, prof, judge)
                ex["_fit_engine"] = judge.label
                ex["_family"] = family
                ex["_fit"] = verdict
                total, detail = score.compute(ex, family, commute, offer, prof, verdict)
                _save(con, offer, commute, ex, total, detail)
                stats["analysed"] += 1
                judged += 1
            con.commit()
        except Exception:
            log.exception("analysis %s", offer["id"])
            stats["errors"] += 1

    if judge.label != "server":
        stats["rejudged"] = refit(con, prof, judge)
    engines.release(judge)
    report.notify_new(con, first_run)
    stats["finished"] = dt.datetime.now().isoformat(timespec="seconds")
    report.write_digest(con, stats)
    LAST_RUN.clear()
    LAST_RUN.update(stats)
    log.info("run finished: %s", json.dumps(stats, ensure_ascii=False))
    return stats


def refit(con, prof: dict, judge: engines.Engine) -> int:
    """Re-judge with the big model the offers the main model rated for lack of better (stops if the user returns)."""
    rows = con.execute("SELECT * FROM offers WHERE score > 0 AND closed = 0 "
                       "AND json_extract(extracted, '$._fit_engine') = 'server' ORDER BY score DESC LIMIT ?",
                       (config.REFIT_PER_RUN,)).fetchall()
    done = 0
    for row in rows:
        if done and done % 10 == 0 and not engines.still_free(judge):
            break
        offer = _offer(row)
        ex = json.loads(row["extracted"])
        try:
            verdict = fit.judge(offer, ex, ex["_family"], row["commute_min"], prof, judge)
            ex["_fit_engine"], ex["_fit"] = judge.label, verdict
            total, detail = score.compute(ex, ex["_family"], row["commute_min"], offer, prof, verdict)
            _save(con, offer, row["commute_min"], ex, total, detail)
            con.commit()
            done += 1
        except httpx.HTTPError:
            log.warning("big model unreachable: re-judging interrupted")
            break
        except Exception:
            log.exception("re-judge %s", offer["id"])
    return done


def rejudge() -> dict:
    """Recompute family, gates, judgement and score of already extracted offers (profile or scoring changed),
    without redoing the fact extraction (the slow part)."""
    with _run_lock:
        con = db.connect()
        prof = profile.load()
        judge = engines.judge()
        rows = con.execute("SELECT * FROM offers WHERE closed = 0 AND status IN ('new', 'interested', 'applied') "
                           "AND extracted IS NOT NULL AND json_extract(extracted, '$.job_family') IS NOT NULL").fetchall()
        stats = {"offers": len(rows), "excluded": 0, "rated": 0, "errors": 0, "judge": judge.label}
        log.info("rejudge: %d offers (judge: %s)", len(rows), judge.label)
        for row in rows:
            offer = _offer(row)
            ex = json.loads(row["extracted"])
            try:
                commute = row["commute_min"] if row["commute_min"] is not None else geo.commute(con, offer)
                family = families.resolve(offer["title"], ex.get("job_family"))
                reason = score.prefilter(offer) or score.gate(ex, family, commute, offer, prof)
                if reason:
                    _save(con, offer, commute, ex, 0, score.excluded_detail(reason, family))
                    stats["excluded"] += 1
                else:
                    try:
                        verdict = fit.judge(offer, ex, family, commute, prof, judge)
                    except httpx.HTTPError:
                        if judge.label == "server":
                            raise
                        log.warning("big model unavailable (user back?): the main model takes over")
                        judge = engines.server()
                        verdict = fit.judge(offer, ex, family, commute, prof, judge)
                    ex["_fit_engine"], ex["_family"], ex["_fit"] = judge.label, family, verdict
                    total, detail = score.compute(ex, family, commute, offer, prof, verdict)
                    _save(con, offer, commute, ex, total, detail)
                    stats["rated"] += 1
                con.commit()
            except Exception:
                log.exception("rejudge %s", offer["id"])
                stats["errors"] += 1
        engines.release(judge)
        report.write_digest(con, stats)
        log.info("rejudge finished: %s", json.dumps(stats, ensure_ascii=False))
        return stats


def refit_when_free():
    """Every 15 min outside a run: if the big model is available and offers are waiting for it, it re-judges them."""
    if not _run_lock.acquire(blocking=False):
        return
    try:
        con = db.connect()
        waiting = con.execute("SELECT COUNT(*) FROM offers WHERE score > 0 AND closed = 0 "
                              "AND json_extract(extracted, '$._fit_engine') = 'server'").fetchone()[0]
        if not waiting:
            return
        judge = engines.judge()
        if judge.label == "server":
            return
        n = refit(con, profile.load(), judge)
        engines.release(judge)
        log.info("big model: %d/%d offers re-judged", n, waiting)
        if n:
            report.write_digest(con, LAST_RUN)
    finally:
        _run_lock.release()


# --------------------------------------------------------------------------------------- API
PUBLIC_FIELDS = ("id", "source", "url", "title", "company", "city", "country", "posted_at", "first_seen",
                 "commute_min", "score", "status")
STATUSES = {"new", "interested", "applied", "dismissed"}


class Api(BaseHTTPRequestHandler):
    def _json(self, code: int, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        con = db.connect()
        if url.path == "/health":
            return self._json(200, {"ok": True, "last_run": LAST_RUN})
        if url.path == "/offers":
            statuses = [s for s in q.get("status", "new,interested,applied").split(",") if s in STATUSES]
            rows = con.execute(
                f"SELECT * FROM offers WHERE closed = 0 AND score >= ? AND status IN ({','.join('?' * len(statuses))}) "
                "ORDER BY score DESC, first_seen DESC LIMIT ?",
                (int(q.get("min_score", 0)), *statuses, min(int(q.get("limit", 200)), 1000))).fetchall()
            out = []
            for r in rows:
                item = {k: r[k] for k in PUBLIC_FIELDS}
                item["analysis"] = json.loads(r["extracted"] or "{}")
                item["score_detail"] = json.loads(r["score_detail"] or "{}")
                out.append(item)
            return self._json(200, {"offers": out})
        if url.path == "/stats":
            by_status = dict(con.execute("SELECT status, COUNT(*) FROM offers WHERE closed = 0 GROUP BY status").fetchall())
            by_source = dict(con.execute("SELECT source, COUNT(*) FROM offers WHERE closed = 0 GROUP BY source").fetchall())
            good = con.execute("SELECT COUNT(*) FROM offers WHERE closed = 0 AND score >= ?", (config.NOTIFY_MIN_SCORE,)).fetchone()[0]
            return self._json(200, {"by_status": by_status, "by_source": by_source, "matches": good, "last_run": LAST_RUN})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        parts = url.path.strip("/").split("/")
        if parts == ["run"]:
            threading.Thread(target=run, daemon=True).start()
            return self._json(202, {"ok": True})
        if parts == ["status"]:  # {"id": "...", "status": "..."} (ids may contain "/")
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                body = {}
            status, offer_id = body.get("status"), body.get("id")
            if status not in STATUSES or not offer_id:
                return self._json(400, {"error": f"id required and status in {sorted(STATUSES)}"})
            con = db.connect()
            n = con.execute("UPDATE offers SET status = ? WHERE id = ?", (status, offer_id)).rowcount
            con.commit()
            return self._json(200 if n else 404, {"ok": bool(n)})
        self._json(404, {"error": "not found"})


def scheduler():
    last = None
    while True:
        now = dt.datetime.now()
        slot = (now.date(), now.hour)
        if now.hour in config.RUN_HOURS and slot != last:
            last = slot
            run()
        elif now.minute % 15 == 0:
            try:
                refit_when_free()
            except Exception:
                log.exception("re-judging with the big model")
        time.sleep(60)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "run":
        print(json.dumps(run(), ensure_ascii=False, indent=1))
    elif cmd == "reanalyse":  # python -m scout reanalyse 50: re-analyse offers >= 50 on the next run
        con = db.connect()
        n = con.execute("UPDATE offers SET extracted = NULL, score = NULL, score_detail = NULL WHERE score >= ? "
                        "AND status IN ('new', 'interested', 'applied')", (int(sys.argv[2]) if len(sys.argv) > 2 else 50,)).rowcount
        con.commit()
        print(f"{n} offers to re-analyse")
    elif cmd == "rejudge":
        print(json.dumps(rejudge(), ensure_ascii=False, indent=1))
    elif cmd == "demo":
        with tempfile.TemporaryDirectory() as tmp:
            demo.setup(Path(tmp))
            logging.getLogger().setLevel(logging.WARNING)
            stats = run()
            print(demo.render(db.connect(), stats))
    elif cmd == "digest":
        report.write_digest(db.connect(), LAST_RUN)
    elif cmd == "serve":
        threading.Thread(target=scheduler, daemon=True).start()
        if db.connect().execute("SELECT COUNT(*) FROM offers").fetchone()[0] == 0:
            threading.Thread(target=run, daemon=True).start()  # first start: immediate run
        ThreadingHTTPServer((config.BIND, config.PORT), Api).serve_forever()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
