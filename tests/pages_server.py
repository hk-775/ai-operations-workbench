"""Serve only the built public files, with real byte-range responses for media."""
import argparse
from pathlib import Path

from starlette.staticfiles import StaticFiles
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18771)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]/"artifacts/pages"
    uvicorn.run(StaticFiles(directory=root, html=True), host="127.0.0.1",
                port=args.port, access_log=False)
