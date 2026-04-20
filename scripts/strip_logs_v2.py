#!/usr/bin/env python3
# SPDX-License-Identifier: FSL-1.1-MIT
"""strip_logs_v2.py — удаляет вызовы log_event и импорты log_writer,
затем копирует файлы из Repo A в Repo C для публичного синка.

Обрабатывает однострочные и многострочные вызовы:
    await log_event(ctx, "x", "y", {"k": v})
    await log_event(
        ctx, "x", "y", {
            "k": v,
        }
    )

Использование:
    # Проверить без записи:
    python scripts/strip_logs_v2.py --dry-run src/mnemostroma/tools/read.py

    # Стрипнуть и скопировать один файл:
    python scripts/strip_logs_v2.py src/mnemostroma/tools/read.py /path/to/repo-c/src/mnemostroma/tools/read.py

    # Стрипнуть и скопировать директорию:
    python scripts/strip_logs_v2.py --dir src/mnemostroma/ /path/to/repo-c/src/mnemostroma/
"""
import sys
import re
import shutil
from pathlib import Path


def strip_log_events(source: str) -> tuple[str, int]:
    """Удаляет await log_event(...) вызовы и импорты log_writer.

    Использует счётчик скобок для корректной обработки многострочных вызовов.

    Returns:
        (result_source, removed_count)
    """
    lines = source.splitlines(keepends=True)
    result = []
    removed = 0
    i = 0

    LOG_EVENT_RE = re.compile(r'^\s*await\s+(?:_?)log_event\s*\(')
    IMPORT_LOG_EVENT_RE = re.compile(
        r'^\s*(from\s+\S+\s+import\s+.*\blog_event\b|import\s+.*\blog_event\b)'
    )
    IMPORT_LOG_WRITER_RE = re.compile(r'^\s*from\s+\S*log_writer\S*\s+import\b')

    while i < len(lines):
        line = lines[i]

        # Убираем импорты log_event
        if IMPORT_LOG_EVENT_RE.match(line):
            removed += 1
            i += 1
            continue

        # Убираем импорты log_writer (вся строка)
        if IMPORT_LOG_WRITER_RE.match(line):
            removed += 1
            i += 1
            continue

        # Начало вызова log_event — считаем скобки до закрывающей )
        if LOG_EVENT_RE.match(line):
            depth = line.count('(') - line.count(')')
            removed += 1
            i += 1
            while depth > 0 and i < len(lines):
                depth += lines[i].count('(') - lines[i].count(')')
                removed += 1
                i += 1
            continue

        result.append(line)
        i += 1

    return ''.join(result), removed


def process_file(src: Path, dst: Path | None, dry_run: bool = False) -> int:
    """Стрипнуть src и записать в dst (или in-place если dst is None)."""
    source = src.read_text(encoding='utf-8')
    stripped, count = strip_log_events(source)

    if dry_run:
        if count:
            print(f"[dry-run] {src}: {count} вызов(ов) будет удалено")
        return count

    target = dst if dst is not None else src
    if dst is not None:
        target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(stripped, encoding='utf-8')

    if count:
        print(f"  stripped {count:>2} вызов(ов)  {src}{f' -> {dst}' if dst else ''}")
    else:
        if dst:
            shutil.copy2(src, dst)
            print(f"  copied             {src} -> {dst}")
    return count


def main():
    args = sys.argv[1:]
    dry_run = '--dry-run' in args
    args = [a for a in args if a != '--dry-run']

    if not args:
        print(__doc__)
        sys.exit(1)

    total = 0

    if '--dir' in args:
        idx = args.index('--dir')
        src_dir = Path(args[idx + 1])
        dst_dir = Path(args[idx + 2])
        for src_file in sorted(src_dir.rglob('*.py')):
            rel = src_file.relative_to(src_dir)
            total += process_file(src_file, dst_dir / rel, dry_run)

    elif len(args) == 1:
        # Только dry-run / in-place strip
        p = Path(args[0])
        if p.is_dir():
            for f in sorted(p.rglob('*.py')):
                total += process_file(f, None, dry_run)
        else:
            total += process_file(p, None, dry_run)

    elif len(args) == 2:
        total += process_file(Path(args[0]), Path(args[1]), dry_run)

    else:
        print(__doc__)
        sys.exit(1)

    print(f"\nИтого удалено: {total} вызов(ов)"
          f"{' (dry-run, файлы не изменены)' if dry_run else ''}")


if __name__ == '__main__':
    main()
