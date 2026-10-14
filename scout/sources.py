"""Collectors. Each collector returns a list of dicts:
{source, source_id, url, title, company, city, country, lat, lon, posted_at, description, hints}.
Public APIs / open feeds at low frequency only (see README: sources and limits).
"""
import datetime as dt
import html
import logging
import re
import time

import httpx

from . import config

log = logging.getLogger("scout.sources")
HEADERS = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}


def _client() -> httpx.Client:
    return httpx.Client(headers=HEADERS, timeout=40, follow_redirects=True)


def strip_html(text: str | None) -> str:
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t \xa0]+", " ", html.unescape(text)).strip()


def _iso(ms: int | None) -> str | None:
    return dt.datetime.fromtimestamp(ms / 1000).date().isoformat() if ms else None


# ----------------------------------------------------------------------------- EURES (ADEM, France Travail…)
EURES = "https://europa.eu/eures/api/jv-searchengine/public"


def eures() -> list[dict]:
    offers: dict[str, dict] = {}
    with _client() as c:
        for locations, isco, keywords in config.EURES_QUERIES:
            page = 1
            while len(offers) < 5000:
                body = {
                    "resultsPerPage": 50, "page": page, "sortSearch": "MOST_RECENT",
                    "keywords": [{"keyword": k, "specificSearchCode": "EVERYWHERE"} for k in keywords],
                    "publicationPeriod": None, "occupationUris": [f"http://data.europa.eu/esco/isco/{g}" for g in isco],
                    "skillUris": [], "requiredExperienceCodes": [], "positionScheduleCodes": [], "sectorCodes": [],
                    "educationAndQualificationLevelCodes": [], "positionOfferingCodes": [], "locationCodes": locations,
                    "euresFlagCodes": [], "otherBenefitsCodes": [], "requiredLanguages": [], "minNumberPost": None,
                    "sessionId": "job-scout",
                }
                r = c.post(f"{EURES}/jv-search/search", json=body)
                r.raise_for_status()
                jvs = r.json().get("jvs", [])
                for jv in jvs:
                    offers.setdefault(jv["id"], jv)
                if len(jvs) < 50 or page * 50 >= config.EURES_MAX_PER_QUERY:
                    break
                page += 1
                time.sleep(1)
            time.sleep(1)
        out = []
        for jv_id, jv in offers.items():
            country = next(iter(jv.get("locationMap") or {"": []}), "").lower() or None
            out.append({
                "source": "eures", "source_id": jv_id,
                "url": f"https://europa.eu/eures/portal/jv-se/jv-details/{jv_id}?lang=fr",
                "title": jv["title"].strip(), "company": (jv.get("employer") or {}).get("name"),
                "city": None, "country": country, "posted_at": _iso(jv.get("creationDate")),
                "description": strip_html(jv.get("description"))[:6000], "hints": {},
            })
    return out


def eures_details(offer: dict) -> dict:
    """Detail of an EURES offer: city, experience, languages. Only called for offers that survive the prefilter."""
    with _client() as c:
        r = c.get(f"{EURES}/jv/id/{offer['source_id']}", params={"requestLang": "fr"})
        if r.status_code != 200:
            return offer
        d = r.json()
        prof = (d.get("jvProfiles") or {}).get(d.get("preferredLanguage") or "fr") or next(iter((d.get("jvProfiles") or {}).values()), {})
    loc = (prof.get("locations") or [{}])[0]
    city = re.sub(r"\s*\(.*\)$", "", loc.get("cityName") or "") or None
    offer["city"] = city
    offer["country"] = (loc.get("countryCode") or offer.get("country") or "").lower() or None
    offer["hints"] = {
        "years_experience": prof.get("requiredYearsOfExperience"),
        "languages": [{"code": l.get("languageCode"), "level": l.get("requiredSkillLevel")}
                      for l in prof.get("positionLanguages") or []],
        "apply": strip_html(" ".join(prof.get("applicationInstructions") or []))[:400],
        "source_system": d.get("source"),
    }
    return offer


# ----------------------------------------------------------------------------- Forem (open data ODWB, Wallonie)
FOREM = "https://www.odwb.be/api/explore/v2.1/catalog/datasets/offres-d-emploi-forem/records"


def forem() -> list[dict]:
    geo = f"within_distance(lieuxtravailgeo, geom'POINT({config.HOME['lon']} {config.HOME['lat']})', {config.FOREM_RADIUS_KM}km)"
    seen: dict[str, dict] = {}
    with _client() as c:
        for flt in config.FOREM_FILTERS:
            r = c.get(FOREM, params={"where": f"{geo} AND {flt}", "order_by": "datedebutdiffusion desc", "limit": 100})
            r.raise_for_status()
            for rec in r.json().get("results", []):
                seen.setdefault(rec["numerooffreforem"], rec)
            time.sleep(0.5)
    out = []
    for oid, rec in seen.items():
        g = (rec.get("lieuxtravailgeo") or [{}])[0] or {}
        out.append({
            "source": "forem", "source_id": oid, "url": rec.get("url"),
            "title": rec["titreoffre"].strip(), "company": rec.get("nomemployeur"),
            "city": ((rec.get("lieuxtravaillocalite") or [None])[0] or "").title() or None, "country": "be",
            "lat": g.get("lat"), "lon": g.get("lon"), "posted_at": rec.get("datedebutdiffusion"),
            "description": f"Métier : {rec.get('metier')}. Contrat : {rec.get('typecontrat')}. "
                           f"Régime : {rec.get('regimetravail')}. Études : {', '.join(rec.get('niveauxetudes') or [])}. "
                           f"Expérience : {rec.get('experiencerequise') or 'non précisée'}. "
                           f"Secteur : {', '.join(rec.get('secteurs') or [])}. Source : {rec.get('source')}.",
            "hints": {"languages": rec.get("languescodeiso2"), "experience": rec.get("experiencerequise"),
                      "contract": rec.get("typecontrat"), "metier": rec.get("metier")},
        })
    return out


# ----------------------------------------------------------------------------- Career pages (ATS)
def workday() -> list[dict]:
    out = []
    with _client() as c:
        for tenant, inst, site, search, name in config.WORKDAY:
            base = f"https://{tenant}.{inst}.myworkdayjobs.com"
            try:
                offset = 0
                while offset < 200:
                    r = c.post(f"{base}/wday/cxs/{tenant}/{site}/jobs",
                               json={"searchText": search, "limit": 20, "offset": offset, "appliedFacets": {}})
                    r.raise_for_status()
                    posts = r.json().get("jobPostings", [])
                    for p in posts:
                        if "luxembourg" not in (p.get("locationsText") or "").lower():
                            continue
                        out.append({
                            "source": f"workday:{tenant}", "source_id": p["externalPath"],
                            "url": f"{base}/{site}{p['externalPath']}", "title": p["title"].strip(),
                            "company": name,
                            "city": "Luxembourg", "country": "lu", "posted_at": None,
                            "description": "", "hints": {"workday": [base, tenant, site, p["externalPath"]]},
                        })
                    if len(posts) < 20:
                        break
                    offset += 20
                    time.sleep(1)
            except httpx.HTTPError as e:
                log.warning("workday %s : %s", tenant, e)
    return out


def workday_details(offer: dict) -> dict:
    base, tenant, site, path = offer["hints"]["workday"]
    with _client() as c:
        r = c.get(f"{base}/wday/cxs/{tenant}/{site}{path}")
        if r.status_code == 200:
            info = r.json().get("jobPostingInfo", {})
            offer["description"] = strip_html(info.get("jobDescription"))[:6000]
            offer["posted_at"] = info.get("startDate")
            offer["city"] = (info.get("location") or "Luxembourg").split(",")[0]
    return offer


def recruitee() -> list[dict]:
    out = []
    with _client() as c:
        for company in config.RECRUITEE:
            try:
                r = c.get(f"https://{company}.recruitee.com/api/offers/")
                r.raise_for_status()
            except httpx.HTTPError as e:
                log.warning("recruitee %s : %s", company, e)
                continue
            for o in r.json().get("offers", []):
                if (o.get("country_code") or "").upper() not in ("LU", "BE", "FR"):
                    continue
                out.append({
                    "source": f"recruitee:{company}", "source_id": str(o["id"]), "url": o.get("careers_url"),
                    "title": o["title"].strip(), "company": o.get("company_name") or company.title(),
                    "city": (o.get("city") or "").title() or None, "country": (o.get("country_code") or "").lower(),
                    "posted_at": (o.get("published_at") or "")[:10] or None,
                    "description": strip_html((o.get("description") or "") + "\n" + (o.get("requirements") or ""))[:6000],
                    "hints": {"remote": o.get("remote"), "experience": o.get("experience_code"),
                              "contract": o.get("employment_type_code")},
                })
    return out


def amazon() -> list[dict]:
    out = []
    with _client() as c:
        for loc, country in config.AMAZON_LOCATIONS:
            offset = 0
            while offset < 300:
                r = c.get("https://www.amazon.jobs/en/search.json",
                          params={"loc_query": loc, "country": country, "sort": "recent", "result_limit": 100, "offset": offset})
                r.raise_for_status()
                jobs = r.json().get("jobs", [])
                for j in jobs:
                    out.append({
                        "source": "amazon", "source_id": str(j.get("id_icims") or j.get("id")),
                        "url": "https://www.amazon.jobs" + j["job_path"], "title": j["title"].strip(),
                        "company": "Amazon", "city": j.get("city") or loc, "country": "lu",
                        "posted_at": j.get("posted_date"),
                        "description": strip_html((j.get("description") or "") + "\n" + (j.get("basic_qualifications") or "")
                                                  + "\n" + (j.get("preferred_qualifications") or ""))[:6000],
                        "hints": {},
                    })
                if len(jobs) < 100:
                    break
                offset += 100
                time.sleep(1)
    return out


# ----------------------------------------------------------------------------- ictjob.lu (sitemap: titles only)
def ictjob() -> list[dict]:
    """ictjob detail pages do not answer automated requests: we keep the title (from the URL) and the link."""
    out = []
    with _client() as c:
        for sitemap in config.ICTJOB_SITEMAPS:
            try:
                r = c.get(sitemap)
                r.raise_for_status()
            except httpx.HTTPError as e:
                log.warning("ictjob : %s", e)
                continue
            for url in re.findall(r"<loc>([^<]+)</loc>", r.text):
                m = re.search(r"/job/([^/]+)/([\w-]+)$", url)
                if not m:
                    continue
                slug = m.group(1).replace("-", " ")
                out.append({
                    "source": "ictjob", "source_id": m.group(2), "url": url, "title": slug.capitalize(),
                    "company": None, "city": None, "country": "lu", "posted_at": None,
                    "description": f"Offre IT publiée sur ictjob.lu (titre tiré de l'URL) : {slug}.",
                    "hints": {"title_only": True},
                })
    return out


# ----------------------------------------------------------------------------- HTML pages (no API)
HTML = {"Accept": "text/html"}


def page_text(page: str) -> str:
    """Text of a whole HTML page (scripts and styles removed)."""
    return strip_html(re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page))


def _first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.S)
    return strip_html(m.group(1)) if m else None


_BE = re.compile(r"belgi|arlon|virton|bastogne|libramont|neufchateau|marche|aubange|messancy|florenville|habay")
_FR = re.compile(r"france|longwy|thionville|metz|verdun|sedan|montmedy|longuyon|hayange|villerupt|audun")


def _country(location: str | None) -> str:
    from .db import norm
    suffix = re.search(r"\((\w+)\)\s*$", location or "")  # « Arlon (BE) », « Bissen (Luxembourg) »
    loc = norm(location or "")
    if suffix and suffix.group(1).upper() in ("BE", "B", "BELGIQUE", "BELGIUM"):
        return "be"
    if suffix and suffix.group(1).upper() in ("FR", "F", "FRANCE"):
        return "fr"
    return "be" if _BE.search(loc) else "fr" if _FR.search(loc) else "lu"


def _city(location: str | None) -> str | None:
    return re.sub(r"\s*\([^)]*\)\s*$", "", location).strip() or None if location else None


# ----------------------------------------------------------------------------- jobs.lu
# Main Luxembourg job board. No API: HTML listings sorted by date, per category, read slowly (3 s between pages).
# Opt-in (SCOUT_SOURCES): read the site's terms before enabling it.
_JOBSLU_ITEM = re.compile(r'<article class="job-list-item[^"]*" id="job-id-(\d+)">(.*?)</article>', re.S)


def parse_jobslu_list(page: str) -> list[dict]:
    out = []
    for jid, block in _JOBSLU_ITEM.findall(page):
        title = _first(r'class="job-title">(.*?)</a>', block)
        if not title:
            continue
        location = _first(r'<span class="location">(.*?)</span>', block)
        out.append({
            "source": "jobslu", "source_id": jid, "url": f"https://fr.jobs.lu/ApplyForJob.aspx?Id={jid}",
            "title": title, "company": _first(r'class="recruiter-name">(.*?)</a>', block),
            "city": _city(location), "country": _country(location), "posted_at": None, "description": "", "hints": {},
        })
    return out


def jobslu() -> list[dict]:
    out, seen = [], set()
    with _client() as c:
        for cat in config.JOBSLU_CATEGORIES:
            for page in range(1, config.JOBSLU_MAX_PAGES + 1):
                try:
                    r = c.get("https://fr.jobs.lu/Jobs.aspx", headers=HTML, params={
                        "Keywords": "", "Categories": cat, "Regions": 0, "sort": "Date", "page": page})
                    r.raise_for_status()
                except httpx.HTTPError as e:
                    log.warning("jobs.lu catégorie %s page %d : %s", cat, page, e)
                    break
                items = parse_jobslu_list(r.text)
                out += [o for o in items if o["source_id"] not in seen]
                seen.update(o["source_id"] for o in items)
                time.sleep(config.JOBSLU_DELAY)
                if len(items) < 40:  # last page of the category
                    break
    return out


def parse_jobslu_detail(offer: dict, page: str) -> dict:
    desc = re.search(r'job-html-description">(.*?)</div>\s*</div>', page, re.S)
    offer["description"] = strip_html(desc.group(1))[:6000] if desc else page_text(page)[:6000]
    field = lambda labels: _first(rf"<dt>(?:{labels}):</dt>\s*<dd>(.*?)</dd>", page)  # fr.jobs.lu ou en.jobs.lu
    location = field("Location|Localisation")
    if location:
        offer["city"], offer["country"] = _city(location), _country(location)
    offer["hints"] = {**(offer.get("hints") or {}), "contract": field("Contract Type|Type de contrat"),
                      "hours": field("Hours|Temps de travail")}
    return offer


def jobslu_details(offer: dict) -> dict:
    time.sleep(config.JOBSLU_DELAY)
    try:
        with _client() as c:
            r = c.get(offer["url"], headers=HTML)
            r.raise_for_status()
        return parse_jobslu_detail(offer, r.text)
    except httpx.HTTPError as e:
        log.warning("jobs.lu détail %s : %s", offer["source_id"], e)
        return offer


# ----------------------------------------------------------------------------- employers followed directly
def parse_list_lu(page: str) -> list[dict]:
    """LIST (Luxembourg Institute of Science and Technology): cards of the careers page, offers hosted on Skeeled."""
    out = []
    for card in re.findall(r'<div class="lt-job-card">(.*?)</a>', page, re.S):
        url = re.search(r'href="(https://app\.skeeled\.com/offer/c/(\w+)[^"]*)"', card)
        title = _first(r'weight--600 mb--16">(.*?)</p>', card)
        if not (url and title):
            continue
        internship = bool(re.match(r"\s*INT-?\d", title))  # "INT-..." references: internships and thesis topics
        for _ in range(3):  # "FA-27006 TECHNICIEN.NE ...", "SD25062 ...", "SD-26104 – ..." -> reference stripped
            title = re.sub(r"^\s*(?:[A-Z]{1,4}-?\d+|[–-])\s*-?\s*", "", title)
        if internship:
            title = f"Internship – {title}"
        out.append({
            "source": "list", "source_id": url.group(2), "url": html.unescape(url.group(1)).replace("lang=en", "lang=fr"),
            "title": title.capitalize() if title.isupper() else title, "company": "LIST",
            "city": _first(r'lt-job-card__location">.*?<p[^>]*>(.*?)</p>', card), "country": "lu", "posted_at": None,
            "description": "", "hints": {"contract": _first(r'fa-file[^>]*></i>\s*<p[^>]*>(.*?)</p>', card)},
        })
    return out


def parse_science_center(page: str) -> list[dict]:
    """Luxembourg Science Center (Differdange): offers published only on its own site."""
    out = []
    for slug, contract, title in re.findall(
            r'<a href="/en/([^"]+)" class="w-full flex flex-col items-center group[^"]*">\s*<span[^>]*>(.*?)</span>'
            r'\s*<h2[^>]*>\s*<span>(.*?)</span>', page, re.S):
        out.append({
            "source": "lsc", "source_id": slug, "url": f"https://www.science-center.lu/en/{slug}",
            "title": strip_html(title), "company": "Luxembourg Science Center", "city": "Differdange", "country": "lu",
            "posted_at": None, "description": "", "hints": {"contract": strip_html(contract)},
        })
    return out


def _html_list(url: str, parse) -> list[dict]:
    try:
        with _client() as c:
            r = c.get(url, headers=HTML)
            r.raise_for_status()
        return parse(r.text)
    except httpx.HTTPError as e:
        log.warning("%s : %s", url, e)
        return []


def list_lu() -> list[dict]:
    return _html_list("https://www.list.lu/career/job-offers", parse_list_lu)


def science_center() -> list[dict]:
    return _html_list("https://www.science-center.lu/en/jobs", parse_science_center)


def page_details(offer: dict) -> dict:
    """Full text of an offer whose page is plain HTML (Skeeled, Science Center)."""
    time.sleep(2)
    try:
        with _client() as c:
            r = c.get(offer["url"], headers=HTML)
            r.raise_for_status()
        offer["description"] = page_text(r.text)[:6000]
    except httpx.HTTPError as e:
        log.warning("détail %s : %s", offer["url"], e)
    return offer


COLLECTORS = {"eures": eures, "forem": forem, "workday": workday, "recruitee": recruitee, "amazon": amazon,
              "ictjob": ictjob, "jobslu": jobslu, "list": list_lu, "lsc": science_center}
DETAILS = {"eures": eures_details, "workday": workday_details, "jobslu": jobslu_details, "list": page_details,
           "lsc": page_details}
