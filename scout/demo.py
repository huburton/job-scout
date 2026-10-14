"""Demo mode: the whole pipeline offline.

Synthetic offers (fictional employers), a deterministic fake LLM that answers the two grammar-constrained calls
(fact extraction and fit judgement) with keyword rules, and a fake commute table. Nothing here touches the network.
The point is to exercise the real code (prefilter, gates, scoring, digest, API) without any server or API key.

    python -m scout demo                 # run once in a temporary directory and print a ranked digest
    SCOUT_DEMO=1 python -m scout serve   # same data behind the HTTP API
"""
import re
from pathlib import Path

from . import config, families, score
from .db import norm

# Fake commute table (minutes by car from the demo home town); keys are normalised city names.
DEMO_COMMUTES = {"arlon": 49, "luxembourg": 64, "kirchberg": 68, "differdange": 57, "virton": 21, "metz": 91}

OFFERS = [
    {"source_id": "1001", "title": "Technicien support informatique junior (H/F)", "company": "Brightwave IT Services",
     "city": "Arlon", "country": "be", "posted_at": "2026-10-12", "description":
     "Au sein de notre service desk, tu dépannes les utilisateurs (Windows, Active Directory, Microsoft 365) et tu "
     "gères le parc de postes. Débutants acceptés, formation assurée en interne. Une première expérience en support "
     "est un plus. Contrat CDI, un jour de télétravail par semaine. Français courant, anglais technique."},
    {"source_id": "1002", "title": "Administrateur systèmes Linux junior", "company": "Nordlicht Hosting",
     "city": "Luxembourg", "country": "lu", "posted_at": "2026-10-13", "description":
     "Rejoins l'équipe infrastructure : administration de serveurs Linux, conteneurs Docker, scripts Bash, "
     "supervision et sauvegardes. Profil junior ou autodidacte bienvenu, projets personnels appréciés. CDI. "
     "Deux jours de télétravail par semaine. Langues : français, anglais."},
    {"source_id": "1003", "title": "Junior Python Developer", "company": "Quartz Analytics",
     "city": "Kirchberg", "country": "lu", "posted_at": "2026-10-11", "description":
     "You will build small internal tools and data pipelines in Python and SQL, with Git and Docker, in a team of "
     "five. Entry level welcome, self-taught developers with a solid portfolio are encouraged to apply. Permanent "
     "contract, hybrid work. Working language: English, French is a plus."},
    {"source_id": "1004", "title": "Technicien prototypage et impression 3D", "company": "Fablux Makerspace",
     "city": "Differdange", "country": "lu", "posted_at": "2026-10-10", "description":
     "Tu accueilles le public dans notre fablab, tu entretiens les imprimantes 3D et la découpe laser, tu aides à "
     "réaliser des prototypes avec Arduino et ESP32 et tu modélises en CAO. Aucune expérience requise, motivation et "
     "curiosité avant tout. CDD de 12 mois. Français, anglais."},
    {"source_id": "1005", "title": "Technicien électronique et IoT", "company": "Verdant Sensors",
     "city": "Virton", "country": "be", "posted_at": "2026-10-09", "description":
     "Montage, test et mise en service de capteurs connectés (ESP32, C embarqué, PCB). Débutants acceptés, nous vous "
     "formerons. Atelier à Virton, pas de télétravail. CDI. Français."},
    {"source_id": "1006", "title": "Senior DevOps Engineer", "company": "Cobalt Cloud",
     "city": "Luxembourg", "country": "lu", "posted_at": "2026-10-12", "description":
     "Lead our platform team: Kubernetes, Terraform, CI/CD, on-call. 8+ years of experience required. Permanent."},
    {"source_id": "1007", "title": "Développeur backend Java", "company": "Meridian Software",
     "city": "Luxembourg", "country": "lu", "posted_at": "2026-10-08", "description":
     "Développement de services Java et Spring pour le secteur bancaire. Minimum 4 ans d'expérience professionnelle "
     "requis en développement backend. Master en informatique. CDI. Français, anglais."},
    {"source_id": "1008", "title": "Développeur full stack", "company": "Alpenrose Digital",
     "city": "Luxembourg", "country": "lu", "posted_at": "2026-10-13", "description":
     "Applications web avec TypeScript, React et Node.js pour des clients luxembourgeois. Débutants acceptés. "
     "Allemand courant exigé, français et anglais. CDI."},
    {"source_id": "1009", "title": "Développeur web - Metz", "company": "Lorraine Pixel",
     "city": "Metz", "country": "fr", "posted_at": "2026-10-12", "description":
     "Agence web à Metz : sites en PHP et JavaScript, intégration, maintenance. Débutants acceptés. CDI. Français."},
    {"source_id": "1010", "title": "Comptable (H/F)", "company": "Ledger & Co",
     "city": "Luxembourg", "country": "lu", "posted_at": "2026-10-07", "description":
     "Tenue de la comptabilité de plusieurs sociétés, clôtures mensuelles. CDI. Français, anglais."},
]


def _collect() -> list[dict]:
    return [{"source": "demo", "url": f"https://jobs.example.test/offers/{o['source_id']}", "lat": None, "lon": None,
             "hints": {}, **o} for o in OFFERS]


COLLECTORS = {"demo": _collect}


def setup(workdir: Path):
    """Point every path at a scratch directory, use the bundled example profile and disable optional services."""
    config.DEMO = True
    config.DATA_DIR = str(workdir / "data")
    config.OUT_DIR = str(workdir / "out")
    config.PROFILE_FILE = str(Path(__file__).resolve().parent.parent / "profile.example.md")
    config.PC_STATUS_URL = ""
    config.NTFY_TOPIC = ""


# ------------------------------------------------------------------------------------------ fake LLM
_VOCAB = ["python", "sql", "git", "docker", "linux", "bash", "windows", "active directory", "microsoft 365",
          "typescript", "react", "node.js", "php", "javascript", "java", "spring", "kubernetes", "terraform",
          "arduino", "esp32", "pcb", "cao", "ci/cd", "support", "helpdesk", "service desk"]


_WORDS = {"un": 1, "deux": 2, "trois": 3}


def _section(content: str, start: str, end: str | None = None) -> str:
    i = content.find(start)
    if i < 0:
        return ""
    i += len(start)
    j = content.find(end, i) if end else -1
    return content[i:j if j >= 0 else None].strip()


def _fake_extract(content: str) -> dict:
    title = _section(content, "Titre : ", "\n")
    text = norm(f"{title} {_section(content, "Texte de l'offre :")}")
    years = score.required_years_in_text(text)
    family = families.from_title(title) or ("finance_business" if re.search(r"comptab|finance", text) else "it_other")
    degree = "master" if re.search(r"\bmaster\b", text) else "inconnu"
    days = re.search(r"(un|deux|trois) jours? (?:de teletravail|par semaine)", text)
    remote = "partiel" if re.search(r"teletravail|remote|hybrid", text) and "pas de teletravail" not in text else "aucun"
    return {
        "job_family": family,
        "seniority": "senior" if re.search(r"\bsenior\b|\blead\b", text) else "junior" if "junior" in text else "confirme",
        "degree_required": degree,
        "degree_mandatory": degree == "master",
        "equivalence_accepted": bool(score._EQUIVALENT.search(text)),
        "experience_mentioned": bool(years),
        "experience_pro_mandatory": years >= 1,
        "min_years_experience": min(years, 20),
        "internship_counts": "projets personnels" in text,
        "junior_friendly": bool(score._WELCOME_STRONG.search(text)),
        "self_taught_welcome": bool(re.search(r"autodidact|self taught", text)),
        "languages_required": ["fr"] + (["de"] if re.search(r"allemand courant|german.{0,20}required", text) else []),
        "languages_nice": ["en"] if re.search(r"anglais|english", text) else [],
        "remote": remote,
        "remote_days_per_week": _WORDS.get(days.group(1), 0) if days else 0,
        "contract": "cdd" if re.search(r"\bcdd\b", text) else "cdi" if re.search(r"\bcdi\b|permanent", text) else "inconnu",
        "skills": [s for s in _VOCAB if re.search(rf"(?<![a-z]){re.escape(s)}(?![a-z])", text)][:12],
        "passion_match": [p for p in sorted(score.PASSIONS) if re.search(score.EVIDENCE[p], text)][:5],
        "summary_fr": f"{title} chez {_section(content, 'Employeur : ', chr(10))}."[:240],
    }


def _fake_judge(content: str) -> dict:
    profile = norm(_section(content, "Son profil :", "Familles de métiers"))
    skills = [s.strip() for s in _section(content, "- Compétences demandées : ", "\n").split(",") if s.strip()]
    excerpt = norm(_section(content, "- Extrait du texte : "))
    shared = [s for s in skills if norm(s) and re.search(rf"\b{re.escape(norm(s))}\b", profile)]
    welcome = bool(score._WELCOME_STRONG.search(excerpt))
    fit = max(0, min(10, 3 + 2 * min(len(shared), 3) + (2 if welcome else 0)))
    return {
        "fit": fit,
        "pour": ([f"Compétences en commun : {', '.join(shared[:3])}"] if shared else []) + (
            ["Le texte accueille les débutants"] if welcome else []),
        "contre": [] if shared else ["Peu de compétences en commun avec ton profil"],
        "note_fr": ("Fonce, c'est accessible et ça colle à tes projets." if fit >= 8
                    else "Possible, mets tes projets en avant." if fit >= 5 else "Peu d'atouts, à garder en réserve."),
    }


def fake_chat_json(content: str, schema: dict) -> dict:
    """Deterministic stand-in for engines.chat_json: same signature of result (a dict matching the schema)."""
    return _fake_extract(content) if "job_family" in schema["properties"] else _fake_judge(content)


# ------------------------------------------------------------------------------------------ rendering
def render(con, stats: dict) -> str:
    import json
    rows = con.execute("SELECT * FROM offers WHERE closed = 0 AND status != 'duplicate' ORDER BY score DESC, title").fetchall()
    ranked = [r for r in rows if (r["score"] or 0) > 0]
    dropped = [r for r in rows if not r["score"]]
    out = ["job-scout demo - synthetic offers, fake LLM, fake geo table, no network", "",
           f"{len(rows)} offers collected, {len(ranked)} scored, {len(dropped)} excluded by the prefilter or the gates", "",
           "RANKED OFFERS (score / 100 = chances 35 + interest 25 + practicality 10 + judge 30)", ""]
    for n, r in enumerate(ranked, 1):
        d = json.loads(r["score_detail"])
        p = d["points"]
        trip = f"{r['commute_min']} min" if r["commute_min"] is not None else "? min"
        out.append(f"{n:>2}. {r['score']:>3}  {r['title']} - {r['company']}, {r['city']} ({trip})")
        out.append(f"         chances {p['chances']:>2} | interest {p['intérêt']:>2} | practical {p['pratique']:>2} | judge {p['avis IA']:>2}"
                   f"   skills: {', '.join(d['compétences_trouvées']) or '-'}")
        out.append(f"         {d['fit']}" + (f"  [{'; '.join(d['infos'])}]" if d["infos"] else ""))
    out += ["", "EXCLUDED", ""]
    for r in dropped:
        reason = json.loads(r["score_detail"])["infos"][0].removeprefix("écartée : ")
        out.append(f"  x  {r['title']} - {r['company']}: {reason}")
    out += ["", f"run: {json.dumps({k: v for k, v in stats.items() if k in ('analysed', 'skipped', 'errors', 'judge')})}"]
    return "\n".join(out)
