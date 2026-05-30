import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from mnemostroma.cli.commands import build_cli

class ArgparseCliRunner:
    class Result:
        def __init__(self, exit_code, output):
            self.exit_code = exit_code
            self.output = output

    def invoke(self, cli_parser, args):
        import sys
        from io import StringIO
        
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        
        exit_code = 0
        try:
            parsed_args = cli_parser.parse_args(args)
            from mnemostroma.cli.commands import dispatch
            dispatch(parsed_args)
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else 1
        except Exception:
            exit_code = 1
        finally:
            output = sys.stdout.getvalue()
            sys.stdout = old_stdout
            
        return self.Result(exit_code, output)

runner = ArgparseCliRunner()
cli = build_cli()

# T-01: ext_src существует → копируется в ~/.mnemostroma/extension
def test_install_extension_copies_dist(tmp_path, monkeypatch):
    ext_src = tmp_path / "package" / "extension" / "dist"
    ext_src.mkdir(parents=True)
    (ext_src / "manifest.json").write_text('{"manifest_version": 3}', encoding="utf-8")
    ext_dst = tmp_path / ".mnemostroma" / "extension"

    monkeypatch.setenv("MNEMO_DIR", str(tmp_path / ".mnemostroma"))
    monkeypatch.setattr("mnemostroma.cli.commands._MNEMO_DIR", tmp_path / ".mnemostroma")
    with patch("mnemostroma.cli.commands.EXT_SRC", ext_src):
        result = runner.invoke(cli, ["install-extension"])

    assert result.exit_code == 0
    assert (ext_dst / "manifest.json").exists()
    assert "Chrome" in result.output

# T-02: ext_src отсутствует → exit code 1, понятное сообщение
def test_install_extension_missing_source(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DIR", str(tmp_path))
    monkeypatch.setattr("mnemostroma.cli.commands._MNEMO_DIR", tmp_path)
    with patch("mnemostroma.cli.commands.EXT_SRC", tmp_path / "nonexistent"):
        result = runner.invoke(cli, ["install-extension"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()

# T-03: повторный вызов → dirs_exist_ok=True, не падает, обновляет файлы
def test_install_extension_idempotent(tmp_path, monkeypatch):
    ext_src = tmp_path / "dist"
    ext_src.mkdir()
    (ext_src / "manifest.json").write_text('{"v": 1}', encoding="utf-8")
    monkeypatch.setenv("MNEMO_DIR", str(tmp_path / ".mnemostroma"))
    monkeypatch.setattr("mnemostroma.cli.commands._MNEMO_DIR", tmp_path / ".mnemostroma")

    with patch("mnemostroma.cli.commands.EXT_SRC", ext_src):
        runner.invoke(cli, ["install-extension"])
        (ext_src / "manifest.json").write_text('{"v": 2}', encoding="utf-8")
        result = runner.invoke(cli, ["install-extension"])

    assert result.exit_code == 0
    dst = tmp_path / ".mnemostroma" / "extension" / "manifest.json"
    assert '"v": 2' in dst.read_text(encoding="utf-8")

# T-04: вывод содержит правильный путь к extension
def test_install_extension_prints_correct_path(tmp_path, monkeypatch):
    ext_src = tmp_path / "dist"
    ext_src.mkdir()
    (ext_src / "manifest.json").write_text("{}", encoding="utf-8")
    mnemo_dir = tmp_path / ".mnemostroma"
    monkeypatch.setenv("MNEMO_DIR", str(mnemo_dir))
    monkeypatch.setattr("mnemostroma.cli.commands._MNEMO_DIR", mnemo_dir)

    with patch("mnemostroma.cli.commands.EXT_SRC", ext_src):
        result = runner.invoke(cli, ["install-extension"])

    assert str(mnemo_dir / "extension") in result.output
