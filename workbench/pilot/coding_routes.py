"""Read-only coding evidence. The API never runs submitted code or containers."""
from fastapi import Depends, HTTPException

from workbench.billing_acceptance import read_json
from workbench.coding import DATA, verify_result


def register(app, member):
    @app.get("/api/pilot/coding/example")
    def example(actor=Depends(member)):
        return verify_result(read_json(DATA / "example-result.json", 8_000_000))

    @app.get("/api/pilot/coding/calibration")
    def calibration(actor=Depends(member)):
        return verify_result(read_json(DATA / "calibration-result.json", 8_000_000))

    @app.post("/api/pilot/coding/preview")
    def preview(payload: dict, actor=Depends(member)):
        try:
            return verify_result(payload)
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            raise HTTPException(422, "Invalid coding result, contract, checksums, or accounting") from None
