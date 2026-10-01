#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка ЭТАПА 1: ни одна содержательная строка из /source не потерялась
при извлечении в content-md/.

Логика. Каждая содержательная строка блока источника должна найтись в
соответствующем .md. Сравнение нечувствительно к оформлению (заголовки ##,
кавычки, маркеры списка, регистр, двоеточие в конце).

Отдельно обрабатывается НАМЕРЕННОЕ разделение строки на заголовок и текст:
    «    Команда проекта: доцент, к.ф.н. Янкова В.Г., …»
        →  «## Команда проекта»  +  «доцент, к.ф.н. Янкова В.Г., …»
    «Проект выполняется совместно с Институт теплофизики …»
        →  «## Проект выполняется совместно с»  +  «Институт теплофизики …»
В этом случае проверяем, что на месте И метка (как заголовок), И остаток.

Исключения (сознательные, подтверждены заказчиком):
  • строки-имена вложений вида «Описание проекта_QbD.docx» — мусор.

Запуск:  python3 tools/verify_md.py
Код выхода: 0 — всё сошлось, 1 — есть потери.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_extractor():
    spec = importlib.util.spec_from_file_location(
        "extract_md", REPO / "tools" / "extract_md.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def key(s: str, norm_line) -> str:
    """Нормализация для сравнения: без разметки, кавычек, маркеров, регистра."""
    s = norm_line(s)
    s = re.sub(r"^#+\s*", "", s)
    s = re.sub(r"^[\s\-\u2022\u2013\u2014]+", "", s)
    s = s.strip().strip("«»\"“”‘’'").rstrip(":").strip()
    return re.sub(r"\s+", " ", s).lower()


JUNK = re.compile(
    r"^(описание проекта_\S+\.docx|наименование_\S+\.docx)$", re.IGNORECASE
)


def main() -> int:
    ex = load_extractor()

    # Метки, которые могли быть вынесены в заголовок (в порядке приоритета).
    joint = list(ex.JOINT_LABELS)          # без двоеточия
    team = list(ex.TEAM_LABELS)            # с двоеточием ИЛИ пробелом
    general = list({*ex.SECTION_LABELS["ru"], *ex.SECTION_LABELS["en"]})

    problems: list[str] = []
    checked = 0

    for name, (dept, lang) in ex.FILE2DEPT.items():
        if lang != ("ru" if name.endswith("рус.txt") else "en"):
            continue
        src_path = REPO / name
        if not src_path.exists():
            problems.append(f"нет исходного файла {name}")
            continue

        text = src_path.read_text(encoding="utf-8", errors="replace")
        blocks = ex.split_blocks(text)

        for k, (i_ru, i_en) in enumerate(ex.PAIRS[dept]):
            idx = i_ru if lang == "ru" else i_en
            slug = ex.SLUGS[dept][k]
            md_path = REPO / "content-md" / dept / f"{slug}.{lang}.md"
            if not md_path.exists():
                problems.append(f"нет файла {md_path.relative_to(REPO)}")
                continue

            md_lines = [
                key(l, ex.norm_line)
                for l in md_path.read_text(encoding="utf-8").splitlines()
                if l.strip()
            ]
            md_blob = "\n".join(md_lines)

            _, body = blocks[idx]
            for raw in body.splitlines():
                s = ex.norm_line(raw).strip()
                if len(s) <= 10 or JUNK.match(s):
                    continue
                checked += 1

                # 1) метка «совместно с» — без двоеточия
                handled = False
                for lb in joint:
                    if s.lower().startswith(lb.lower()):
                        tail = ex.norm_line(s[len(lb):]).lstrip(":").strip()
                        if tail:
                            if key(lb, ex.norm_line) not in md_lines:
                                problems.append(
                                    f"{dept}/{slug}.{lang}: потерян заголовок «{lb}»"
                                )
                            if key(tail, ex.norm_line) not in md_blob:
                                problems.append(
                                    f"{dept}/{slug}.{lang}: потерян текст после «{lb}» → {tail[:90]}"
                                )
                        handled = True
                        break
                if handled:
                    continue

                # 2) метка команды с двоеточием ИЛИ пробелом
                for lb in team:
                    m = re.match(
                        r"^\s*" + re.escape(lb) + r"(?:\s*:\s*|\s+)(?P<tail>\S.*)$",
                        s, re.IGNORECASE,
                    )
                    if m:
                        if key(lb, ex.norm_line) not in md_lines:
                            problems.append(
                                f"{dept}/{slug}.{lang}: потерян заголовок «{lb}»"
                            )
                        tail = m.group("tail").strip()
                        if key(tail, ex.norm_line) not in md_blob:
                            problems.append(
                                f"{dept}/{slug}.{lang}: потерян состав команды → {tail[:90]}"
                            )
                        handled = True
                        break
                if handled:
                    continue

                # 3) обычная метка раздела с двоеточием и текстом в той же строке
                for lb in general:
                    m = re.match(
                        r"^\s*" + re.escape(lb) + r"\s*:\s*(?P<tail>\S.*)$",
                        s, re.IGNORECASE,
                    )
                    if m:
                        if key(lb, ex.norm_line) not in md_lines:
                            problems.append(
                                f"{dept}/{slug}.{lang}: потерян заголовок «{lb}»"
                            )
                        tail = m.group("tail").strip()
                        if key(tail, ex.norm_line) not in md_blob:
                            problems.append(
                                f"{dept}/{slug}.{lang}: потерян текст после «{lb}» → {tail[:90]}"
                            )
                        handled = True
                        break
                if handled:
                    continue

                # 4) обычная строка — ищем как есть
                if key(s, ex.norm_line) not in md_blob:
                    problems.append(f"{dept}/{slug}.{lang}: потеряна строка → {s[:110]}")

    print(f"Проверено содержательных строк: {checked}")
    if problems:
        print(f"ПРОБЛЕМ: {len(problems)}", file=sys.stderr)
        for p in problems[:40]:
            print("  -", p, file=sys.stderr)
        if len(problems) > 40:
            print(f"  ... и ещё {len(problems) - 40}", file=sys.stderr)
        return 1
    print("OK: расхождений нет, весь текст источника сохранён")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
