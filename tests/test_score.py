from scout import families, score
from scout.db import norm
from scout.profile import DEFAULT

PROFILE = {**DEFAULT, "skills": ["python", "linux", "docker", "home assistant", "3d printing"]}


def ex(**kw):
    base = {"job_family": "sysadmin_network_devops", "seniority": "junior", "degree_required": "inconnu",
            "degree_mandatory": False, "equivalence_accepted": False, "experience_mentioned": False,
            "experience_pro_mandatory": False, "min_years_experience": 0, "internship_counts": False,
            "junior_friendly": True, "self_taught_welcome": False, "languages_required": ["fr"],
            "languages_nice": ["en"], "remote": "partiel", "remote_days_per_week": 1, "contract": "cdi",
            "skills": ["linux", "docker"], "passion_match": [], "summary_fr": ""}
    base.update(kw)
    return base


LU = {"country": "lu", "title": "Administrateur système Linux junior", "description": "Débutant accepté. Linux, Docker."}


def test_family_from_title():
    assert families.from_title("Référent(e) Technique Atelier & Fabrication Numérique") == "digital_fabrication"
    assert families.from_title("Electronicien / Automaticien industriel (H/F/X)") == "electronics_iot"
    assert families.from_title("IT Helpdesk Support") == "support_it"
    assert families.from_title("Junior Back End Dev") == "dev_software"
    assert families.from_title("System Development Engineer, ShipTech Analytics") == "dev_software"
    assert families.from_title("Business Development Representative") is None
    assert families.from_title("IT/OT System Engineer (H/F/X)") == "sysadmin_network_devops"
    assert families.from_title("Depositary Oversight Specialist, Officer") is None
    assert families.from_title("Monteur Câbleur Débutant en Signalisation Ferroviaire") is None


def test_llm_non_tech_verdict_wins_over_ambiguous_title():
    assert families.resolve("Data entry clerk", "other_non_it") == "other_non_it"
    assert families.resolve("Client Implementation & Service, Associate 2", "finance_business") == "finance_business"
    assert families.resolve("Développeur web", "it_other") == "dev_software"


def test_non_target_family_is_excluded():
    assert score.gate(ex(), "finance_business", 64, LU, PROFILE).startswith("métier hors de tes familles")
    assert score.gate(ex(), "engineering_other", 20, LU, PROFILE).startswith("métier hors de tes familles")


def test_commute_rules_depend_on_country_and_passion():
    fr = {"country": "fr", "title": "Développeur", "description": ""}
    assert score.gate(ex(), "dev_software", 91, fr, PROFILE) == "trajet 91 min (max 50 hors Luxembourg)"  # Metz
    assert score.gate(ex(), "dev_software", 95, LU, PROFILE) is None                                     # LU : ok
    assert score.gate(ex(), "digital_fabrication", 59, {**fr, "country": "be"}, PROFILE) is None          # passion
    assert score.gate(ex(), "dev_software", 59, {**fr, "country": "be"}, PROFILE).startswith("trajet")


def test_blocked_languages():
    offer = {**LU, "description": "Allemand courant exigé."}
    assert score.gate(ex(languages_required=["fr", "de"]), "sysadmin_network_devops", 64, offer, PROFILE) == "exige de"
    eures = {**LU, "hints": {"languages": [{"code": "lb", "level": "b1"}]}}
    assert score.gate(ex(), "sysadmin_network_devops", 64, eures, PROFILE) == "exige lb"


def test_mandatory_experience_and_degree():
    offer = {**LU, "description": "Minimum 3 ans d'expérience professionnelle exigés."}
    assert "3 ans" in score.gate(ex(experience_pro_mandatory=True, min_years_experience=3), "dev_software", 64, offer, PROFILE)
    amazon = {**LU, "description": "Basic qualifications: 1+ years of non-internship professional experience."}
    assert "dans le texte" in score.gate(ex(), "dev_software", 64, amazon, PROFILE)
    master = {**LU, "description": "Master en informatique obligatoire."}
    assert score.gate(ex(degree_required="master", degree_mandatory=True), "dev_software", 64, master, PROFILE) == "diplôme exigé (master)"
    equiv = {**LU, "description": "Bachelier ou expérience équivalente."}
    assert score.gate(ex(degree_required="bac+2/3", degree_mandatory=True, equivalence_accepted=True),
                      "dev_software", 64, equiv, PROFILE) is None


def test_wished_experience_does_not_exclude():
    offer = {**LU, "description": "Idéalement 2 ans d'expérience, stage compris."}
    assert score.gate(ex(min_years_experience=2), "dev_software", 64, offer, PROFILE) is None


def test_prefilter_titles():
    assert score.prefilter({"title": "Aide-soignant DE H/F en EHPAD"}) == "métier hors sujet"
    assert score.prefilter({"title": "Depositary Oversight Specialist, Officer"}) == "métier hors sujet"
    assert score.prefilter({"title": "Senior .net Backend Engineer (m/f)"}) == "poste senior / encadrement"
    assert score.prefilter({"title": "Administrateur serveur Linux"}) is None
    assert score.prefilter({"title": "Northwind junior master data manager"}) is None
    assert score.prefilter({"title": "Business Intelligence Intern Luxembourg"}).startswith("stage")
    assert score.prefilter({"title": "Stagiaire développeur web"}).startswith("stage")
    assert score.prefilter({"title": "Développeur web en alternance"}) is None
    assert score.prefilter({"title": "PhD in nanoscale electro-optic control"}).startswith("poste de recherche")
    assert score.prefilter({"title": "Postdoctoral researcher in AI-based energy management"}).startswith("poste de recherche")
    assert score.prefilter({"title": "Research Support Technician"}) is None
    assert score.prefilter({"title": "Service Desk Supervisor - (CDI) (m/f)"}) == "poste senior / encadrement"
    assert score.prefilter({"title": "PRODUKTIONSMITARBEITER (M/W/D)"}) == "annonce en allemand"
    assert score.prefilter({"title": "CAD Zeichner / Konstrukteur (m/w/d)"}) == "annonce en allemand"
    assert score.prefilter({"title": "Technicien helpdesk (m/f/d)"}) is None
    assert score.prefilter({"title": "Projektleiter IT (m/w/d)"}) == "annonce en allemand"


def test_years_in_text_detection():
    amazon = norm("BASIC QUALIFICATIONS - 1+ years of non-internship professional software development experience. "
                  "PREFERRED QUALIFICATIONS - 3+ years of full software development life cycle experience")
    assert score.required_years_in_text(amazon) == 1
    assert score.required_years_in_text(norm("Idéalement 2 ans d'expérience, débutants acceptés.")) == 0


def test_fit_drives_the_score():
    be = {**LU, "country": "be"}
    good, d = score.compute(ex(), "sysadmin_network_devops", 49, be, PROFILE,
                            {"fit": 9, "pour": ["Linux"], "contre": [], "note_fr": "Fonce."})
    meh, _ = score.compute(ex(), "sysadmin_network_devops", 49, be, PROFILE,
                           {"fit": 3, "pour": [], "contre": ["Loin de tes envies"], "note_fr": "Bof."})
    assert good >= 75 and good - meh == 18 and d["fit"] == "Fonce."


def test_skills_are_matched_against_profile_not_invented():
    _, d = score.compute(ex(skills=["linux", "sap abap", "comptabilité"]), "dev_software", 64, LU, PROFILE, None)
    assert d["compétences_trouvées"] == ["linux"]


def test_title_only_offers_are_capped():
    s, d = score.compute(ex(), "support_it", 64, {**LU, "hints": {"title_only": True}}, PROFILE,
                         {"fit": 10, "pour": [], "contre": [], "note_fr": ""})
    assert s == 60 and any("titre seul" in i for i in d["infos"])


def test_passion_needs_evidence():
    offer = {**LU, "title": "Gestionnaire IAM", "description": "Gestion des accès."}
    _, d = score.compute(ex(passion_match=["ia"]), "sysadmin_network_devops", 64, offer, PROFILE, None)
    assert d["passions"] == []
    fab = {**LU, "title": "Technicien fablab", "description": "Parc d'imprimantes 3D et découpe laser."}
    _, d = score.compute(ex(passion_match=["impression_3d", "fablab"]), "digital_fabrication", 57, fab, PROFILE, None)
    assert d["passions"] == ["fablab", "impression_3d"] and d["points"]["intérêt"] == 25


def test_eures_form_years_alone_do_not_exclude():
    fab = {**LU, "title": "Référent technique atelier fabrication numérique", "hints": {"years_experience": 2},
           "description": "Expérience pratique en impression 3D, découpe laser et CNC."}
    assert score.gate(ex(), "digital_fabrication", 57, fab, PROFILE) is None
    _, d = score.compute(ex(), "digital_fabrication", 57, fab, PROFILE, None)
    assert any("formulaire EURES" in i for i in d["infos"])
    stated = {**fab, "description": "Minimum 2 ans d'expérience professionnelle requise."}
    assert score.gate(ex(), "digital_fabrication", 57, stated, PROFILE).startswith("expérience pro exigée (2 ans")


def test_ai_passion_only_for_ai_jobs():
    sde = {**LU, "title": "Software Dev Engineer", "description": "Java microservices. Leverage GenAI and AI-powered tools."}
    _, d = score.compute(ex(passion_match=["ia"]), "dev_software", 64, sde, PROFILE, None)
    assert d["passions"] == []
    _, d = score.compute(ex(passion_match=["ia"]), "ai_automation_data", 64, {**sde, "title": "AI engineer"}, PROFILE, None)
    assert d["passions"] == ["ia"]


def test_student_only_offers_are_excluded():
    amazon = {**LU, "description": "Basic Qualifications. Education: Currently enrolled in or completed a Bachelor's "
                                   "degree. Expected graduation between October 2025 - September 2026."}
    assert score.gate(ex(), "dev_software", 64, amazon, PROFILE) == "réservé aux étudiants / diplômés récents"


def test_accessible_offers_rank_above_demanding_ones():
    open_ = {**LU, "title": "Technicien support informatique", "description": "Débutants acceptés, formation assurée. Vous êtes motivé."}
    closed = {**LU, "title": "Technicien support informatique", "description": "Idéalement 3 ans d'expérience en support. Bachelier souhaité."}
    a, da = score.compute(ex(), "support_it", 64, open_, PROFILE, {"fit": 6, "pour": [], "contre": [], "note_fr": ""})
    b, _ = score.compute(ex(degree_required="bac+2/3"), "support_it", 64, closed, PROFILE, {"fit": 6, "pour": [], "contre": [], "note_fr": ""})
    assert a - b >= 20 and da["accessible"] and da["infos"][0].startswith("accessible")


def test_office_it_scores_like_passion_family():
    office = {**LU, "title": "Helpdesk IT", "description": "Support aux utilisateurs, postes Windows."}
    fab = {**LU, "title": "Technicien fablab", "description": "Support aux utilisateurs de l'atelier."}
    a, _ = score.compute(ex(), "support_it", 64, office, PROFILE, None)
    b, _ = score.compute(ex(), "digital_fabrication", 64, fab, PROFILE, None)
    assert a == b  # la passion n'est qu'un bonus quand elle est prouvée par le texte


def test_llm_seniority_and_degree_need_text_evidence():
    plc_offer = {**LU, "title": "Automaticien (H-F)", "description": "Profil : Bac +2/+3 en automatisme ou équivalent. KNX, Modbus."}
    base, _ = score.compute(ex(seniority="junior", degree_required="bac+2/3"), "electronics_iot", 64, plc_offer, PROFILE, None)
    wrong, _ = score.compute(ex(seniority="senior", degree_required="bac+2/3"), "electronics_iot", 64, plc_offer, PROFILE, None)
    assert wrong == base  # le 4B dit « senior », le texte ne le dit pas ; « ou équivalent » annule le diplôme
    assert score.gate(ex(degree_required="bac+2/3", degree_mandatory=True), "electronics_iot", 64, plc_offer, PROFILE) is None
    senior = {**plc_offer, "description": "Profil senior, 5 ans d'expérience souhaités."}
    s2, _ = score.compute(ex(seniority="senior"), "electronics_iot", 64, senior, PROFILE, None)
    assert s2 < base


def test_city_found_in_title_when_missing():
    from scout import geo
    assert geo._city_in_text({"title": "Alternance DEVELOPPEUR WEB FULLSTACK - Metz", "description": ""}) == 91
    assert geo._city_in_text({"title": "Technicien", "description": "Poste basé à Arlon, proche du Luxembourg."}) == 49
    assert geo._city_in_text({"title": "Technicien", "description": "Télétravail."}) is None
