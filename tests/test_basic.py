# SPDX-License-Identifier: FSL-1.1-MIT
import unittest
import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from mnemostroma.observer.filter import deterministic_filter
from mnemostroma.storage.content import compress_content, decompress_content, get_content_hash

class TestMnemostromaBasic(unittest.TestCase):
    def test_filter(self):
        res = deterministic_filter("Это критическое решение.")
        self.assertEqual(res["importance"], "critical")
        
        res = deterministic_filter("https://google.com")
        self.assertEqual(res["precision_items"][0]["type"], "link")

    def test_content(self):
        text = "Hello World"
        compressed = compress_content(text)
        self.assertTrue(len(compressed) > 0)
        self.assertEqual(decompress_content(compressed), text)
        
        h = get_content_hash("test")
        self.assertEqual(len(h), 64)

if __name__ == "__main__":
    unittest.main()
