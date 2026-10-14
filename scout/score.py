"""Gates and 0-100 score of an offer: deterministic, driven by the profile note.

Every criterion is visible in score_detail (API, digest). Reasons and infos are in French, like the prompts.
"""
import re

from .db import norm
from .families import PASSION_FAMILIES

# Jobs clearly off-topic judging by the title (mostly brought by EURES keyword searches)
_OFF_TOPIC = re.compile(
    r"soignant|infirmi|chauffeur|cuisin|boulang|vendeu|caissi|coiffeu|nettoyage|entretien des locaux|medecin|"
    r"pharmac|avocat|juriste|comptab|aide a domicile|educat|enseignant|plombi|macon|couvreu|charpent|menuisi|"
    r"carreleu|soudeu|cariste|preparateur de commandes|magasini|manutention|livreu|ambulan|kine|psycholog|"
    r"auditeur|fund |kyc|aml |compliance|trader|actuaire|recruteur|payroll|conducteur de travaux|telephoniste|"
    r"teleoperat|telecons|agent de securite|gardien|serveur en salle|serveuse|barman|commis de cuisine|depositary|"
    r"custody|fund accounting|transfer agent|laborant|radiologie"
)
_ACADEMIC_TITLE = re.compile(r"\bphd\b|post ?doc|postdoctoral|doctoral|doctorant|\bresearchers?\b|scientist|chercheu")
_SENIOR_TITLE = re.compile(r"\b(senior|sr|lead|head|principal|director|directeur|directrice|chief|vp|expert|architect|supervisor|superviseur|"
                           r"architecte|manager)\b")

# What the LLM claims must be found in the offer text (otherwise it is a guess of the model)
EVIDENCE = {
    "impression_3d": r"impressions? 3d|imprimantes? 3d|3d print|fabrication additive|additive manufacturing|prototypage rapide",
    "electronique": r"electroni|pcb|circuit|soudure|microcontr|arduino|esp32|automaticien",
    "fablab": r"fab ?lab|makerspace|hackerspace",
    "iot": r"\biot\b|objets? connecte|internet of things|capteur|embarque|embedded",
    "ia": r"\bia\b|intelligence artificielle|machine learning|\bllm|deep learning|\bai\b|data scien|genai|generative",
    "de": r"allemand|german|deutsch",
    "lb": r"luxembourgeois|luxembourgish|letzebuergesch|luxemburgisch",
    "nl": r"neerlandais|dutch|nederlands|flamand|flemish",
    "doctorat": r"\bphd\b|ph d|doctorat|doctorate|doctoral",
    "bac+2/3": r"bac 2|bac 3|bachelor|bachelier|licence|\bbts\b|\bdut\b|\bbut\b|graduat|diplome|degree|hbo",
    "master": r"master|msc|bac 5|ingenieur civil|engineering degree|m sc",
    "experience": r"\d+ ?(ans|annees|an|years?|yrs|jaar|jahre)|experience (professionnelle|significative|confirmee|"
                  r"minimum|requise|exigee|solide|avere)|minimum .{0,25}experience|at least .{0,25}experience|"
                  r"proven .{0,20}experience|years of experience|berufserfahrung",
    "junior": r"debutant|junior|jeune diplome|sans experience|premiere experience|formation assuree|reconversion|"
              r"entry.level|graduate|no experience|autodidact|self.taught",
}
PASSIONS = {"impression_3d", "electronique", "fablab", "iot", "ia"}
# Score = chances of being hired (35) + interest (25) + practicality (10) + judge's opinion (30).
# Chances come first: the target is a junior / self-taught candidate, so offers open to beginners rank highest.
CONTRACT_POINTS = {"cdi": 2, "cdd": 1, "interim": 0, "stage": -8, "freelance": 0, "inconnu": 0}
FAMILY_POINTS = {3: 15, 2: 10, 1: 5}
# The offer text explicitly opens the door (checked in the text, not on the LLM's word)
_WELCOME_STRONG = re.compile(
    r"debutante?s? (accepte|bienvenu|admis|possible)\w*|debutants? acceptes|ouvert aux debutants|sans experience|"
    r"aucune experience|pas d.experience (requise|necessaire|exigee)|premiere experience|jeune diplome|"
    r"formation (assuree|interne|en interne|complete|prevue|fournie|sur le terrain)|nous (vous )?formerons|"
    r"nous vous formons|on vous forme|vous serez forme|reconversion|autodidacte|self.taught|"
    r"no (prior |previous )?experience (is )?(required|needed|necessary)|entry.level|trainee|\bjunior\b|"
    r"pas de diplome (requis|exige|necessaire)|sans diplome|diplome non (requis|exige)|no degree (is )?required|"
    r"degree (is )?not required|profil atypique|toutes? formations? (acceptee|confondue)"
)
_WELCOME_WEAK = re.compile(r"motive|motivation|passionne|curieu|curious|envie d.apprendre|eager to learn|"
                           r"willing(ness)? to learn|goût d.apprendre|gout d.apprendre|esprit d.equipe|team spirit")
# What the LLM claims about level or degree only counts if the text says it too
_SENIOR_WORDS = re.compile(r"\bsenior\b|confirme|experimente|\bexpert\b|\blead\b|\d+ ?(?:\+ ?)?(?:ans|annees|years?) d")
_EQUIVALENT = re.compile(r"ou (?:diplome |formation |titre |niveau )?equivalent|or equivalent|equivalent (?:work )?experience|"
                         r"experience equivalente|ou equivalence|or similar|ou similaire")
# Experience that is only "wished" (firm requirements are already excluded by gate())
_YEARS_ANY = re.compile(r"\b(\d{1,2}) ?(?:(?:a|to) ?\d{1,2} ?)?(?:\+ ?)?(?:years?|yrs|ans|annees)\b(?: \w+){0,6}? (?:experience|expertise)")


def _evidenced(item: str, text: str) -> bool:
    pattern = EVIDENCE.get(item)
    return True if pattern is None else bool(re.search(pattern, text))


def offer_text(offer: dict) -> str:
    return norm(f"{offer.get('title', '')} {offer.get('description', '')}")


def prefilter(offer: dict) -> str | None:
    """Reason to drop the offer from its title alone (before any analysis)."""
    title = norm(offer["title"])
    if _OFF_TOPIC.search(title):
        return "métier hors sujet"
    if _GERMAN_TITLE.search(title) or re.search(r"\b[mw] ?/ ?[wm] ?/ ?d\b", offer["title"], re.I):  # « (m/w/d) »
        return "annonce en allemand"
    if _INTERNSHIP_TITLE.search(title):
        return "stage (réservé aux étudiants : convention de stage)"
    if _ACADEMIC_TITLE.search(title):
        return "poste de recherche (doctorat / master)"
    if _SENIOR_TITLE.search(title) and "junior" not in title:
        return "poste senior / encadrement"
    return None


def commute_limit(offer: dict, family: str, profile: dict) -> int:
    c = profile["commute"]
    if offer.get("country") == "lu":
        return c["lu_max_min"]
    return c["passion_other_max_min"] if family in PASSION_FAMILIES else c["other_max_min"]


def commute_gate(offer: dict, family: str, commute: int | None, profile: dict) -> str | None:
    """Commute gate, usable before the LLM analysis (family from the title)."""
    if commute is None:
        return None
    limit = commute_limit(offer, family, profile)
    if commute > limit:
        where = "Luxembourg" if offer.get("country") == "lu" else "hors Luxembourg"
        return f"trajet {commute} min (max {limit} {where})"
    return None


# "3 ans d'expérience", "1+ years of non-internship professional experience" (normalised text)
_YEARS_EXP = re.compile(r"\b(\d{1,2}) ?(?:(?:a|to) ?\d{1,2} ?)?(?:years?|yrs|ans|annees|an)\b(?: \w+){0,6}? (?:experience|expertise)")
_NICE_TO_HAVE = re.compile(r"prefer|ideal|souhait|un plus|nice to have|bonus|atout|apprecie|appreciated|would be a plus|advantage")


def required_years_in_text(text: str) -> int:
    """Largest number of years of experience required in the text, ignoring \"preferred\" passages."""
    best = 0
    for m in _YEARS_EXP.finditer(text):
        if "intern" in m.group(0) and "non intern" not in m.group(0):
            continue  # "1 year of internship experience": an internship is enough
        if _NICE_TO_HAVE.search(text[max(0, m.start() - 160):m.start()]):
            continue
        best = max(best, int(m.group(1)))
    return best


def required_languages(ex: dict, offer: dict, text: str) -> set[str]:
    required = {lang for lang in ex.get("languages_required", []) if _evidenced(lang, text)}
    for lang in (offer.get("hints") or {}).get("languages") or []:  # EURES: required languages, with level
        if isinstance(lang, dict) and lang.get("level"):
            required.add(lang.get("code"))
    return required - {"other", None}


_GERMAN_TITLE = re.compile(r"\bm w d\b|\bw m d\b|mitarbeiter|zeichner|konstrukteur|techniker\b|sachbearbeiter|"
                           r"kaufm|fachrichtung|elektroniker|informatiker|entwickler")  # German almost always required
_INTERNSHIP_TITLE = re.compile(r"\b(intern|interns|internship|stagiaire|stage)\b")  # work-study (alternance) stays possible
# Jobs reserved for students or recent graduates (new-grad programmes, internships...): small models miss them
_STUDENTS_ONLY = re.compile(
    r"currently enrolled|expected graduation|graduated within|graduation (date )?between|recent graduates? only|"
    r"must be (a )?(current )?student|penultimate or final year|working towards a (university )?degree|convention de stage (obligatoire|requise|exigee)|"
    r"(etre|etes) (actuellement )?(inscrit|etudiant)e? (en|dans|a)|etudiant(e)? en (cours|derniere annee) d.etudes")


def gate(ex: dict, family: str, commute: int | None, offer: dict, profile: dict) -> str | None:
    """Reason to drop the offer outright (rules of the profile note), or None."""
    text = offer_text(offer)
    if family not in (profile.get("target_families") or {}):
        return f"métier hors de tes familles ({family})"
    if ex.get("remote") != "complet":
        reason = commute_gate(offer, family, commute, profile)
        if reason:
            return reason
    blocked = required_languages(ex, offer, text) & set(profile.get("blocked_languages") or [])
    if blocked:
        return "exige " + ", ".join(sorted(blocked))
    years = ex.get("min_years_experience") or 0
    hinted = (offer.get("hints") or {}).get("years_experience")
    eures_years = hinted if isinstance(hinted, int) else 0  # EURES: "required" years typed in by the employer
    if not ex.get("internship_counts"):
        if eures_years >= 1 and _evidenced("experience", text):
            return f"expérience pro exigée ({eures_years} an{'s' if eures_years > 1 else ''})"
        if ex.get("experience_pro_mandatory") and years >= 1 and _evidenced("experience", text):
            return f"expérience pro exigée ({years} an{'s' if years > 1 else ''})"
        in_text = required_years_in_text(text)
        if in_text >= 1 and not ex.get("self_taught_welcome"):
            return f"expérience pro exigée ({in_text} an{'s' if in_text > 1 else ''}, dans le texte)"
    if _STUDENTS_ONLY.search(text):
        return "réservé aux étudiants / diplômés récents"
    degree = ex.get("degree_required")
    if (ex.get("degree_mandatory") and degree in ("bac+2/3", "master", "doctorat") and not _EQUIVALENT.search(text)
            and not ex.get("equivalence_accepted") and not ex.get("self_taught_welcome") and _evidenced(degree, text)):
        return f"diplôme exigé ({degree})"
    return None


def skill_points(skills: list[str], profile: dict) -> list[str]:
    mine = {norm(s) for s in (profile.get("skills") or [])}
    matched = []
    for skill in skills:
        s = norm(skill)
        if s and any(s == k or (len(k) >= 3 and re.search(rf"\b{re.escape(k)}\b", s)) for k in mine):
            matched.append(skill)
    return matched


def compute(ex: dict, family: str, commute: int | None, offer: dict, profile: dict, fit: dict | None) -> tuple[int, dict]:
    """Score of an offer that passed gate(). fit = LLM judgement (fit.judge) or None if it has not happened yet."""
    text = offer_text(offer)
    matched = skill_points(ex.get("skills", []), profile)

    # 1. Chances of being hired (0-35)
    chances = 12
    welcome = sorted({m.group(0) for m in _WELCOME_STRONG.finditer(text)})
    if welcome:
        chances += 15
    elif ex.get("junior_friendly") or ex.get("self_taught_welcome"):
        chances += 5  # l'IA le pense, le texte ne le dit pas clairement
    if _WELCOME_WEAK.search(text):
        chances += 3
    chances += min(8, 2 * len(matched))  # skills the candidate can prove with projects
    years = max((int(m.group(1)) for m in _YEARS_ANY.finditer(text)), default=0)
    if years >= 2:
        chances -= 10
    elif years == 1:
        chances -= 4
    if _SENIOR_WORDS.search(text):  # LLM says "senior" but the text does not: ignored
        if ex.get("seniority") == "confirme":
            chances -= 8
        elif ex.get("seniority") in ("senior", "lead"):
            chances -= 15
    degree = ex.get("degree_required")
    equivalent = ex.get("equivalence_accepted") or bool(_EQUIVALENT.search(text))
    if degree == "master" and _evidenced("master", text) and not equivalent:
        chances -= 10
    elif degree == "bac+2/3" and _evidenced("bac+2/3", text) and not equivalent:
        chances -= 5
    hinted = (offer.get("hints") or {}).get("years_experience")
    eures_years = hinted if isinstance(hinted, int) and not ex.get("internship_counts") else 0
    if eures_years:
        chances -= 6  # passed gate(): the ad does not mention it, only the EURES form does

    # 2. Interest (0-25): job family weighted by the profile, interests as a bonus (proven by the text)
    passions = {p for p in ex.get("passion_match", []) if p in PASSIONS and _evidenced(p, text)
                and (p != "ia" or family == "ai_automation_data")}  # "GenAI tools" in a Java job: not an interest
    interest = FAMILY_POINTS.get(int((profile.get("target_families") or {}).get(family, 1)), 5) + (10 if passions else 0)

    # 3. Practicality (0-10): commute + contract
    if ex.get("remote") == "complet":
        trip = 6
    elif commute is None:
        trip = 2
    elif offer.get("country") == "lu":
        trip = 6 if commute <= 60 else 5 if commute <= 80 else 3
    else:
        trip = 8 if commute <= 25 else 6 if commute <= 40 else 4 if commute <= 55 else 2
    practical = trip + CONTRACT_POINTS.get(ex.get("contract"), 0)

    d = {"chances": max(0, min(35, chances)), "intérêt": min(25, interest), "pratique": min(10, practical),
         "avis IA": 3 * fit["fit"] if fit else 15}  # 0-30; neutral (5/10) until the judgement happened
    total = max(0, min(100, sum(d.values())))
    info = []
    if welcome:
        info.append("accessible : « " + " », « ".join(welcome[:3]) + " »")
    if (offer.get("hints") or {}).get("title_only"):
        total = min(total, 60)  # only the title is known: the analysis remains a guess
        info.append("titre seul : à vérifier sur l'offre")
    if commute is None and ex.get("remote") != "complet":
        info.append("lieu inconnu : vérifie le trajet")
    if years:
        info.append(f"{years} an{'s' if years > 1 else ''} d'expérience souhaité{'s' if years > 1 else ''} (pas exigé{'s' if years > 1 else ''})")
    if eures_years:
        info.append(f"le formulaire EURES indique {eures_years} an{'s' if eures_years > 1 else ''} d'expérience "
                    "(pas l'annonce) : mets tes projets en avant")
    if "en" in required_languages(ex, offer, text):
        info.append("anglais exigé (ta compréhension suffit, l'oral se pratique)")
    if ex.get("contract") == "stage":
        info.append("stage : souvent réservé aux étudiants")
    if offer.get("country") == "lu" and (ex.get("remote_days_per_week") or 0) * 45 > 34:
        info.append("télétravail > 34 j/an : ces jours seraient imposés en France")
    return total, {"points": d, "compétences_trouvées": matched, "passions": sorted(passions), "infos": info,
                   "accessible": welcome, "fit": (fit or {}).get("note_fr", ""), "pour": (fit or {}).get("pour", []),
                   "contre": (fit or {}).get("contre", []), "famille": family}


def excluded_detail(reason: str, family: str | None = None) -> dict:
    return {"infos": [f"écartée : {reason}"], "famille": family}
