import pytest
from pathlib import Path
import json
import mnemostroma

def test_package_data_presence():
    """Verify that vital package data files are present in the installed package."""
    pkg_dir = Path(mnemostroma.__file__).parent
    
    config_default = pkg_dir / "config_default.json"
    manifest = pkg_dir / "models_manifest.json"
    
    assert config_default.exists(), "config_default.json missing from package"
    assert manifest.exists(), "models_manifest.json missing from package"
    
    # Verify they are valid JSON
    with open(config_default, "r", encoding="utf-8") as f:
        json.load(f)
    with open(manifest, "r", encoding="utf-8") as f:
        json.load(f)

# T-08: extension/dist входит в установленный пакет (или fallback на extension/ в dev-режиме)
def test_extension_dist_in_package():
    pkg_path = Path(mnemostroma.__file__).parent
    ext_path = pkg_path / "extension" / "dist" / "manifest.json"
    if not ext_path.exists():
        ext_path = pkg_path / "extension" / "manifest.json"
    assert ext_path.exists(), \
        f"extension manifest.json missing from package at {pkg_path}"

# T-09: manifest.json внутри пакета валидный JSON с manifest_version=3
def test_extension_manifest_valid():
    import json
    pkg_path = Path(mnemostroma.__file__).parent
    ext_path = pkg_path / "extension" / "dist" / "manifest.json"
    if not ext_path.exists():
        ext_path = pkg_path / "extension" / "manifest.json"
    manifest = json.loads(ext_path.read_text(encoding="utf-8"))
    assert manifest.get("manifest_version") == 3
    assert "name" in manifest
    assert "permissions" in manifest
