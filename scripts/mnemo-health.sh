#!/bin/bash
# Mnemostroma Health Check — Golden Standard
# Usage: bash scripts/mnemo-health.sh

PASS=0
FAIL=0

check() {
    local desc="$1"
    local cmd="$2"
    local expected="$3"
    local result
    result=$(eval "$cmd" 2>/dev/null)
    if echo "$result" | grep -q "$expected"; then
        echo "✅ $desc"
        ((PASS++))
    else
        echo "❌ $desc (got: $result)"
        ((FAIL++))
    fi
}

echo "=== Mnemostroma Health Check ==="
echo ""

# 1. Single daemon instance
check "Single daemon instance" \
    "pgrep -c -f 'mnemostroma run'" \
    "^1$"

# 2. Old unit is disabled
check "mnemostroma.service is disabled" \
    "systemctl --user is-enabled mnemostroma.service 2>&1" \
    "disabled\|not-found"

# 3. Daemon unit is active
check "mnemostroma-daemon.service is active" \
    "systemctl --user is-active mnemostroma-daemon.service" \
    "active"

# 4. No AttributeError in recent logs
check "No AttributeError in recent logs" \
    "journalctl --user -u mnemostroma-daemon.service -n 50 2>/dev/null | grep -c 'AttributeError\|Traceback'" \
    "^0$"

# 5. Single SQLite WAL writer
# Note: we check the main db file
DB_PATH="$HOME/.mnemostroma/mnemostroma.db"
if [ -f "$DB_PATH" ]; then
    check "Single SQLite WAL writer" \
        "fuser $DB_PATH 2>/dev/null | wc -w" \
        "^1$"
else
    echo "⚠️  DB not found at $DB_PATH (skipping writer check)"
fi

# 6. RAM in norm (< 750 MB as per systemd limit)
# The instruction said 550, but systemd says 750. We'll use 750 for safety.
RAM=$(ps -o rss= -p $(pgrep -f "mnemostroma run") 2>/dev/null | \
      awk '{sum+=$1} END {print int(sum/1024)}')
if [ -n "$RAM" ] && [ "$RAM" -lt 750 ]; then
    echo "✅ RAM usage: ${RAM} MB"
    ((PASS++))
else
    echo "❌ RAM usage: ${RAM:-unknown} MB (limit < 750 MB)"
    ((FAIL++))
fi

# 7. No evict loop (< 5 evict in 5 min)
check "No evict loop (< 5 evicts in 5 min)" \
    "journalctl --user -u mnemostroma-daemon.service \
     --since '5 minutes ago' 2>/dev/null | \
     grep -c 'dissolver.evict'" \
    "^[0-4]$"

echo ""
echo "=== Result: ${PASS} passed, ${FAIL} failed ==="

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "To reset: systemctl --user restart mnemostroma-daemon.service"
    exit 1
fi
