import sys

from scripts import launch_desktop


def test_launcher_resolves_paths_and_passes_demo(tmp_path, monkeypatch):
    project = tmp_path / "folder with spaces"
    project.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["launcher", "--demo"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    calls = []

    def run(path, run_name):
        calls.append((path, run_name, list(sys.argv)))
        print("startup checked")

    monkeypatch.setattr(launch_desktop.runpy, "run_path", run)
    assert launch_desktop.launch(project) == 0
    assert calls == [(str(project / "main.py"), "__main__", [str(project / "main.py"), "--demo"])]
    assert "startup checked" in (project / "data/launcher.log").read_text(encoding="utf-8")


def test_launcher_logs_failure_and_shows_dialog(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["launcher"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    messages = []

    def fail(*args, **kwargs):
        raise ImportError("missing test dependency")

    monkeypatch.setattr(launch_desktop.runpy, "run_path", fail)
    monkeypatch.setattr(launch_desktop, "show_error", messages.append)
    assert launch_desktop.launch(tmp_path) == 1
    assert "missing test dependency" in (tmp_path / "data/launcher.log").read_text(encoding="utf-8")
    assert len(messages) == 1
    assert "uv sync --frozen" in messages[0]
