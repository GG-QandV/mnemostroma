# SPDX-License-Identifier: FSL-1.1-MIT
import pytest
from mnemostroma.storage.content import compress_content, decompress_content, get_content_hash, generate_diff

def test_content_compression():
    text = "Hello, Mnemostroma! " * 100
    compressed = compress_content(text)
    assert len(compressed) < len(text)
    decompressed = decompress_content(compressed)
    assert decompressed == text

def test_content_hash():
    text = "Important code"
    h1 = get_content_hash(text)
    h2 = get_content_hash(text)
    assert h1 == h2
    assert h1 != get_content_hash(text + " ")

def test_diff_generation():
    old = "Line 1\nLine 2\nLine 3"
    new = "Line 1\nLine 2 changed\nLine 3"
    diff = generate_diff(old, new)
    assert "-Line 2" in diff
    assert "+Line 2 changed" in diff
