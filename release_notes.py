import argparse
import re
from collections import defaultdict
from datetime import datetime
from enum import Enum
from typing import List, Optional, Union, Tuple, Dict

from dotenv import load_dotenv
import os
from jira import JIRA, Issue

load_dotenv()

JIRA_URL = os.getenv("JIRA_URL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")


def get_config() -> Tuple[str, str, datetime, str]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-version", default=os.getenv("RELEASE_VERSION"))
    parser.add_argument("--develop-version", default=os.getenv("DEVELOP_VERSION"))
    parser.add_argument("--release-date", default=os.getenv("RELEASE_DATE"))
    parser.add_argument("--prefix", default=os.getenv("PREFIX"))
    args = parser.parse_args()

    release = args.release_version
    develop = args.develop_version
    date = args.release_date or datetime.now().strftime("%d.%m.%Y")
    prefix = args.prefix

    if not release:
        release = input("Release Version: ")
    if not develop:
        develop = input("Develop Version: ")

    return release, develop, date, prefix


# === НАСТРОЙКИ РЕЛИЗА ===
RELEASE_VERSION, DEVELOP_VERSION, RELEASE_DATE, ISSUE_PREFIX = get_config()

if not all([JIRA_URL, JIRA_API_TOKEN]):
    raise EnvironmentError(
        "❌ Отсутствуют обязательные переменные в .env:\n"
        "Убедитесь, что заданы: JIRA_URL, JIRA_API_TOKEN"
    )

# === ВХОДНЫЕ ДАННЫЕ: СПИСОК MERGE-СТРОК ===
with open('merges.txt', 'r', encoding='utf-8') as f:
    merge_lines = f.read().splitlines()


def list_to_str(ids: Union[List, Tuple], quot: Optional[str] = None) -> str:
    quoted = [f"{quot}{x}{quot}" for x in ids] if quot is not None else map(str, ids)
    return ','.join(quoted)


class BranchType(tuple, Enum):
    FEATURE = ('feature',)
    MOD = ('mod', 'modification', 'refactor')
    BUGFIX = ('bugfix', 'bugfixes', 'bug', 'fix', 'hotfix')
    OTHER = ()

    @classmethod
    def all(cls) -> List[str]:
        return list(map(lambda x: x.name, cls))

    @classmethod
    def classify_branch_type(cls, pref: str) -> 'BranchType':
        pref = pref.lower()

        if pref in cls.FEATURE:
            return cls.FEATURE
        elif pref in cls.MOD:
            return cls.MOD
        elif pref in cls.BUGFIX:
            return cls.BUGFIX

        else:
            return cls.OTHER


feature_types = list_to_str(BranchType.FEATURE, quot='`')
mod_types = list_to_str(BranchType.MOD, quot='`')
bugfix_types = list_to_str(BranchType.BUGFIX, quot='`')
other_types = list_to_str(BranchType.OTHER, quot='`')

# === ПАРСИНГ ЗАДАЧ ===
tasks = {}  # base_key -> branch_type
base_key_pattern = re.compile(fr'^({ISSUE_PREFIX}-\d+)')

for line in merge_lines:
    line = line.strip()
    if not line or "refs/heads/develop" in line or "remote-tracking" in line:
        continue

    m = re.search(r"Merge branch '([^']+)'", line)
    if not m:
        continue

    full_branch = m.group(1)
    if '/' not in full_branch:
        continue

    try:
        prefix, task_key = full_branch.split('/', 1)
    except ValueError:
        continue

    if not task_key.startswith(f'{ISSUE_PREFIX}-'):
        continue

    # Пропускаем явные опечатки (например, WEBDEB)
    if ISSUE_PREFIX in task_key.lower():
        continue

    # Извлекаем базовый номер: WEBDEV-**** из WEBDEV-****-v2 и т.п.
    base_match = base_key_pattern.match(task_key)
    if not base_match:
        continue
    base_key = base_match.group(1)

    branch_type = BranchType.classify_branch_type(prefix)
    if base_key not in tasks:
        tasks[base_key] = branch_type

# === ЗАПРОС К JIRA ===
base_keys = list(tasks.keys())

if not base_keys:
    print(f"Нет корректных задач {ISSUE_PREFIX} для обработки.")
    exit()

print(f"Запрашиваю {len(base_keys)} задач из Jira...")

jira_api = JIRA(
    JIRA_URL,
    token_auth=JIRA_API_TOKEN,
)

issue_data: Dict[str, Optional[Issue]] = {}

# Формируем JQL: issueKey in (WEBDEV-1, WEBDEV-2, ...)
jql = f"issueKey IN ({','.join(base_keys)})"

try:
    # Получаем все задачи за один запрос
    issues = jira_api.search_issues(
        jql,
        fields="summary,status",  # запрашиваем только нужные поля
        maxResults=len(base_keys)
    )
except Exception as e:
    print(f"❌ Ошибка при запросе к Jira: {e}")
    exit(1)

issue_data: Dict[str, Optional[Issue]] = {issue.key: issue for issue in issues}

# Для отсутствующих задач - заглушка
for key in base_keys:
    if key not in issue_data:
        issue_data[key] = None


# === ГРУППИРОВКА ===
def make_group(jira_tasks: Dict[str, BranchType]) -> Dict[str, List]:
    jira_groups = defaultdict(list)
    for k, b_type in jira_tasks.items():
        if b_type == BranchType.FEATURE:
            jira_groups[f'Функциональность ({feature_types})'].append(k)
        elif b_type == BranchType.MOD:
            jira_groups[f'Доработки / Модификации ({mod_types})'].append(k)
        elif b_type == BranchType.BUGFIX:
            jira_groups[f'Багфиксы ({bugfix_types})'].append(k)
        else:
            jira_groups[f'Прочее ({other_types}'].append(k)

    return jira_groups


groups = make_group(tasks)

# === ФОРМИРОВАНИЕ ВЫВОДА ===
output_lines = []
output_lines.append("### Release Notes")
output_lines.append("")
output_lines.append(f"Release Version: {RELEASE_VERSION}")
output_lines.append(f"Develop Version: {DEVELOP_VERSION}")
output_lines.append(f"Дата релиза: {RELEASE_DATE}")
output_lines.append("")
output_lines.append("### Основные изменения:")
output_lines.append("")

# Сортируем задачи по номеру внутри каждой группы
for group_name in groups.keys():
    keys = groups[group_name]
    if not keys:
        continue
    output_lines.append(f"- **{group_name}:**")
    # Сортировка по числовому ID: WEBDEV-100 → 100
    sorted_keys = sorted(keys, key=lambda x: int(x.split('-')[1]))
    for key in sorted_keys:
        issue = issue_data[key]

        if issue:
            title = issue_data[key].fields.summary.strip()
            status = issue_data[key].fields.status.__str__()
        else:
            title = '[Название не найдено]'
            status = '[Todo]'

        output_lines.append(f"  + {title} (задача {key})[{status}]")
    output_lines.append("")

output_lines.append("#release #backend #patch")

# === ВЫВОД ===
final_output = "\n".join(output_lines)

with open("release_notes.md", "w") as f:
    f.write(final_output)

print(final_output)
