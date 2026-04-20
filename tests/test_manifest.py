# SPDX-License-Identifier: FSL-1.1-MIT
import unittest
import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from mnemostroma.conductor import Conductor
from mnemostroma.config import Config

class TestMnemostromaManifest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conductor = Conductor()
        self.project_root = Path(__file__).parent.parent
        self.config_path = self.project_root / "config.json"
        self.manifest_path = self.project_root / "models_manifest.json"

    async def test_bootstrap_integrity(self):
        """Verify that system starts with real manifest and correct paths."""
        # Test 1: Config & Manifest loading
        config = Config.load(self.config_path)
        self.assertIsNotNone(config.manifest)
        
        embedder_def = config.manifest.active_models.get("session_embedder")
        self.assertIsNotNone(embedder_def)
        
        # Test 2: Check query_prefix existence (Fix verification)
        self.assertIsNotNone(embedder_def.query_prefix)
        self.assertTrue(len(embedder_def.query_prefix) > 0, "query_prefix must not be empty")
        
        # Test 3: Check tokenizer path correction
        self.assertTrue(embedder_def.tokenizer_path.endswith("tokenizer.json"))

    async def test_conductor_start_no_crash(self):
        """Verify that Conductor starts without 'Is a directory' error."""
        # We use a temporary DB for testing bootstrap
        ctx = await self.conductor.start(
            config_path=self.config_path,
            db_path=":memory:", # Use in-memory DB for test
            model_dir=self.project_root / "models"
        )
        
        self.assertIsNotNone(ctx.models.embedder)
        # If we reached here, the tokenizer loading succeeded!
        
        # Verify prefix is accessible via the chain you requested
        prefix = ctx.config.manifest.active_models["session_embedder"].query_prefix
        self.assertTrue(len(prefix) > 0)
        
        await self.conductor.stop()

if __name__ == "__main__":
    unittest.main()
