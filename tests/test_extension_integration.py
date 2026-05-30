import pytest
from unittest.mock import patch
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

# T-10: после mnemostroma setup папка extension существует и не пустая
def test_setup_produces_loadable_extension(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DIR", str(tmp_path / ".mnemostroma"))
    monkeypatch.setattr("mnemostroma.cli.commands._MNEMO_DIR", tmp_path / ".mnemostroma")
    
    with patch("mnemostroma.cli.commands._install_models"), \
         patch("mnemostroma.setup.tls.generate_passthrough_tls", return_value=("cert", "key", "ca")), \
         patch("mnemostroma.cli.commands._cmd_on"), \
         patch("subprocess.Popen"):
        result = runner.invoke(cli, ["setup"])

    ext_dst = tmp_path / ".mnemostroma" / "extension"
    assert ext_dst.exists()
    files = list(ext_dst.rglob("*"))
    assert len(files) > 0, "extension directory is empty after setup"

# T-11: install-extension после setup не ломает уже установленное расширение
def test_install_extension_after_setup_is_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DIR", str(tmp_path / ".mnemostroma"))
    monkeypatch.setattr("mnemostroma.cli.commands._MNEMO_DIR", tmp_path / ".mnemostroma")
    
    with patch("mnemostroma.cli.commands._install_models"), \
         patch("mnemostroma.setup.tls.generate_passthrough_tls", return_value=("cert", "key", "ca")), \
         patch("mnemostroma.cli.commands._cmd_on"), \
         patch("subprocess.Popen"):
        runner.invoke(cli, ["setup"])

    result = runner.invoke(cli, ["install-extension"])
    assert result.exit_code == 0
    ext_dst = tmp_path / ".mnemostroma" / "extension"
    assert ext_dst.exists()
    assert (ext_dst / "manifest.json").exists()
