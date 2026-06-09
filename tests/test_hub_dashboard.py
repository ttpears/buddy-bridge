import importlib

from importlib.resources import files


def test_dashboard_resource_present_and_loaded():
    html = (files("buddybridge.resources") / "dashboard.html").read_text(encoding="utf-8")
    assert "CLAUDE" in html and "buddy" in html.lower()


def test_hub_module_uses_real_dashboard_not_fallback():
    hub = importlib.import_module("buddybridge.hub")
    importlib.reload(hub)
    assert "dashboard.html missing" not in hub.DASHBOARD_HTML
    assert "<!doctype html>" in hub.DASHBOARD_HTML.lower()
