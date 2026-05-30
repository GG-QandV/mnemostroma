import pytest
from pathlib import Path

# T-12: install-extension не использует shutil.rmtree перед копированием
def test_install_extension_no_rmtree():
    import inspect
    import mnemostroma.cli.commands as m
    src = inspect.getsource(m._cmd_install_extension)
    assert "rmtree" not in src, "install-extension must not delete existing extension"

# T-13: EXT_SRC путь резолвится относительно __file__ пакета, не CWD
def test_ext_src_relative_to_package():
    import mnemostroma.cli.commands as m
    assert m.EXT_SRC.is_absolute()
    assert "mnemostroma" in str(m.EXT_SRC).lower()
