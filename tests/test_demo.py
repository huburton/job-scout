import json
import sqlite3

import pytest

from scout import __main__ as cli
from scout import config, db, demo, extract, fit


@pytest.fixture
def isolated_config(monkeypatch):
    """demo.setup() rewrites config values: have them restored after each test."""
    for name in ("DEMO", "DATA_DIR", "OUT_DIR", "PROFILE_FILE", "PC_STATUS_URL", "NTFY_TOPIC"):
        monkeypatch.setattr(config, name, getattr(config, name))


@pytest.fixture
def demo_run(tmp_path, isolated_config):
    demo.setup(tmp_path)
    stats = cli.run()
    return stats, db.connect(), tmp_path


def test_demo_pipeline_end_to_end(demo_run):
    stats, con, tmp_path = demo_run
    assert stats["errors"] == 0 and stats["analysed"] == 5 and stats["skipped"] == 5
    ranked = [r["title"] for r in con.execute("SELECT title FROM offers WHERE score > 0 ORDER BY score DESC")]
    assert ranked[0] == "Technicien prototypage et impression 3D"  # open to beginners + proven interest
    reasons = {r["title"]: json.loads(r["score_detail"])["infos"][0]
               for r in con.execute("SELECT title, score_detail FROM offers WHERE score = 0")}
    assert reasons["Senior DevOps Engineer"] == "écartée : poste senior / encadrement"
    assert reasons["Comptable (H/F)"] == "écartée : métier hors sujet"
    assert "exige de" in reasons["Développeur full stack"]
    assert "expérience pro exigée" in reasons["Développeur backend Java"]
    assert "trajet 91 min" in reasons["Développeur web - Metz"]
    assert list((tmp_path / "out" / "digests").glob("*.md"))


def test_demo_render_lists_every_offer(demo_run):
    stats, con, _ = demo_run
    text = demo.render(con, stats)
    assert "10 offers collected, 5 scored, 5 excluded" in text
    assert all(o["title"] in text for o in demo.OFFERS)


def test_fake_llm_outputs_match_the_schemas(demo_run):
    _, con, _ = demo_run
    for row in con.execute("SELECT extracted FROM offers WHERE extracted LIKE '%job_family%'"):
        ex = json.loads(row["extracted"])
        for key in extract.SCHEMA["required"]:
            assert key in ex
        assert ex["job_family"] in extract.FAMILIES
    verdict = demo.fake_chat_json("Son profil :\npython\n\nFamilles de métiers x\n- Compétences demandées : python\n"
                                  "- Extrait du texte : débutants acceptés\n", fit.SCHEMA)
    assert set(fit.SCHEMA["required"]) <= set(verdict) and 0 <= verdict["fit"] <= 10


def test_demo_is_deterministic(tmp_path, isolated_config):
    results = []
    for n in range(2):
        demo.setup(tmp_path / f"w{n}")
        cli.run()
        results.append([tuple(r) for r in sqlite3.connect(tmp_path / f"w{n}" / "data" / "offers.db")
                        .execute("SELECT id, score FROM offers ORDER BY id")])
    assert results[0] == results[1]
