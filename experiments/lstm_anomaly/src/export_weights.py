"""학습된 가중치를 torch 없이 읽을 수 있는 .npz 로 내보낸다.

왜 ONNX 가 아닌가.
  프롬프트 §5 는 "서비스 연동이 필요하면 ONNX" 를 제안하지만, 그러려면 백엔드에
  onnxruntime(수십 MB)이 들어가야 한다. 백엔드는 MQTT 수신과 안전 경보 판정을 하는
  안전 필수 컨테이너다. 이 모델은 LSTM 두 개와 Linear 세 개가 전부라 numpy 행렬곱
  60줄이면 그대로 돌아간다. 런타임 하나를 더 얹어 기동 실패 지점을 늘릴 이유가 없다.

  대신 백엔드에 numpy 를 추가한다. numpy 는 학습 프레임워크가 아니라 수치 계산
  라이브러리이고, §5 가 금지한 것은 "무거운 학습 의존성"이다.

실행:
  .venv/bin/python -m src.export_weights --artifact artifacts/demo
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

WEIGHTS_FILENAME = "model_weights.npz"


def export(artifact_dir: Path) -> Path:
    state = torch.load(artifact_dir / "model.pt", map_location="cpu", weights_only=True)
    arrays = {key: value.detach().cpu().numpy().astype("float32")
              for key, value in state.items()}

    manifest = json.loads((artifact_dir / "feature_manifest.json").read_text(encoding="utf-8"))
    # 추론 쪽이 shape 를 추측하지 않도록 구조를 함께 박아둔다.
    arrays["_n_features"] = np.array([manifest["n_features"]], dtype="int64")
    arrays["_hidden_size"] = np.array(
        [arrays["encoder.weight_hh_l0"].shape[1]], dtype="int64"
    )
    arrays["_latent_size"] = np.array(
        [arrays["to_latent.weight"].shape[0]], dtype="int64"
    )

    out = artifact_dir / WEIGHTS_FILENAME
    np.savez(out, **arrays)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="model.pt -> model_weights.npz")
    parser.add_argument("--artifact", required=True)
    args = parser.parse_args()
    path = export(Path(args.artifact))
    data = np.load(path)
    print(f"wrote {path}")
    print(f"  n_features={int(data['_n_features'][0])} "
          f"hidden={int(data['_hidden_size'][0])} latent={int(data['_latent_size'][0])}")
    print("  arrays:", ", ".join(k for k in data.files if not k.startswith("_")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
