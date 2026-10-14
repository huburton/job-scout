"""Job family of an offer: title rules first, the LLM only gives a second opinion."""
import re

from .db import norm

# Most specific first (normalised text: lower case, no accents)
TITLE_RULES = [
    ("digital_fabrication", r"fab ?lab|makerspace|impressions? 3d|3d print|additive|prototyp|fabrication numerique|"
                            r"modelisation 3d|\bcao\b|\bcad\b|dessinateur"),
    ("electronics_iot", r"electroni|\biot\b|embarque|embedded|firmware|automaticien|\bpcb\b|hardware|mecatroni|"
                        r"robotique|robotics|objets connectes"),
    ("ai_automation_data", r"\bdata\b|donnees|\bia\b|\bai\b|machine learning|\bml\b|\bllm|intelligence artificielle|"
                           r"automatisation|\brpa\b|business intelligence|\bbi\b"),
    ("sysadmin_network_devops", r"administrateur (systemes?|reseaux?)|sysadmin|system administrator|devops|\bsre\b|cloud|"
                                r"infrastructure|network|reseaux? informatique|systemes? et reseaux|linux|platform engineer|"
                                r"systems? engineer|ingenieur systemes?|it ?/ ?ot"),
    ("support_it", r"support|helpdesk|help desk|service desk|technicien informatique|it technician|workplace|deskside|"
                   r"informaticien"),
    ("dev_software", r"developpeu|developer|\bdev\b|(software|systems?|web|application) development|"
                     r"development engineer|software|logiciel|full ?stack|back ?end|front ?end|\bweb\b|"
                     r"programm|\bsde\b|\bjava\b|python|\bphp\b|javascript|typescript|\.net\b|\bnet developer"),
]
TECH = {"dev_software", "sysadmin_network_devops", "support_it", "ai_automation_data", "digital_fabrication",
        "electronics_iot", "it_other"}
NON_TECH = {"finance_business", "sales_marketing", "healthcare_science", "logistics_production", "other_non_it"}
PASSION_FAMILIES = {"digital_fabrication", "electronics_iot"}


def from_title(title: str) -> str | None:
    t = norm(title)
    for family, pattern in TITLE_RULES:
        if re.search(pattern, t):
            return family
    return None


def resolve(title: str, llm_family: str | None) -> str:
    """Title first; if the LLM says the offer is clearly not tech (e.g. "Data entry clerk"), it has the last word."""
    by_title = from_title(title)
    if by_title and llm_family not in NON_TECH:
        return by_title
    return llm_family or by_title or "other_non_it"
