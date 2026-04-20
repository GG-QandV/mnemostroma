#!/usr/bin/env bash
# Mnemostroma — Full Audit Script
# Usage: bash scripts/audit.sh [--fast]
# Output: PASS/FAIL per check. Exit 0 = all pass, 1 = failures found.
# Designed for flash agents: only FAIL lines need human/senior-agent review.

set -uo pipefail

REPO_A="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_C="/home/gg/projects/mnemostroma-public"
VENV="$REPO_A/.venv/bin"
FAST="${1:-}"

PASS=0
FAIL=0
FAILS=()

pass() { echo "PASS $1"; ((PASS++)); }
fail() { echo "FAIL $1: $2"; ((FAIL++)); FAILS+=("$1: $2"); }
header() { echo ""; echo "── $1 ─────────────────────────────────"; }

cd "$REPO_A"

# ══════════════════════════════════════════════════════
# 1. КОД
# ══════════════════════════════════════════════════════
header "1. КОД"

if "$VENV/ruff" check src/ --quiet 2>&1 | grep -q "error\|Error"; then
    fail "ruff" "$("$VENV/ruff" check src/ --quiet 2>&1 | head -3)"
elif "$VENV/ruff" check src/ 2>&1 | grep -q "^Found"; then
    fail "ruff" "$("$VENV/ruff" check src/ 2>&1 | tail -1)"
else
    pass "ruff"
fi

if [[ "$FAST" != "--fast" ]]; then
    MYPY_OUT=$("$VENV/mypy" src/ --ignore-missing-imports --no-error-summary 2>&1 | grep "error:" | wc -l)
    if [[ "$MYPY_OUT" -gt 0 ]]; then
        fail "mypy" "$MYPY_OUT type errors"
    else
        pass "mypy"
    fi
fi

# Цикломатическая сложность > 15 (radon если установлен)
if "$VENV/python" -m radon cc src/ -n C -s 2>/dev/null | grep -q "^src"; then
    COMPLEX=$("$VENV/python" -m radon cc src/ -n C -s 2>/dev/null | head -5)
    fail "complexity" "functions with CC>10: $COMPLEX"
else
    pass "complexity"
fi

# ══════════════════════════════════════════════════════
# 2. БЕЗОПАСНОСТЬ
# ══════════════════════════════════════════════════════
header "2. БЕЗОПАСНОСТЬ"

if [[ "$FAST" != "--fast" ]]; then
    if command -v pip-audit &>/dev/null; then
        AUDIT_OUT=$(pip-audit --require-hashes 2>&1 || pip-audit 2>&1)
        if echo "$AUDIT_OUT" | grep -qi "vulnerability\|CVE"; then
            fail "pip-audit" "$(echo "$AUDIT_OUT" | grep -i "CVE\|vulnerability" | head -3)"
        else
            pass "pip-audit"
        fi
    else
        fail "pip-audit" "not installed"
    fi
fi

BANDIT_OUT=$("$VENV/python" -m bandit -r src/ -ll -q 2>&1 | grep "Issue:" | wc -l)
if [[ "$BANDIT_OUT" -gt 0 ]]; then
    fail "bandit" "$BANDIT_OUT high/medium severity issues"
else
    pass "bandit"
fi

# Захардкоженные секреты
SECRET_HITS=$(grep -rn "password\s*=\s*['\"][^'\"]\{8\}\|token\s*=\s*['\"][^'\"]\{8\}" src/ \
    --include="*.py" | grep -v "sse_token\|Bearer\|test\|#\|import secrets" | wc -l)
if [[ "$SECRET_HITS" -gt 0 ]]; then
    fail "hardcoded-secrets" "$SECRET_HITS potential hits"
else
    pass "hardcoded-secrets"
fi

# chmod sse_token
TOKEN_FILE="$HOME/.mnemostroma/sse_token"
if [[ -f "$TOKEN_FILE" ]]; then
    PERMS=$(stat -c "%a" "$TOKEN_FILE" 2>/dev/null || stat -f "%Lp" "$TOKEN_FILE" 2>/dev/null)
    if [[ "$PERMS" != "600" ]]; then
        fail "sse_token_perms" "expected 600, got $PERMS"
    else
        pass "sse_token_perms"
    fi
else
    pass "sse_token_perms" # not created yet — ok
fi

# ══════════════════════════════════════════════════════
# 3. ТЕСТЫ
# ══════════════════════════════════════════════════════
header "3. ТЕСТЫ"

# Fast mode: skip slow integration tests
if [[ "$FAST" == "--fast" ]]; then
    PYTEST_ARGS="tests/ -q --tb=no --timeout=30 --ignore=tests/test_memory_layers.py --ignore=tests/test_data_contracts.py"
else
    PYTEST_ARGS="tests/ -q --tb=no --timeout=60"
fi
TEST_OUT=$("$VENV/python" -m pytest $PYTEST_ARGS 2>&1 | tail -3)
if echo "$TEST_OUT" | grep -q "failed\|error"; then
    NFAIL=$(echo "$TEST_OUT" | grep -oP '\d+ failed' | head -1)
    fail "pytest" "$NFAIL"
else
    pass "pytest"
fi

if [[ "$FAST" != "--fast" ]]; then
    COV_OUT=$("$VENV/python" -m pytest tests/ -q --tb=no \
        --cov=src/mnemostroma --cov-report=term-missing 2>&1 | grep "^TOTAL")
    COV_PCT=$(echo "$COV_OUT" | grep -oP '\d+%' | tail -1 | tr -d '%')
    if [[ -n "$COV_PCT" && "$COV_PCT" -lt 70 ]]; then
        fail "coverage" "${COV_PCT}% < 70%"
    else
        pass "coverage (${COV_PCT}%)"
    fi
fi

# ══════════════════════════════════════════════════════
# 4. РЕПО-ИНВАРИАНТЫ
# ══════════════════════════════════════════════════════
header "4. РЕПО-ИНВАРИАНТЫ"

# Watermark anchors
for ANCHOR in "_SESS_DIAG_KEY_" "_LOGS_ID_DB_" "_CONS_BUILD_TAG_"; do
    if ! grep -rq "$ANCHOR" src/; then
        fail "watermark_$ANCHOR" "missing from src/"
    else
        pass "watermark_$ANCHOR"
    fi
done

# log_event в Repo C
if [[ -d "$REPO_C/src" ]]; then
    LOG_HITS=$(grep -rn "log_event" "$REPO_C/src/" 2>/dev/null | wc -l)
    if [[ "$LOG_HITS" -gt 0 ]]; then
        fail "repo_c_log_event" "$LOG_HITS occurrences in mnemostroma-public/src/"
    else
        pass "repo_c_log_event"
    fi
else
    fail "repo_c_log_event" "mnemostroma-public/src/ not found"
fi

# scripts/ не в Repo C
for SCRIPT in "issue_build.py" "identify_leak.py" "audit.sh"; do
    if [[ -f "$REPO_C/scripts/$SCRIPT" ]]; then
        fail "repo_c_scripts" "$SCRIPT found in public repo"
    fi
done
pass "repo_c_scripts"

# Remote Repo A
REMOTE_A=$(git -C "$REPO_A" remote get-url origin 2>/dev/null)
if [[ "$REMOTE_A" != *"mnemostroma-core"* ]]; then
    fail "remote_repo_a" "expected mnemostroma-core, got $REMOTE_A"
else
    pass "remote_repo_a"
fi

# Remote Repo C
if [[ -d "$REPO_C" ]]; then
    REMOTE_C=$(git -C "$REPO_C" remote get-url origin 2>/dev/null)
    if [[ "$REMOTE_C" != *"mnemostroma.git"* ]]; then
        fail "remote_repo_c" "expected mnemostroma.git, got $REMOTE_C"
    else
        pass "remote_repo_c"
    fi
fi

# Чувствительные файлы не в git
for SENSITIVE in "daemon.pid" "daemon.sock" "*.db" "dist/" "sse_token"; do
    if git ls-files | grep -q "$SENSITIVE" 2>/dev/null; then
        fail "git_sensitive" "$SENSITIVE tracked in git"
    fi
done
pass "git_sensitive"

# ══════════════════════════════════════════════════════
# 5. АРХИТЕКТУРНЫЕ ИНВАРИАНТЫ
# ══════════════════════════════════════════════════════
header "5. АРХИТЕКТУРА"

# conductor.py не импортирует mcp/starlette
COND_IMPORTS=$(grep -n "^import mcp\|^from mcp\|^import starlette\|^from starlette" \
    src/mnemostroma/conductor.py 2>/dev/null | wc -l)
if [[ "$COND_IMPORTS" -gt 0 ]]; then
    fail "conductor_imports" "conductor.py imports mcp/starlette"
else
    pass "conductor_imports"
fi

# ipc_server.py только stdlib
IPC_EXT=$(grep -n "^import\|^from" src/mnemostroma/ipc_server.py 2>/dev/null | \
    grep -v "^from \.\|asyncio\|json\|logging\|sys\|pathlib\|typing" | wc -l)
if [[ "$IPC_EXT" -gt 0 ]]; then
    fail "ipc_stdlib_only" "ipc_server.py has non-stdlib imports"
else
    pass "ipc_stdlib_only"
fi

# Адаптеры не импортируют conductor
for ADAPTER in "mcp_stdio_adapter.py" "mcp_sse_adapter.py"; do
    if grep -q "from mnemostroma.conductor\|import conductor" \
        "src/mnemostroma/integration/$ADAPTER" 2>/dev/null; then
        fail "adapter_no_conductor" "$ADAPTER imports conductor"
    else
        pass "adapter_no_conductor ($ADAPTER)"
    fi
done

# ══════════════════════════════════════════════════════
# 6. ЗАВИСИМОСТИ + КОНФИГ
# ══════════════════════════════════════════════════════
header "6. ЗАВИСИМОСТИ + КОНФИГ"

PIP_CHECK=$("$VENV/python" -m pip check 2>&1)
if echo "$PIP_CHECK" | grep -q "has requirement\|is not installed"; then
    fail "pip_check" "$(echo "$PIP_CHECK" | head -3)"
else
    pass "pip_check"
fi

# config_default.json валидный JSON
if ! "$VENV/python" -c \
    "import json; json.load(open('src/mnemostroma/config_default.json'))" 2>/dev/null; then
    fail "config_json" "invalid JSON"
else
    pass "config_json"
fi

# ══════════════════════════════════════════════════════
# 7. ДОКУМЕНТАЦИЯ
# ══════════════════════════════════════════════════════
header "7. ДОКУМЕНТАЦИЯ"

if "$VENV/python" scripts/audit_version_check.py; then
    pass "version_match"
else
    fail "version_match" "pyproject vs README mismatch"
fi

for DOC in "README.md" "CLAUDE_AI_SETUP.md" "CHANGELOG.md"; do
    if [[ ! -f "$REPO_C/$DOC" ]]; then
        fail "repo_c_docs" "$DOC missing from public repo"
    else
        pass "repo_c_docs ($DOC)"
    fi
done

# ══════════════════════════════════════════════════════
# ИТОГ
# ══════════════════════════════════════════════════════
echo ""
echo "══════════════════════════════════════════════════════"
echo "AUDIT RESULT: $PASS passed, $FAIL failed"
echo "══════════════════════════════════════════════════════"

# Write JSON output for senior agent review
JSON_OUT="$REPO_A/audit_results.json"
MODE_STR="${FAST:+fast}"
MODE_STR="${MODE_STR:-full}"
VERSION=$("$VENV/python" -c "import re,pathlib; m=re.search(r'version\s*=\s*[\"\']([\d.]+)', pathlib.Path('$REPO_A/pyproject.toml').read_text()); print(m.group(1) if m else 'unknown')" 2>/dev/null)

# Build JSON failures array and write file via Python
FAILS_JSON=""
for F in "${FAILS[@]+"${FAILS[@]}"}"; do
    KEY="${F%%:*}"
    DETAIL="${F#*: }"
    KEY="${KEY// /}"
    FAILS_JSON="${FAILS_JSON}{\"check\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$KEY"), \"detail\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$DETAIL")},"
done
FAILS_JSON="[${FAILS_JSON%,}]"

python3 - <<PYEOF
import json, datetime, pathlib
data = {
    "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "mode": "$MODE_STR",
    "version": "$VERSION",
    "passed": $PASS,
    "failed": $FAIL,
    "failures": $FAILS_JSON,
}
pathlib.Path("$JSON_OUT").write_text(json.dumps(data, ensure_ascii=False, indent=2))
PYEOF

echo "JSON: $JSON_OUT"

if [[ "$FAIL" -gt 0 ]]; then
    echo ""
    echo "FAILURES:"
    for F in "${FAILS[@]+"${FAILS[@]}"}"; do
        echo "  ✗ $F"
    done
    exit 1
fi

echo "ALL CHECKS PASSED"
exit 0
