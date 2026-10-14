"""Extraction of the FACTS of an offer (without the candidate's profile: it contaminated the extracted skills).

Model: the main (small) model, JSON output constrained by a grammar (engines.chat_json). Prompt in French.
"""
import json

from . import engines

FAMILIES = ["dev_software", "sysadmin_network_devops", "support_it", "ai_automation_data", "digital_fabrication",
            "electronics_iot", "it_other", "industrial_maintenance", "engineering_other", "finance_business",
            "sales_marketing", "healthcare_science", "logistics_production", "other_non_it"]
LANG = {"type": "string", "enum": ["fr", "en", "de", "lb", "nl", "other"]}
SCHEMA = {
    "type": "object",
    "required": ["job_family", "seniority", "degree_required", "degree_mandatory", "equivalence_accepted",
                 "experience_mentioned", "experience_pro_mandatory", "min_years_experience", "internship_counts",
                 "junior_friendly", "self_taught_welcome", "languages_required", "languages_nice", "remote",
                 "remote_days_per_week", "contract", "skills", "passion_match", "summary_fr"],
    "properties": {
        "job_family": {"type": "string", "enum": FAMILIES},
        "seniority": {"type": "string", "enum": ["stage", "junior", "confirme", "senior", "lead"]},
        "degree_required": {"type": "string", "enum": ["aucun", "bac", "bac+2/3", "master", "doctorat", "inconnu"]},
        "degree_mandatory": {"type": "boolean"},
        "equivalence_accepted": {"type": "boolean"},
        "experience_mentioned": {"type": "boolean"},
        "experience_pro_mandatory": {"type": "boolean"},
        "min_years_experience": {"type": "integer", "minimum": 0, "maximum": 20},
        "internship_counts": {"type": "boolean"},
        "junior_friendly": {"type": "boolean"},
        "self_taught_welcome": {"type": "boolean"},
        "languages_required": {"type": "array", "items": LANG, "maxItems": 5},
        "languages_nice": {"type": "array", "items": LANG, "maxItems": 5},
        "remote": {"type": "string", "enum": ["aucun", "partiel", "complet", "inconnu"]},
        "remote_days_per_week": {"type": "integer", "minimum": 0, "maximum": 5},
        "contract": {"type": "string", "enum": ["cdi", "cdd", "interim", "stage", "freelance", "inconnu"]},
        "skills": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "passion_match": {"type": "array", "maxItems": 5, "items": {"type": "string", "enum": [
            "impression_3d", "electronique", "fablab", "iot", "ia"]}},
        "summary_fr": {"type": "string", "maxLength": 240},
    },
}

PROMPT = """Tu lis une offre d'emploi et tu remplis le JSON avec les FAITS de l'offre, rien d'autre. N'invente rien.
- job_family : le métier réel. Conseil client, finance, fonds, audit, compta → finance_business ; vente → sales_marketing ;
  soins, labo, chimie → healthcare_science ; câblage, BTP, génie civil → engineering_other ; production, entrepôt,
  transport → logistics_production ; ERP / SAP / intégration applicative → it_other.
- degree_required : diplôme minimum EXIGÉ ; degree_mandatory : vrai seulement s'il est obligatoire sans alternative ;
  equivalence_accepted : vrai si « ou équivalent », « ou expérience équivalente » ou autodidactes acceptés.
- experience_pro_mandatory : vrai seulement si une expérience PROFESSIONNELLE est exigée (« requise », « minimum X ans »,
  « X+ years required »). Faux si « souhaitée », « un plus », « idéalement », « preferred » ou si débutants acceptés.
- internship_counts : vrai si un stage, une alternance ou des projets suffisent.
- junior_friendly / self_taught_welcome : vrai seulement si le texte le dit.
- languages_required : langues exigées ; languages_nice : souhaitées. « lb » = luxembourgeois.
- skills : UNIQUEMENT des technologies ou compétences écrites dans l'offre, en minuscules.
- passion_match : seulement si le poste consiste vraiment à faire de l'impression 3D, de l'électronique, du fablab,
  de l'IoT ou de l'IA.
- summary_fr : une phrase factuelle en français sur le poste.

Titre : {title}
Employeur : {company}
Lieu : {city} ({country})
Indications de la source : {hints}

Texte de l'offre :
{description}"""


def analyse(offer: dict, engine: engines.Engine | None = None) -> dict:
    content = PROMPT.format(title=offer["title"], company=offer.get("company") or "?", city=offer.get("city") or "?",
                            country=offer.get("country") or "?",
                            hints=json.dumps(offer.get("hints") or {}, ensure_ascii=False)[:600],
                            description=(offer.get("description") or "(pas de texte)")[:4500])
    return engines.chat_json(engine or engines.server(), content, SCHEMA, max_tokens=1000)
