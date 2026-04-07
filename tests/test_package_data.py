# SPDX-License-Identifier: FSL-1.1-MIT
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
