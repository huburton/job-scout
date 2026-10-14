from scout import config, engines


def status(idle=True, ai_mode=False, loaded=False, used=6000):
    return {"user_idle": idle, "ai_mode": ai_mode, "gpu": {"vram_used_mib": used, "vram_total_mib": 16303},
            "models": [{"id": config.PC_MODEL, "status": "loaded" if loaded else "unloaded"}]}


def pick(monkeypatch, st):
    monkeypatch.setattr(config, "PC_MODEL_MIB", 13000)
    monkeypatch.setattr(engines, "_pc_status", lambda: st)
    return engines.judge()


def test_pc_off_or_router_down_uses_server(monkeypatch):
    assert pick(monkeypatch, None).label == "server"
    assert pick(monkeypatch, {**status(), "models": None}).label == "server"


def test_hugo_at_the_pc_uses_server(monkeypatch):
    assert pick(monkeypatch, status(idle=False, ai_mode=True, used=1000)).label == "server"


def test_big_model_only_when_it_fits_in_vram(monkeypatch):
    assert pick(monkeypatch, status(used=11000)).label == "server"  # animated wallpaper + screensaver: the model would spill onto the CPU
    assert pick(monkeypatch, status(used=2000)).label == "pc-big"
    e = pick(monkeypatch, status(ai_mode=True, used=11000))
    assert e.label == "pc-big" and not e.was_loaded  # loaded by job-scout -> unloaded at the end of the batch
    assert pick(monkeypatch, status(loaded=True, used=15000)).label == "server"  # loaded next to the wallpaper: partly on CPU
    assert pick(monkeypatch, status(ai_mode=True, loaded=True, used=15000)).was_loaded


def test_second_machine_is_disabled_without_status_url(monkeypatch):
    monkeypatch.setattr(config, "PC_STATUS_URL", "")
    assert engines._pc_status() is None and engines.judge().label == "server"
