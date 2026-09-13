from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def test_serves_built_client_when_static_dir_exists(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html>digital-twin</html>", encoding="utf-8")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            assert "digital-twin" in client.get("/").text
            # API routes keep precedence over the static mount.
            assert client.get("/api/health").json()["ok"] is True
    finally:
        get_settings.cache_clear()


def test_no_static_mount_in_dev():
    # Dev: no static dir, so / has nothing to serve (Vite owns the client).
    with TestClient(create_app()) as client:
        assert client.get("/").status_code == 404
