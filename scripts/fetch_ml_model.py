"""배포 빌드용 고정 ML 릴리스 아티팩트 다운로드와 SHA-256 검증."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare_model(local_model=None):
    config = json.loads((ROOT / "deploy/ml_model.json").read_text())
    destination = ROOT / "deploy/ml-models/model.joblib"
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(local_model) if local_model else Path(temporary) / config["asset"]
        if local_model is None:
            subprocess.run(
                [
                    "gh",
                    "release",
                    "download",
                    config["release_tag"],
                    "--repo",
                    config["repository"],
                    "--pattern",
                    config["asset"],
                    "--dir",
                    temporary,
                ],
                check=True,
                timeout=120,
            )
        if hashlib.sha256(source.read_bytes()).hexdigest() != config["sha256"]:
            raise ValueError("ML artifact checksum mismatch")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    print(f"ML artifact verified: {config['model_version']} {config['sha256']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-model", type=Path)
    args = parser.parse_args()
    prepare_model(args.local_model)


if __name__ == "__main__":
    main()
