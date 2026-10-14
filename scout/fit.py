""""Is this job for the candidate?" judgement: full profile note + extracted facts -> 0-10 rating.

Only for offers that passed the gates; the model is chosen by engines.judge(). Prompts are in French (the target
job market is French-speaking); the judge answers in French too.
"""
from . import engines

SCHEMA = {
    "type": "object",
    "required": ["fit", "pour", "contre", "note_fr"],
    "properties": {
        "fit": {"type": "integer", "minimum": 0, "maximum": 10},
        "pour": {"type": "array", "items": {"type": "string", "maxLength": 90}, "maxItems": 3},
        "contre": {"type": "array", "items": {"type": "string", "maxLength": 90}, "maxItems": 3},
        "note_fr": {"type": "string", "maxLength": 260},
    },
}

FAMILY_FR = {
    "dev_software": "développement", "sysadmin_network_devops": "sysadmin / réseau / DevOps",
    "ai_automation_data": "IA / automatisation / data", "support_it": "support IT",
    "digital_fabrication": "fabrication numérique (fablab, 3D, prototypage)",
    "electronics_iot": "électronique / IoT", "it_other": "informatique (autre)",
}

PROMPT = """Tu es le conseiller carrière d'un candidat. Son profil :

{profile}

Familles de métiers qu'il vise (préférence 1 à 3) : {families}

L'offre :
- Titre : {title} — {company}, {city} ({country}), trajet depuis chez lui : {commute}
- Famille : {family}
- Résumé : {summary}
- Compétences demandées : {skills}
- Exigences : expérience {experience} ; diplôme {degree} ; langues exigées {languages} ; contrat {contract}
- Extrait du texte : {excerpt}

Cette offre a DÉJÀ passé ses filtres : trajet acceptable, aucune expérience professionnelle ni aucun diplôme
obligatoires, langues OK. Ne la pénalise pas pour le trajet, le diplôme ou l'expérience : juge l'intérêt du poste et
si ses compétences et projets collent.

Note de 0 à 10 : ses CHANCES d'être pris d'abord, puis son intérêt pour le poste
(10 : poste ouvert aux débutants / autodidactes motivés, dans un domaine qui lui plaît, il doit postuler ;
5 : possible mais il sera en concurrence avec des profils diplômés ou expérimentés ; 0 : irréaliste ou hors sujet).
Sois honnête d'après son profil : ce qui compte, ce sont ses projets concrets, pas seulement ses diplômes ou son
expérience salariée. Les postes des familles qu'il vise lui conviennent tous, y compris l'informatique de bureau ;
ses centres d'intérêt (listés dans le profil) sont un bonus, JAMAIS une condition.
Monte la note quand le texte accueille les débutants, les autodidactes, la reconversion ou promet une formation.
pour / contre : 3 raisons courtes au plus. note_fr : UNE phrase de 25 mots maximum, adressée au candidat en le
TUTOYANT (« tu », « ton », jamais « vous »)."""


def judge(offer: dict, ex: dict, family: str, commute: int | None, profile: dict, engine: engines.Engine) -> dict:
    prefs = ", ".join(f"{FAMILY_FR.get(k, k)} ({v})" for k, v in (profile.get("target_families") or {}).items())
    exp = f"{ex.get('min_years_experience', 0)} an(s)" + (" exigés" if ex.get("experience_pro_mandatory") else "")
    content = PROMPT.format(
        profile=profile.get("text") or "(profil vide)", families=prefs,
        title=offer["title"], company=offer.get("company") or "?", city=offer.get("city") or "?",
        country=(offer.get("country") or "?").upper(),
        commute=f"{commute} min, OK pour lui" if commute is not None else "inconnu (à vérifier, ne le pénalise pas)",
        family=FAMILY_FR.get(family, family), summary=ex.get("summary_fr", ""),
        skills=", ".join(ex.get("skills", [])) or "non précisées", experience=exp,
        degree=ex.get("degree_required", "inconnu"), languages=", ".join(ex.get("languages_required", [])) or "aucune",
        contract=ex.get("contract", "inconnu"), excerpt=(offer.get("description") or "")[:1500])
    return engines.chat_json(engine, content, SCHEMA, max_tokens=500)
