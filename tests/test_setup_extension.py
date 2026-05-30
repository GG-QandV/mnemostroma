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

# T-05: setup копирует extension если ext_src есть и ext_dst нет
def test_setup_copies_extension_when_missing(tmp_path, monkeypatch):
    ext_src = tmp_path / "pkg" / "extension" / "dist"
    ext_src.mkdir(parents=True)
    (ext_src / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("MNEMO_DIR", str(tmp_path / ".mnemostroma"))
    monkeypatch.setattr("mnemostroma.cli.commands._MNEMO_DIR", tmp_path / ".mnemostroma")

    with patch("mnemostroma.cli.commands.EXT_SRC", ext_src), \
         patch("mnemostroma.cli.commands._install_models"), \
         patch("mnemostroma.setup.tls.generate_passthrough_tls", return_value=("cert", "key", "ca")), \
         patch("mnemostroma.cli.commands._cmd_on"), \
         patch("subprocess.Popen"):
        result = runner.invoke(cli, ["setup"])

    assert (tmp_path / ".mnemostroma" / "extension" / "manifest.json").exists()
    assert "extension" in result.output.lower()

# T-06: setup НЕ перезаписывает extension если ext_dst уже существует
def test_setup_does_not_overwrite_existing_extension(tmp_path, monkeypatch):
    ext_dst = tmp_path / ".mnemostroma" / "extension"
    ext_dst.mkdir(parents=True)
    (ext_dst / "manifest.json").write_text('{"existing": true}', encoding="utf-8")
    monkeypatch.setenv("MNEMO_DIR", str(tmp_path / ".mnemostroma"))
    monkeypatch.setattr("mnemostroma.cli.commands._MNEMO_DIR", tmp_path / ".mnemostroma")

    with patch("mnemostroma.cli.commands._install_models"), \
         patch("mnemostroma.setup.tls.generate_passthrough_tls", return_value=("cert", "key", "ca")), \
         patch("mnemostroma.cli.commands._cmd_on"), \
         patch("subprocess.Popen"):
        runner.invoke(cli, ["setup"])

    assert '{"existing": true}' in (ext_dst / "manifest.json").read_text(encoding="utf-8")

# T-07: setup не падает если ext_src отсутствует (graceful degradation)
def test_setup_survives_missing_ext_src(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DIR", str(tmp_path / ".mnemostroma"))
    monkeypatch.setattr("mnemostroma.cli.commands._MNEMO_DIR", tmp_path / ".mnemostroma")
    with patch("mnemostroma.cli.commands.EXT_SRC", tmp_path / "nonexistent"), \
         patch("mnemostroma.cli.commands._install_models"), \
         patch("mnemostroma.setup.tls.generate_passthrough_tls", return_value=("cert", "key", "ca")), \
         patch("mnemostroma.cli.commands._cmd_on"), \
         patch("subprocess.Popen"):
        result = runner.invoke(cli, ["setup"])

    assert result.exit_code == 0  # setup не должен падать из-за extension
