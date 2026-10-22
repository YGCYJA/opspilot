"""Download an actual small generative model for local, credential-free testing."""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "var/models/Qwen3-0.6B")
    parser.add_argument("--revision", default=os.getenv("OPS_CHAT_REVISION", "c1899de289a04d12100db370d81485cdf75e47ca"))
    args = parser.parse_args()
    os.environ.setdefault("HF_HOME", str(ROOT / "var/hf-cache"))
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    try:
        from huggingface_hub import model_info, snapshot_download
    except ImportError:
        parser.error("Install the local extra first: pip install '.[local]'")
    repo = "Qwen/Qwen3-0.6B"
    target = args.output_dir.expanduser()
    info = model_info(repo, revision=args.revision)
    snapshot_download(repo, revision=info.sha, local_dir=target,
                      allow_patterns=["*.safetensors", "*.json", "*.txt", "*.jinja", "*.model", "README.md", "LICENSE"],
                      max_workers=2)
    manifest = {"repo_id": repo, "revision": info.sha, "data_kind": "public_pretrained_weights",
                "source": "https://huggingface.co/Qwen/Qwen3-0.6B"}
    (target / "opspilot_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(target), **manifest}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
