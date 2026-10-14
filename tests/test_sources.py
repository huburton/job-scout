from pathlib import Path

from scout import sources

FIX = Path(__file__).parent / "fixtures"


def read(name):
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


def test_jobslu_list():
    offers = sources.parse_jobslu_list(read("jobslu-list.html"))
    assert len(offers) == 6
    o = next(x for x in offers if x["source_id"] == "900001")
    assert o["title"] == "Data analyst - Developer" and o["company"] == "Helix Insights SA"
    assert o["city"] == "Luxembourg" and o["country"] == "lu" and o["url"].endswith("Id=900001")
    assert {x["source_id"]: x["country"] for x in offers}["900002"] == "be"
    assert {x["source_id"]: x["country"] for x in offers}["900004"] == "fr"


def test_jobslu_detail():
    o = sources.parse_jobslu_detail({"source_id": "x", "hints": {}}, read("jobslu-detail.html"))
    assert o["description"].startswith("Your mission:") and "Python data pipelines" in o["description"]
    assert o["city"] == "Luxembourg" and o["hints"]["contract"] == "Permanent" and o["hints"]["hours"] == "Full Time"


def test_country_from_location():
    assert sources._country("Arlon") == "be" and sources._country("Longwy (France)") == "fr"
    assert sources._country("Esch-sur-Alzette") == "lu" and sources._country(None) == "lu"
    assert sources._country("Aubange (BE)") == "be" and sources._city("Ehlerange (LU)") == "Ehlerange"


def test_jobslu_detail_french_labels():
    page = ('<div class="inner-padding job-html-description">Autodidacte passionné bienvenu.</div>\n</div>'
            "<dt>Localisation:</dt><dd>Ehlerange (LU)</dd><dt>Type de contrat:</dt><dd>CDI</dd>"
            "<dt>Temps de travail:</dt><dd>Temps plein</dd>")
    o = sources.parse_jobslu_detail({"hints": {}}, page)
    assert o["city"] == "Ehlerange" and o["country"] == "lu" and o["hints"]["contract"] == "CDI"
    assert o["description"] == "Autodidacte passionné bienvenu."


def test_list_lu_cards():
    offers = sources.parse_list_lu(read("list.html"))
    assert len(offers) == 5
    o = offers[0]
    assert o["url"].startswith("https://app.skeeled.com/offer/c/") and "lang=fr" in o["url"]
    assert o["title"] == "Technicien.ne de laboratoire electronique"  # reference stripped, capitals lowered
    assert o["city"] == "Belval" and o["hints"]["contract"] == "Fixed-term"
    titles = [x["title"] for x in offers]
    assert "Developpeur logiciel junior" in titles and "Ingénieur data" in titles
    assert all(not x["title"].startswith(("FA-", "SD")) for x in offers)
    assert any(t.startswith("Internship – ") for t in titles)  # INT- references are internships


def test_science_center_jobs():
    offers = sources.parse_science_center(read("lsc.html"))
    titles = [o["title"] for o in offers]
    assert "Workshop & Digital Fabrication Technician" in titles
    fab = offers[titles.index("Workshop & Digital Fabrication Technician")]
    assert fab["hints"]["contract"].startswith("CDI") and fab["city"] == "Differdange"
    assert fab["url"] == "https://www.science-center.lu/en/fablab-technician"


def test_strip_html():
    assert sources.strip_html("<p>One&nbsp;<b>two</b></p><ul><li>three</li></ul>") == "One two \n three"
