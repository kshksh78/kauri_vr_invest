from pathlib import Path


def test_deployment_preserves_runtime_and_binds_loopback():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts/deploy_wsl.sh").read_text()
    unit = (root / "deploy/kauri-vr.service").read_text()
    assert "backup(" in script
    assert "--exclude=runtime/" in script
    assert "--exclude=.venv/" in script
    assert "--host 127.0.0.1 --port 8787" in unit
    assert "Restart=on-failure" in unit
