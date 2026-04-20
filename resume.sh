#!/bin/bash
# Mnemostroma — resume after Claude Code rate limit
# Usage: bash ~/projects/Project_mnemostroma/resume.sh [minutes]
# Default wait: 30 minutes

WAIT=${1:-30}
SECONDS=$((WAIT * 60))

echo "⏳ Waiting ${WAIT} min before resuming Mnemostroma session..."
echo "   Started: $(date '+%H:%M:%S')"
echo "   Resume:  $(date -d "+${WAIT} minutes" '+%H:%M:%S')"
echo "   Press Ctrl+C to cancel"
echo ""

sleep $SECONDS

echo "🚀 Starting Claude Code agent..."

claude --dangerously-skip-permissions "
Восстанови контекст сессии:
1. Выполни cm_search 'mnemostroma прогресс' — получи актуальный статус
2. Выполни: git -C ~/projects/Project_mnemostroma log --oneline -5
3. Прочитай ~/projects/Project_mnemostroma/MNEMOSTROMA_TODO_v3.md
4. Продолжи следующий незакрытый пункт роадмапа автономно.
   Рабочая директория: ~/projects/Project_mnemostroma
   После завершения — сохрани прогресс в CM.
"
