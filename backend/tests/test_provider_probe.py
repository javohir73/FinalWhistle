"""probe_player_access: a no-secrets diagnostic for whether the api-sports key
reaches current-season player data (the prerequisite for goalscorer predictions).
api-sports answers 200 with an `errors` object on plan/quota issues, so
reachability is judged by the topscorers result count, never the HTTP status."""
from pipeline.ingest import api_football


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def _patch(monkeypatch, status_payload, topscorers_payload):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _Resp(status_payload if url.endswith("/status") else topscorers_payload)

    monkeypatch.setattr(api_football.requests, "get", fake_get)


def test_probe_reports_reachable_with_plan(monkeypatch):
    _patch(
        monkeypatch,
        {"response": {"subscription": {"plan": "Pro", "active": True},
                      "requests": {"current": 5, "limit_day": 7500}}},
        {"results": 20, "errors": [], "response": [{"player": {"name": "X"}}]},
    )
    out = api_football.probe_player_access("k", 1, 2026)
    assert out["plan"] == "Pro"
    assert out["player_data_reachable"] is True
    assert out["topscorers_results"] == 20


def test_probe_reports_blocked_on_plan_error(monkeypatch):
    _patch(
        monkeypatch,
        {"response": {"subscription": {"plan": "Free", "active": True}}},
        {"results": 0, "errors": {"plan": "Your subscription does not allow this"}, "response": []},
    )
    out = api_football.probe_player_access("k", 1, 2026)
    assert out["player_data_reachable"] is False
    assert out["topscorers_results"] == 0
    assert "subscription does not allow" in str(out["note"])


def test_probe_never_raises_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(api_football.requests, "get", boom)
    out = api_football.probe_player_access("k", 1, 2026)
    assert out["player_data_reachable"] is False
    assert "network down" in str(out["note"])
