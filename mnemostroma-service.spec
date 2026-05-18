# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for mnemostroma-service.exe
# Onefile build: SCM wrapper + watchdog + daemon + adapters + models (int8)
# Build on Windows: pyinstaller mnemostroma-service.spec
# Target size: ~410 MB

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

REPO_ROOT = Path(SPECPATH)
SRC       = REPO_ROOT / "src"
MODELS    = REPO_ROOT / "models"

block_cipher = None

# ---------------------------------------------------------------------------
# onnxruntime DLLs — must be collected as binaries, not bundled in the archive
# ---------------------------------------------------------------------------
ort_binaries = collect_dynamic_libs("onnxruntime")

# ---------------------------------------------------------------------------
# Model data — int8 variants only; exclude full/O4/qint8/tinybert
# ---------------------------------------------------------------------------
model_datas = [
    # e5-small int8
    (str(MODELS / "multilingual-e5-small" / "onnx" / "model_int8.onnx"),
     "models/multilingual-e5-small/onnx"),
    (str(MODELS / "multilingual-e5-small" / "onnx" / "tokenizer.json"),
     "models/multilingual-e5-small/onnx"),
    (str(MODELS / "multilingual-e5-small" / "onnx" / "tokenizer_config.json"),
     "models/multilingual-e5-small/onnx"),
    (str(MODELS / "multilingual-e5-small" / "onnx" / "sentencepiece.bpe.model"),
     "models/multilingual-e5-small/onnx"),
    (str(MODELS / "multilingual-e5-small" / "onnx" / "special_tokens_map.json"),
     "models/multilingual-e5-small/onnx"),
    (str(MODELS / "multilingual-e5-small" / "onnx" / "config.json"),
     "models/multilingual-e5-small/onnx"),
    (str(MODELS / "multilingual-e5-small" / "1_Pooling" / "config.json"),
     "models/multilingual-e5-small/1_Pooling"),
    # distilbert-ner int8
    (str(MODELS / "distilbert-ner" / "onnx" / "model_int8.onnx"),
     "models/distilbert-ner/onnx"),
    (str(MODELS / "distilbert-ner" / "tokenizer.json"),
     "models/distilbert-ner"),
    (str(MODELS / "distilbert-ner" / "config.json"),
     "models/distilbert-ner"),
]

a = Analysis(
    [str(SRC / "mnemostroma" / "windows_service.py")],
    pathex=[str(SRC)],
    binaries=ort_binaries,
    datas=model_datas,
    hiddenimports=[
        # onnxruntime internals — not auto-discovered by PyInstaller
        "onnxruntime",
        "onnxruntime.capi",
        "onnxruntime.capi._pybind_state",
        # tokenizers (Rust extension — needs explicit listing)
        "tokenizers",
        "tokenizers.implementations",
        "tokenizers.models",
        "tokenizers.normalizers",
        "tokenizers.pre_tokenizers",
        "tokenizers.processors",
        "tokenizers.decoders",
        # numpy
        "numpy",
        "numpy.core",
        "numpy.core._multiarray_umath",
        # MCP protocol
        "mcp",
        "mcp.server",
        "mcp.server.stdio",
        "mcp.server.sse",
        "mcp.server.streamable_http_manager",
        "mcp.types",
        # starlette / uvicorn
        "starlette",
        "starlette.applications",
        "starlette.middleware",
        "starlette.middleware.cors",
        "starlette.middleware.base",
        "starlette.routing",
        "starlette.responses",
        "starlette.requests",
        "starlette.staticfiles",
        "uvicorn",
        "uvicorn.config",
        "uvicorn.main",
        "uvicorn.loops",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # http / async
        "httpx",
        "httpx._transports",
        "aiosqlite",
        "lz4",
        "lz4.frame",
        "psutil",
        # pywin32 — Windows service control
        "win32service",
        "win32serviceutil",
        "win32event",
        "win32api",
        "win32con",
        "win32security",
        "servicemanager",
        "pywintypes",
        "win32com",
        "win32com.shell",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # UI — service runs headless
        "PyQt6",
        "PyQt5",
        "PySide6",
        "tkinter",
        "_tkinter",
        # Linux-only
        "curses",
        "_curses",
        # heavy unused packages
        "matplotlib",
        "PIL",
        "Pillow",
        "IPython",
        "jupyter",
        "notebook",
        "pandas",
        "scipy",
        "sklearn",
        "torch",
        "tensorflow",
        "transformers",
        # dev / test
        "pytest",
        "setuptools",
        "pip",
        # tray (separate tool, not part of service)
        "pystray",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="mnemostroma-service",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX compression — skip onnxruntime/VC runtime DLLs (compressing them breaks them)
    upx=True,
    upx_exclude=[
        "onnxruntime*.dll",
        "onnxruntime_providers*.dll",
        "vcruntime*.dll",
        "msvcp*.dll",
        "concrt*.dll",
        "win32*.pyd",
        "pywintypes*.dll",
    ],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
