"""Explicit opt-in model download; pinned resolved revision is saved for reproduction."""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "var/models/bge-small-zh-v1.5")
    parser.add_argument("--revision", default=os.getenv("OPS_MODEL_REVISION", "7999e1d3359715c523056ef9478215996d62a620"))
    args = parser.parse_args()
    os.environ.setdefault("HF_HOME", str(ROOT / "var/hf-cache"))
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    try:
        from huggingface_hub import model_info, snapshot_download
    except ImportError:
        parser.error("Install the semantic extra first: pip install '.[semantic]'")
    repo = "BAAI/bge-small-zh-v1.5"
    target = args.output_dir.expanduser()
    info = model_info(repo, revision=args.revision)
    names = {file.rfilename for file in info.siblings}
    weights = "model.safetensors" if "model.safetensors" in names else "pytorch_model.bin"
    snapshot_download(repo, revision=info.sha, local_dir=target,
                      allow_patterns=[weights, "*.json", "*.txt", "1_Pooling/*", "README.md", "LICENSE"])
    manifest = {"repo_id": repo, "revision": info.sha, "weights": weights,
                "query_prefix": "为这个句子生成表示以用于检索相关文章："}
    (target / "opspilot_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(target), **manifest}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
