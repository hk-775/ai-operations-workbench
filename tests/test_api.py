import json

from fastapi.testclient import TestClient

from workbench.app import create_app
from workbench.domain import ROOT


def test_local_boundary_and_import_errors(tmp_path):
    app=create_app(tmp_path, ROOT/"data/model-comparison.json")
    client=TestClient(app)
    assert client.get("/api/state").json()["connected"] is False
    assert client.post("/api/connect",json={},headers={"Origin":"https://evil.example"}).status_code == 403
    assert client.get("/api/state",headers={"Host":"attacker.example"}).status_code == 403
    assert client.post("/api/connect",content="{}",headers={"Content-Type":"text/plain"}).status_code == 415
    assert client.post("/api/import",json={"schema":"unknown"}).status_code == 422
    recording=json.loads((ROOT/"data/model-comparison.json").read_text())
    for path,value in [
        (("samples",0),None),
        (("samples",0,"stages",0),None),
        (("samples",0,"model"),[]),
        (("samples",0,"stages",0,"usage"),None),
        (("samples",0,"stages",0,"provider_response_id"),42),
        (("created_at",),None),
    ]:
        import copy
        broken=copy.deepcopy(recording)
        target=broken
        for key in path[:-1]:
            target=target[key]
        target[path[-1]]=value
        assert client.post("/api/import",json=broken).status_code == 422
        assert client.get("/api/state").json()["connected"] is False
    assert client.post("/api/import",content='{"schema":1,"schema":2}',
                       headers={"Content-Type":"application/json"}).status_code == 422
    assert client.post("/api/recommend",json={}).status_code == 409
    result=client.post("/api/connect",json={})
    assert result.status_code == 200
    assert result.json()["added_events"] == 144
    assert client.post("/api/connect",json={}).json()["added_events"] == 0
    assert client.get("/api/state").json()["calls"] == 144
    assert client.get("/api/state").json()["unknown_cost_calls"] == 0


def test_saved_recording_replays_all_calls_and_keeps_real_failures():
    from workbench.evidence import analyze,recommend
    report=analyze(json.loads((ROOT/"data/model-comparison.json").read_text()))
    assert report["total_calls"] == 144
    assert [m["passed"] for m in report["models"]] == [20,18,14]
    assert [m["critical_failures"] for m in report["models"]] == [1,1,1]
    assert report["total_cost_usd"] == "0.088074750"
    assert recommend(report)["status"] == "no_eligible_model"
