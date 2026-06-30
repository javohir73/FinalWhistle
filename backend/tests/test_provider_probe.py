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


def test_probe_player_sample_walks_teams_squad_player(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/teams"):
            return _Resp({"response": [{"team": {"id": 6, "name": "Brazil"}}]})
        if url.endswith("/players/squads"):
            return _Resp({"response": [{"team": {"id": 6},
                                        "players": [{"id": 1179, "name": "Vinicius", "position": "Attacker"}]}]})
        return _Resp({"response": [{"player": {"id": 1179, "name": "Vinicius"},
                                    "statistics": [{"goals": {"total": 24}, "games": {"minutes": 2800}}]}]})

    monkeypatch.setattr(api_football.requests, "get", fake_get)
    out = api_football.probe_player_sample("k", 1, 2026, 2025)
    assert out["team"]["team"]["id"] == 6
    assert out["squad_player"]["id"] == 1179
    assert out["player_stats"]["player"]["id"] == 1179
    assert out["note"] is None


def test_probe_player_sample_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(api_football.requests, "get", boom)
    out = api_football.probe_player_sample("k", 1, 2026, 2025)
    assert out["team"] is None
    assert "network down" in str(out["note"])


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
