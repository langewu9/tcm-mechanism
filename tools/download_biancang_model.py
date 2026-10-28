from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


MODEL_ID = "QLUNLP/BianCang-Qwen2.5-7B-Instruct"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS_DIR = PROJECT_ROOT / ".deps" / "biancang"
LOCAL_CACHE_DIR = PROJECT_ROOT / ".cache" / "modelscope"
LOCAL_CREDENTIALS_DIR = PROJECT_ROOT / ".cache" / "modelscope-credentials"
DEFAULT_LOCAL_DIR = PROJECT_ROOT / "models" / "BianCang-Qwen2.5-7B-Instruct"

if LOCAL_DEPS_DIR.exists():
    sys.path.insert(0, str(LOCAL_DEPS_DIR))

os.environ.setdefault("MODELSCOPE_CACHE", str(LOCAL_CACHE_DIR))
os.environ.setdefault("MODELSCOPE_CREDENTIALS_PATH", str(LOCAL_CREDENTIALS_DIR))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download BianCang-Qwen2.5-7B-Instruct from ModelScope.")
    parser.add_argument("--local-dir", default=str(DEFAULT_LOCAL_DIR), help="Directory to store the full model.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    local_dir = Path(args.local_dir).resolve()
    local_dir.mkdir(parents=True, exist_ok=True)

    try:
        from modelscope import snapshot_download
    except ModuleNotFoundError:
        print("modelscope is not installed. Run:")
        print(r'D:\mini\envs\py310\python.exe -m pip install --target .deps\biancang -r requirements-biancang.txt')
        return 1

    model_dir = snapshot_download(MODEL_ID, local_dir=str(local_dir))
    print(f"Downloaded {MODEL_ID}")
    print(f"Model directory: {model_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
