"""Read-only content checks for the seeded and clean deployments; secrets stay local."""
import http.cookiejar
import json
from pathlib import Path
from urllib.request import HTTPCookieProcessor, Request, build_opener


def main():
    report = {}
    for kind in ("demo","clean"):
        root = Path(".pilot/instances") / kind
        values = dict(line.split("=",1) for line in (root/"compose.env").read_text().splitlines() if "=" in line)
        base = "http://127.0.0.1:" + values["WORKBENCH_INSTANCE_PORT"]
        opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

        def call(path,body=None,csrf=""):
            request = Request(base+path,data=None if body is None else json.dumps(body).encode(),
                              headers={"Content-Type":"application/json","X-Workbench-CSRF":csrf})
            with opener.open(request,timeout=15) as response:
                return json.load(response)

        session = call("/api/auth/login",{"username":"admin","password":(root/"admin-password").read_text().strip()})
        try:
            assert call("/health/ready")["status"] == "ready"
            usage = call("/api/pilot/usage")
            jobs = call("/api/pilot/evaluations")["evaluations"]
            proposals = call("/api/pilot/proposals")["proposals"]
            recordings = call("/api/pilot/recordings")["recordings"]
            if kind == "demo":
                assert usage["events"] == 144 and usage["task_count"] == 72
                assert usage["api_estimate_usd"] == "0.088074750"
                assert usage["evidence_counts"] == {"recorded":144}
                assert len(recordings) == len(jobs) == len(proposals) == 1
                result = call("/api/pilot/evaluations/"+jobs[0]["id"])
                assert result["status"] == "complete"
                assert [m["passed"] for m in result["analysis"]["models"]] == [20,18,14]
                assert proposals[0]["status"] == "no_eligible_model"
            else:
                assert usage["events"] == usage["task_count"] == 0
                assert recordings == jobs == proposals == []
                assert call("/api/pilot/sources")["sources"] == []
            report[kind] = {"ready":True,"events":usage["events"],"tasks":usage["task_count"],
                            "evaluations":len(jobs),"reviews":len(proposals)}
        finally:
            call("/api/auth/logout",{},session["csrf"])
    print(json.dumps(report))


if __name__ == "__main__":
    main()
