import subprocess
import sys
import re
import argparse


def get_git_merge_commits(since_ref: str = None, max_count: int = 500):
    """
    Получает последние merge-коммиты из git.
    """
    cmd = ['git', 'log', '--merges', '--oneline', f'--max-count={max_count}']
    if since_ref:
        cmd.append(f'{since_ref}..HEAD')
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.splitlines()
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при выполнении git log: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("❌ Команда 'git' не найдена. Убедитесь, что вы в git-репозитории и git установлен.", file=sys.stderr)
        sys.exit(1)


def extract_lines(lines, prefix: str = None):
    """
    Фильтрует строки с $prefix в названии ветки.
    """
    if prefix:
        pattern = re.compile(rf"Merge branch '([^']*/{prefix}-[^']*)'", re.IGNORECASE)
    else:
        pattern = re.compile(rf"Merge branch ", re.IGNORECASE)

    extracted = []
    for line in lines:
        if pattern.search(line):
            extracted.append(line)
    return extracted


def main():
    parser = argparse.ArgumentParser(
        description="Извлекает merge-коммиты, связанные с задачами."
    )
    parser.add_argument(
        "--since",
        help="Начинать с указанного тега или коммита (например, 1.2.3 или develop)"
    )
    parser.add_argument(
        "--max",
        type=int,
        default=500,
        help="Максимальное количество merge-коммитов для анализа (по умолчанию: 500)"
    )
    parser.add_argument(
        "--prefix",
        default='WEBDEV',
        help="Префикс задач"
    )
    parser.add_argument(
        "--from-file",
        help="Читать git log из файла (вместо запуска git)"
    )
    parser.add_argument(
        "--output",
        help="Сохранить результат в файл (иначе - stdout)"
    )

    args = parser.parse_args()

    output = args.output or 'merges.txt'

    if args.from_file:
        with open(args.from_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    else:
        print(f"🔍 Извлекаю merge-коммиты из git...", file=sys.stderr)
        lines = get_git_merge_commits(since_ref=args.since, max_count=args.max)

    lines = extract_lines(lines, args.prefix)

    output_text = "\n".join(lines)

    if output:
        with open(output, 'w', encoding='utf-8') as f:
            f.write(output_text)
        print(f"✅ Найдено {len(lines)} merge-коммитов. Сохранено в {output}", file=sys.stderr)
    else:
        print(f"\nℹ️  Найдено {len(lines)} merge-коммитов.", file=sys.stderr)


if __name__ == "__main__":
    main()

# python extract_webdev_merges.py --since 1.2.5
# python extract_webdev_merges.py --since 1.2.5 --output merges.txt
# python extract_webdev_merges.py --since 1.2.5 --output merges.txt --prefix ''
