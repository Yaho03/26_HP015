"""topology_check CLI 검증 (이슈 #225 수용기준 잠금).

프로덕션 YAML 이 #225 의 SW 검증 가능 수용기준을 계속 만족하는지 확인한다.
현장 측정 담당자가 YAML 을 교체한 뒤에도 이 테스트가 CI 에서 같은 판정을
내린다 — CLI 와 CI 가 어긋나면 워크시트 안내가 거짓이 된다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def cli_module():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import topology_check

    yield topology_check
    sys.path.pop(0)


def test_cli_passes_on_current_yaml(cli_module, capsys):
    """저장소 골격 YAML — 구조 기준 전항목 통과 (실측 여부는 별개, OQ-V5)."""
    exit_code = cli_module.main([])
    captured = capsys.readouterr().out
    assert exit_code == 0
    assert "[PASS]" in captured
    # 무엇을 판정하지 못하는지 안내가 항상 따라온다 — PASS 가 오해를 낳지 않게.
    assert "OQ-V5" in captured


def test_cli_fails_when_only_one_usable_exit(cli_module, tmp_path, capsys):
    """사용 가능 출구 1개 → FAIL (#225: EXP-8.2 전-출구-차단의 전제)."""
    source = (REPO_ROOT / "config" / "space_topology.yaml").read_text(encoding="utf-8")
    # 후방 출구를 비활성화해 사용 가능 출구를 1개로 만든다.
    tampered = source.replace(
        'exit_id: trunk-aft, nav_node_id: nav.exit.trunk-aft, kind: ladder_out, x_m: 58.0, y_m: 0.0, z_m: 14.0, is_usable: true',
        'exit_id: trunk-aft, nav_node_id: nav.exit.trunk-aft, kind: ladder_out, x_m: 58.0, y_m: 0.0, z_m: 14.0, is_usable: false',
    )
    assert tampered != source, "출구 라인을 찾지 못했다 — 골격 변경 시 테스트도 갱신"
    bad = tmp_path / "bad.yaml"
    bad.write_text(tampered, encoding="utf-8")

    exit_code = cli_module.main(["--file", str(bad)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "2개 이상" in out


def test_cli_fails_on_nonpositive_length(cli_module, tmp_path, capsys):
    source = (REPO_ROOT / "config" / "space_topology.yaml").read_text(encoding="utf-8")
    tampered = source.replace("length_m: 26.0, traverse_factor: 1.0", "length_m: 0.0, traverse_factor: 1.0", 1)
    assert tampered != source
    bad = tmp_path / "bad2.yaml"
    bad.write_text(tampered, encoding="utf-8")

    exit_code = cli_module.main(["--file", str(bad)])
    out = capsys.readouterr().out
    assert exit_code == 1
    # 파서(positive-discriminator)가 먼저 거부하거나 check() 의 양수 검사가
    # 걸린다 — 어느 쪽이든 0/음 길이는 FAIL 이어야 한다.
    assert ("greater than 0" in out) or ("양수" in out)
