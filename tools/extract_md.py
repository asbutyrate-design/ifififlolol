#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ЭТАП 1. Извлечение текста проектов из /source в Markdown.

Один блок = один проект на одном языке → один .md
    content-md/<dept-slug>/<slug>.ru.md
    content-md/<dept-slug>/<slug>.en.md

Запуск:  python3 tools/extract_md.py
Ничего не удаляет и не перезаписывает вне content-md/.
Исходники в /source только читаются.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO
OUT = REPO / "content-md"

# --------------------------------------------------------------------------
# 1. Файл → кафедра.  АКФХ_анг.txt — опечатка в имени (перестановка букв),
#    по содержанию это английская версия АФКХ.  Файл НЕ переименовываем:
#    /source — чужое сырьё.
# --------------------------------------------------------------------------
FILE2DEPT = {
    "АФКХ_рус.txt": ("afkh", "ru"), "АКФХ_анг.txt": ("afkh", "en"),
    "БТ_рус.txt":   ("bt",   "ru"), "БТ_анг.txt":   ("bt",   "en"),
    "ОЭФ_рус.txt":  ("oef",  "ru"), "ОЭФ_анг.txt":  ("oef",  "en"),
    "ФАРМАК_рус.txt": ("farmak", "ru"), "ФАРМАК_анг.txt": ("farmak", "en"),
    "ФАРМАЦ_рус.txt": ("farmac", "ru"), "ФАРМАЦ_анг.txt": ("farmac", "en"),
    "ФЕ_рус.txt":   ("fe",   "ru"), "ФЕ_анг.txt":   ("fe",   "en"),
    "ФП_рус.txt":   ("fp",   "ru"), "ФП_анг.txt":   ("fp",   "en"),
    "ФТ_рус.txt":   ("ft",   "ru"), "ФТ_анг.txt":   ("ft",   "en"),
    "ФХ_рус.txt":   ("fh",   "ru"), "ФХ_анг.txt":   ("fh",   "en"),
}

# --------------------------------------------------------------------------
# 2. Маркеры начала проекта.  В файлах встречаются ПЯТЬ разных формулировок
#    в английских файлах и одна русская — парсер обязан принимать все и не
#    зависеть от регистра и наличия двоеточия.
# --------------------------------------------------------------------------
MARKERS = [
    r"Название научного проекта\s*:",
    r"The name of the scientific project\s*:",
    r"The name of the research project\s*:",
    r"The name of the project\s*:",
    r"Name of the scientific project\s*:",
    r"Name of the research project\s*:",
    r"Name of the project\s*:",
    r"Research Project Title\s*:?",
    r"Title of the research project\s*:?",
    r"Research project title\s*:?",
    r"Project Title\s*:?",
]
MARKER_RE = re.compile("|".join(MARKERS), re.IGNORECASE)

# --------------------------------------------------------------------------
# 3. Пары ru↔en.  ПОРЯДОК ПРОЕКТОВ В ФАЙЛАХ НЕ СОВПАДАЕТ, поэтому пары
#    задаются вручную по смыслу и подтверждены заказчиком.
#    Значение — список (индекс ru, индекс en), нумерация с нуля.
# --------------------------------------------------------------------------
PAIRS = {
    "afkh": [(0, 2), (1, 1), (2, 0)],
    "bt":   [(0, 0), (1, 1), (2, 2), (3, 3)],
    "oef":  [(0, 0), (1, 4), (2, 1), (3, 2), (4, 3)],
    "farmak": [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)],
    "farmac": [(0, 0), (1, 1)],
    "fe":   [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)],
    "fp":   [(0, 0)],
    "ft":   [(0, 0), (1, 1)],
    "fh":   [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5)],
}

# --------------------------------------------------------------------------
# 4. slug.  Присваивается ОДИН РАЗ И НАВСЕГДА, общий для ru и en.
#    Порядок соответствует парам выше.
# --------------------------------------------------------------------------
SLUGS = {
    "afkh": ["spray-quality-aerosols", "solid-dispersions-bioavailability",
             "enterosorbents-adsorption"],
    "bt":   ["targeted-delivery-antitumor", "cell-free-translation",
             "bacteriophages-endolysins", "bacterial-cellulose"],
    "oef":  ["parkinson-net-info", "ai-pharmacy-business-processes",
             "antiepileptic-cost-calculator", "biologic-therapy-access",
             "pharmaceutical-care-pregnant-arvi"],
    "farmak": ["digital-platforms-drug-development", "digital-prescribing",
               "preclinical-plant-raw-materials", "drug-induced-hearing-loss",
               "neuroprotection-neuroregeneration"],
    "farmac": ["cdss-physician-pharmacist", "ai-environmental-programs"],
    "fe":   ["plants-taxonomy-medicine", "new-medicinal-plant-raw-materials",
             "ionomic-profiles-database", "glycans-plant-raw-materials",
             "light-microscopy-quality-control"],
    "fp":   ["qbd-drug-development-strategy"],
    "ft":   ["in-situ-delivery-systems", "chewing-gum-technology"],
    "fh":   ["chemical-toxicological-analysis", "metabolism-pharmacokinetics",
             "quality-control-medicinal-products", "low-molecular-bioactive-compounds",
             "immunotropic-drug-products", "bioequivalence-assessment"],
}

# --------------------------------------------------------------------------
# 5. Заголовки разделов внутри блока.
# --------------------------------------------------------------------------
SECTION_LABELS = {
    "ru": [
        "Команда проекта", "Проект выполняется совместно с",
        "Описание проекта", "Цель проекта", "Ключевые задачи",
        "Ключевые задачи проекта", "Основные научные результаты",
        "Основные научные результаты проекта",
        "Основные научные публикации по проекту",
        "Публикации по проекту", "Основные публикации",
        "Конференции и мероприятия", "Конференции",
    ],
    "en": [
        "Project team", "Project Team", "The project is carried out jointly with",
        "The project is carried out jointly with:",
        "Project description", "Project Description",
        "Project objective", "Project Objective", "Objective", "Project Aim",
        "Aim", "Goal", "Project goal", "Project Goal",
        "Key objectives", "Key Objectives", "Key tasks", "Key points",
        "Key scientific results", "Key scientific results of the project",
        "Main results of the project", "Expected Results", "Expected results",
        "Ожидаемые результаты", "Ключевые результаты проекта",
        "Main scientific publications on the project",
        "Key Scientific Publications on the Project",
        "Key publications on the project", "Key research publications on the project",
        "Main scientific publications related to the project",
        "List of publications", "Publications on the project",
        "Conferences", "Conferences and events",
    ],
}

# Заголовки «в теле строки»: заголовок идёт первым словом строки, а текст —
# сразу за ним (БТ_анг, ФТ_анг, ФАРМАЦ_анг).  Варианты отсортированы по
# убыванию длины, чтобы длинная формулировка не была срезана короткой.
INLINE_HEADERS = [
    "Main scientific publications related to the project",
    "Main scientific publications on the project",
    "The main scientific publications on the project",
    "Main Scientific Publications on the Project",
    "Key research publications on the project",
    "Key Scientific Publications on the Project",
    "Список публикаций по проекту",
    "Ключевые результаты проекта",
    "Key scientific results of the project",
    "Key publications on the project",
    "Publications on the project",
    "Key scientific results",
    "Key publications",
    "List of publications",
    "Список публикаций",
]
INLINE_HEADERS.sort(key=len, reverse=True)
INLINE_HEADER_RE = re.compile(
    r"^\s*(?P<h>" + "|".join(re.escape(h) for h in INLINE_HEADERS) + r")\s*:?\s*(?P<tail>.*)$",
    re.IGNORECASE,
)

# Мусорные строки: имена вложений и артефактов исходников, не являющиеся текстом.
JUNK_LINE_RE = re.compile(
    r"^\s*(Описание проекта_\S+\.docx|Наименование_\S+\.docx)\s*$",
    re.IGNORECASE,
)
# Служебные combining-символы (\u0335) перед заголовками.
COMBINING_RE = re.compile(r"[\u0300-\u036f\u0334-\u0338]")
# "Стр." / нумерация страниц, осколки — оставляем, они не мешают.


def norm_line(s: str) -> str:
    s = COMBINING_RE.sub("", s)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.rstrip()


def split_blocks(text: str) -> list[tuple[str, str]]:
    """Возвращает [(маркер, тело_блока), ...] — тело от конца маркера до
    начала следующего маркера."""
    hits = list(MARKER_RE.finditer(text))
    blocks = []
    for i, h in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        blocks.append((h.group(0), text[h.end():end]))
    return blocks


def take_title(body: str) -> tuple[str, str]:
    """Отделяет название проекта от остального текста блока.

    Название бывает:
      • на одной строке — «в кавычках» либо без;
      • многострочным внутри «…» (ОЭФ, ФАРМАЦ) — тогда берём всё до
        закрывающей кавычки, переносы строк сворачиваем в пробелы.
    Возвращает (название, остаток).
    """
    lines = body.splitlines()
    ti = next((i for i, l in enumerate(lines) if l.strip()), None)
    if ti is None:
        return "", ""

    raw = norm_line(lines[ti])
    after = ti + 1

    # Многострочное название: открывающая кавычка есть, закрывающей на строке нет
    m = re.match(r"^\s*[«\"“]\s*(.*)$", raw)
    if m and not re.search(r"[»\"”]\s*$", raw):
        collected = [m.group(1)]
        while after < len(lines):
            nxt = norm_line(lines[after])
            after += 1
            close = re.search(r"[»\"”]", nxt)
            if close:
                collected.append(nxt[:close.start()])
                break
            collected.append(nxt)
        title = " ".join(collected)
    else:
        title = raw

    title = title.strip().strip("«»\"“”‘’' \t")
    title = re.sub(r"\s+", " ", title).strip()
    rest = "\n".join(lines[after:])
    return title, rest


def is_section_header(line: str, lang: str) -> bool:
    """Заголовок раздела — по известному списку либо по форме:
    короткая строка, оканчивающаяся двоеточием, без нумерации и без точки."""
    bare = line.strip().rstrip(":").rstrip()
    if bare in SECTION_LABELS[lang]:
        return True
    if not line.rstrip().endswith(":"):
        return False
    s = line.strip()
    if len(s) > 60 or s.startswith(("-", "•", "\t")) or re.match(r"^\d", s):
        return False
    # в заголовке не бывает цифр и «слов-предложений» с точкой внутри
    if re.search(r"\d|\.\s", s):
        return False
    # и не бывает имени файла
    if re.search(r"\.(docx?|pdf|xlsx?|jpe?g|png)\b", s, re.IGNORECASE):
        return False
    if len(s.split()) > 8:
        return False
    return bool(re.fullmatch(r"[\w\s\-\.,()«»/]+:", s, re.UNICODE))


def to_markdown(title: str, rest: str, lang: str) -> str:
    out: list[str] = [f"# {title}", ""]
    for raw in rest.splitlines():
        line = norm_line(raw)
        if not line.strip():
            # сохраняем разрыв абзаца, но не больше одного подряд
            if out and out[-1] != "":
                out.append("")
            continue
        if JUNK_LINE_RE.match(line):
            continue  # мусорная строка-имя файла (подтверждено заказчиком)

        # «Заголовок и текст в одной строке» — только если текст непустой
        im = INLINE_HEADER_RE.match(line)
        if im and im.group("tail").strip():
            out.append("")
            out.append(f"## {im.group('h').strip()}")
            out.append("")
            line = im.group("tail").strip()

        if is_section_header(line, lang):
            head = line.strip().rstrip(":").strip()
            out.append("")
            out.append(f"## {head}")
            out.append("")
            continue

        # нормализуем маркеры списка: • и – → "-"; одиночный ведущий пробел
        # у перечислений на английском (\tKey objectives → элемент списка)
        line = re.sub(r"^[\u2022\u2013\u2014]\s*", "- ", line)
        if re.match(r"^\s+\S", line) and not line.lstrip().startswith("-"):
            line = "- " + line.strip()
        out.append(line)

    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def main() -> int:
    if not MARKER_RE.search((SOURCE / "АФКХ_рус.txt").read_text(encoding="utf-8")):
        print("ОШИБКА: маркеры не найдены — проверьте /source", file=sys.stderr)
        return 1

    # --- 1) разбор всех файлов на блоки ------------------------------------
    blocks: dict[str, dict[str, list[tuple[str, str]]]] = {}
    files_used = {}
    for name, (dept, lang) in FILE2DEPT.items():
        path = SOURCE / name
        if not path.exists():
            print(f"ПРЕДУПРЕЖДЕНИЕ: нет файла {name}", file=sys.stderr)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        bl = split_blocks(text)
        blocks.setdefault(dept, {})[lang] = bl
        files_used[(dept, lang)] = name

    # --- 2) контроль сходимости с PAIRS ------------------------------------
    problems = []
    for dept, pairs in PAIRS.items():
        nru = len(blocks.get(dept, {}).get("ru", []))
        nen = len(blocks.get(dept, {}).get("en", []))
        if len(pairs) != nru or len(pairs) != nen:
            problems.append(
                f"{dept}: пар={len(pairs)}, ru-блоков={nru}, en-блоков={nen}"
            )
        if len(SLUGS[dept]) != len(pairs):
            problems.append(f"{dept}: slug'ов={len(SLUGS[dept])}, пар={len(pairs)}")
    if problems:
        print("ОШИБКА СОГЛАСОВАННОСТИ:", file=sys.stderr)
        for p in problems:
            print("  -", p, file=sys.stderr)
        return 1

    # --- 3) запись markdown ------------------------------------------------
    written = 0
    index = []
    for dept, pairs in PAIRS.items():
        d = OUT / dept
        d.mkdir(parents=True, exist_ok=True)
        for k, (i_ru, i_en) in enumerate(pairs):
            slug = SLUGS[dept][k]
            for lang, idx in (("ru", i_ru), ("en", i_en)):
                marker, body = blocks[dept][lang][idx]
                title, rest = take_title(body)
                md = to_markdown(title, rest, lang)
                path = d / f"{slug}.{lang}.md"
                path.write_text(md, encoding="utf-8")
                written += 1
                index.append({
                    "dept": dept, "slug": slug, "lang": lang,
                    "file": str(path.relative_to(REPO)),
                    "title": title,
                    "chars": len(md),
                    "source_file": files_used[(dept, lang)],
                    "source_block": idx + 1,
                })

    (REPO / "data").mkdir(exist_ok=True)
    (REPO / "data" / "content-index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"Записано .md файлов: {written}")
    for lang in ("ru", "en"):
        n = sum(1 for r in index if r["lang"] == lang)
        print(f"  {lang}: {n}")
    print(f"Проектов (пар): {sum(len(p) for p in PAIRS.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
