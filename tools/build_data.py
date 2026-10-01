#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ЭТАП 2. Сборка /data/projects.json из content-md/ и /data/departments.json.

Принципы:
  • Научный текст не переписывается — description_* берётся из .md как есть.
  • Ничего не выдумывается: чего нет в источнике, то null или пустой массив.
  • Где разбор ненадёжен — ставится review_flag, а дословный текст сохраняется
    в team_raw_* / publication.raw. Потерять ФИО нельзя.
  • Числа (страницы, QR) считаются, а не проставляются руками.

Запуск:  python3 tools/build_data.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
MD = REPO / "content-md"

# ---------------------------------------------------------------------------
# Разбор авторов.
# Форматы в источниках сильно разные, поэтому:
#   1) находим все вхождения ФИО регуляркой (кириллица и латиница);
#   2) роль берём из ближайшего предшествующего ключевого слова;
#   3) если структура нестандартная — помечаем author_parsing_uncertain.
# ---------------------------------------------------------------------------

# Фамилия + инициалы: «Янкова В.Г.», «Фельдман Н.Б.»
RE_RU_NAME = re.compile(
    r"\b([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s+"
    r"([А-ЯЁ]\.\s*[А-ЯЁ]?\.?)"
)
# ФИО полностью: «Кокорекин Владимир Алексеевич», «Турецкий Евгений Александрович»
RE_RU_FULLNAME = re.compile(
    r"\b([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s+"
    r"([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s+"
    r"([А-ЯЁ][а-яё]+(?:ич|вна|чна|евич|овна|евна|ична|инична))\b"
)
# Инициалы + фамилия (латиница): «V.G. Yankova», «E.A. Smolyarchuk»
RE_EN_NAME = re.compile(
    r"\b((?:[A-Z]\.\s*){1,2})\s*([A-Z][a-z]+(?:-[A-Z][a-z]+)?)"
)
# Фамилия + инициалы (латиница): «Feldman N.B.», «Zhukova A.A.»
RE_EN_NAME2 = re.compile(
    r"\b([A-Z][a-z]+)\s+((?:[A-Z]\.\s*){1,2})"
)
# ФИО полностью латиницей: «Kokorekin Vladimir Alekseevich»
RE_EN_FULLNAME = re.compile(
    r"\b([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\s+([A-Z][a-z]+)\s+([A-Z][a-z]+)\b"
)

ROLE_PATTERNS = [
    (r"руководител|project lead|project leader|head of the project", "руководитель"),
    (r"аспирант|postgraduate|phd student|doctoral", "аспирант"),
    (r"магистрант|master'?s student", "магистрант"),
    (r"студент|student", "студент"),
    (r"профессор|professor|доцент|associate professor|assistant|lecturer|"
     r"преподаватель|научный сотрудник|researcher|кандидат|доктор|"
     r"candidate|d\.sc|phd|к\.ф\.н|к\.б\.н|к\.м\.н|к\.х\.н|д\.ф\.н|д\.м\.н|д\.б\.н",
     "участник"),
]

# Слова, которые не являются фамилией, но могут попасть в регулярку
NAME_STOPWORDS = {
    "Проект", "Команда", "Описание", "Цель", "Задачи", "Профессор", "Доцент",
    "Студенты", "Аспирант", "Аспиранты", "Магистранты", "Преподаватель",
    "Project", "Team", "Students", "Professor", "Department", "Institute",
    "University", "The", "Head", "Associate", "Assistant", "Senior", "Doctor",
    "Candidate", "Research",
    # Названия подразделений и почётные имена: в тексте команды встречаются
    # как «Коллектив кафедры … им. А.П. Арзамасцева», и наивная регулярка
    # принимает их за ФИО. Человеком это не является — выдумывать нельзя.
    "Коллектив", "Кафедра", "Кафедры", "Институт", "Университет",
    "Arzamastsev", "Nelyubin", "Sechenov", "Lomonosov", "Shemyakin",
    "Ovchinnikov", "Orekhovich", "Kutateladze", "Kozhevnikov",
    "Research", "Staff", "Department", "Institute", "University",
}

# Если в тексте команды нет ни одного ФИО, а есть слова этого набора —
# команда описана коллективно («Коллектив кафедры», «Research staff»),
# и разбирать её на людей нельзя.
COLLECTIVE_RE = re.compile(
    r"коллектив|сотрудники кафедры|научный коллектив|"
    r"\bresearch staff\b|\bthe team of the department\b|\bstaff of the department\b",
    re.IGNORECASE,
)

# Отчества для имён, записанных полностью
PATRONYMIC_END = re.compile(r"(ич|вна|чна|евич|овна|евна|ична|инична)$")


def role_for(text_before: str) -> str:
    low = text_before.lower()
    # ищем ближайшее ключевое слово — с конца
    best, best_pos = "не указана", -1
    for pattern, role in ROLE_PATTERNS:
        for m in re.finditer(pattern, low):
            if m.start() > best_pos:
                best_pos, best = m.start(), role
    return best


def parse_authors(team: str | None, lang: str) -> tuple[list[dict], list[str]]:
    """Возвращает (авторы, пометки). ФИО не теряются: всё, что не разобралось,
    остаётся в team_raw_* и фиксируется флагом."""
    if not team or not team.strip():
        return [], ["no_authors"]

    flags: list[str] = []

    # Коллективная запись команды вместо списка людей — это не ошибка разбора,
    # а факт: авторов поимённо в источнике нет. Выдумывать их нельзя.
    if COLLECTIVE_RE.search(team):
        flags.append("authors_collective_only")
        return [], flags

    found: dict[str, dict] = {}

    # ФИО полностью: «Кокорекин Владимир Алексеевич»
    for m in RE_RU_FULLNAME.finditer(team):
        surname, name_, patron = m.group(1), m.group(2), m.group(3)
        if surname in NAME_STOPWORDS or name_ in NAME_STOPWORDS:
            continue
        if not PATRONYMIC_END.search(patron):
            continue
        before = team[max(0, m.start() - 90):m.start()]
        key = f"{surname} {name_}"
        if key in found:
            continue
        role = role_for(before)
        initials = f"{name_[0]}.{patron[0]}."
        found[key] = {
            "name_ru": f"{surname} {name_} {patron}",
            "name_en": None,
            "initials": initials,
            "position_ru": before.strip(" ,;.")[-90:] or None,
            "position_en": None,
            "role_ru": role,
            "role_en": None,
            "photo": None, "profile_url": None, "orcid": None, "scopus_id": None,
            "researcher_id": None, "elibrary_id": None, "google_scholar": None,
            "researchgate": None,
            "is_lead": role == "руководитель",
        }

    for m in RE_RU_NAME.finditer(team):
        surname, ini = m.group(1).strip(), re.sub(r"\s+", "", m.group(2))
        if surname in NAME_STOPWORDS:
            continue
        before = team[max(0, m.start() - 90):m.start()]
        key = f"{surname} {ini}"
        if key in found:
            continue
        role = role_for(before)
        found[key] = {
            "name_ru": f"{surname} {ini}",
            "name_en": None,
            "initials": ini,
            "position_ru": before.strip(" ,;.")[-90:] or None,
            "position_en": None,
            "role_ru": role,
            "role_en": None,
            "photo": None, "profile_url": None, "orcid": None, "scopus_id": None,
            "researcher_id": None, "elibrary_id": None, "google_scholar": None,
            "researchgate": None,
            "is_lead": role == "руководитель",
        }

    if lang == "en":
        # ФИО полностью латиницей — транслит русского полного имени
        for m in RE_EN_FULLNAME.finditer(team):
            surname, name_, patron = m.group(1), m.group(2), m.group(3)
            if surname in NAME_STOPWORDS or name_ in NAME_STOPWORDS:
                continue
            if not re.search(r"(ovich|evich|ovna|evna|ich|vna)$", patron, re.IGNORECASE):
                continue
            key = f"{surname} {name_}"
            if key in found:
                continue
            before = team[max(0, m.start() - 90):m.start()]
            found[key] = {
                "name_ru": None,
                "name_en": f"{surname} {name_} {patron}",
                "initials": f"{name_[0]}.{patron[0]}.",
                "position_ru": None,
                "position_en": before.strip(" ,;.")[-90:] or None,
                "role_ru": role_for(before),
                "role_en": None,
                "photo": None, "profile_url": None, "orcid": None, "scopus_id": None,
                "researcher_id": None, "elibrary_id": None, "google_scholar": None,
                "researchgate": None,
                "is_lead": role_for(before) == "руководитель",
            }

        for m in RE_EN_NAME.finditer(team):
            ini, surname = re.sub(r"\s+", "", m.group(1)), m.group(2)
            if surname in NAME_STOPWORDS:
                continue
            key = f"{surname} {ini}"
            if key in found:
                continue
            before = team[max(0, m.start() - 90):m.start()]
            found[key] = {
                "name_ru": None,
                "name_en": f"{ini} {surname}",
                "initials": ini,
                "position_ru": None,
                "position_en": before.strip(" ,;.")[-90:] or None,
                "role_ru": role_for(before),
                "role_en": None,
                "photo": None, "profile_url": None, "orcid": None, "scopus_id": None,
                "researcher_id": None, "elibrary_id": None, "google_scholar": None,
                "researchgate": None,
                "is_lead": role_for(before) == "руководитель",
            }
        for m in RE_EN_NAME2.finditer(team):
            surname, ini = m.group(1), re.sub(r"\s+", "", m.group(2))
            if surname in NAME_STOPWORDS:
                continue
            key = f"{surname} {ini}"
            if key in found:
                continue
            before = team[max(0, m.start() - 90):m.start()]
            found[key] = {
                "name_ru": None,
                "name_en": f"{surname} {ini}",
                "initials": ini,
                "position_ru": None,
                "position_en": before.strip(" ,;.")[-90:] or None,
                "role_ru": role_for(before),
                "role_en": None,
                "photo": None, "profile_url": None, "orcid": None, "scopus_id": None,
                "researcher_id": None, "elibrary_id": None, "google_scholar": None,
                "researchgate": None,
                "is_lead": role_for(before) == "руководитель",
            }

    authors = list(found.values())
    if not authors:
        flags.append("no_authors")

    # Признак ненадёжного разбора ставим ТОЛЬКО когда структура действительно
    # нестандартная, иначе флаг срабатывает у всех и перестаёт быть сигналом.
    # Отсутствие явного руководителя — это НЕ ошибка разбора: в источниках
    # его чаще всего просто не помечают. Такой проект отмечается отдельным
    # флагом no_lead_marked, а не «ненадёжным разбором».
    if authors:
        if not any(a["is_lead"] for a in authors):
            flags.append("no_lead_marked")
        # Единственный автор там, где явно перечислена группа — разбор подозрителен
        if len(authors) == 1 and re.search(
            r"студент|student|аспирант|postgraduate|магистрант", team, re.I
        ):
            flags.append("author_parsing_uncertain")
    return authors, flags


# ---------------------------------------------------------------------------
# Разбор публикаций
# ---------------------------------------------------------------------------
# DOI.  В источнике встречается разрыв DOI пробелом (опечатка набора),
# напр. «10.20953/1729-9225- 2021-1-144-148». Такой DOI не рабочий:
# помечаем как битый, сохраняя исходную строку публикации целиком.
RE_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s,;]+)")
RE_YEAR = re.compile(r"\b(19|20)\d{2}\b")
RE_URL = re.compile(r"https?://\S+")
# Признак разорванного в источнике DOI: после него идёт ещё номер через пробел
RE_DOI_SPLIT = re.compile(r"\b10\.\d{4,9}/[^\s,;]*\s+\d+-\d+-\d+")


def parse_publications(section: str | None) -> tuple[list[dict], list[str]]:
    """Возвращает (публикации, пометки). Строка публикации сохраняется дословно."""
    if not section or not section.strip():
        return [], []
    pubs: list[dict] = []
    flags: list[str] = []
    chunks = re.split(r"(?m)^\s*(?:\d+[.)]|[-•])\s+", section)
    for ch in chunks:
        raw = " ".join(ch.split())
        if len(raw) < 25:
            continue
        doi = None
        url = None
        if RE_DOI_SPLIT.search(raw):
            # DOI разорван пробелом в источнике — как ссылку не используем
            flags.append("broken_doi_in_source")
        else:
            doi_m = RE_DOI.search(raw)
            if doi_m:
                cand = doi_m.group(1).rstrip(".,;)")
                # отбрасываем заведомо обрезанные хвосты вида «/10.20953/1729-9225-»
                if cand.endswith("-") or "/" not in cand[6:]:
                    flags.append("broken_doi_in_source")
                else:
                    doi = cand
        url_m = RE_URL.search(raw)
        if doi:
            url = f"https://doi.org/{doi}"
        elif url_m:
            url = url_m.group(0).rstrip(".,;)")
        year_m = None
        for y in RE_YEAR.finditer(raw):
            year_m = int(y.group(0))
        pubs.append({
            "raw": raw,
            "title": None,
            "year": year_m,
            "journal": None,
            "doi": doi,
            "url": url,
        })
    return pubs, flags


# ---------------------------------------------------------------------------
# Секции внутри .md
# ---------------------------------------------------------------------------
SECTION_ALIASES = {
    "team": ("Команда проекта", "Project team", "Project Team"),
    "joint": ("Проект выполняется совместно с", "The project is carried out jointly with"),
    "goal": ("Цель проекта", "Project goal", "Project Goal", "Project Aim", "Project Objective",
             "Project objective", "Objective", "Aim", "Goal", "Project Objectives"),
    "description": ("Описание проекта", "Project description", "Project Description"),
    "tasks": ("Ключевые задачи", "Ключевые задачи проекта", "Key Objectives", "Key objectives",
              "Key tasks", "Key points", "Задачи проекта", "Key objectives of the project"),
    "results": ("Основные научные результаты проекта", "Основные научные результаты",
                "Key scientific results", "Key scientific results of the project",
                "Expected Results", "Expected results", "Implementation of Project Results in Practice"),
    "publications": ("Основные научные публикации по проекту",
                     "Основные научные публикации по тематике проекта",
                     "Основные научные публикации", "Основные публикации по проекту",
                     "Список публикаций", "Key Scientific Publications on the Project",
                     "Key research publications on the project",
                     "Main scientific publications related to the project",
                     "Main scientific publications on the project",
                     "The main scientific publications on the project",
                     "Main Scientific Publications on the Project",
                     "Key Scientific Publications", "Key Publications",
                     "Key publications on the project", "List of publications",
                     "Main scientific publications", "Main publications on the project",
                     "Publications on the project"),
    "conference": ("Доклад на конференции", "Conference presentation"),
}


def split_sections(md_text: str) -> tuple[str, dict[str, str]]:
    """Возвращает (заголовок, {роль_секции: текст})."""
    lines = md_text.splitlines()
    title = ""
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        lines = lines[1:]

    sections: dict[str, str] = {}
    current = "intro"
    buf: list[str] = []
    for line in lines:
        if line.startswith("## "):
            sections[current] = "\n".join(buf).strip()
            head = line[3:].strip()
            current = "intro"
            for role, names in SECTION_ALIASES.items():
                if head in names:
                    current = role
                    break
            buf = []
        else:
            buf.append(line)
    sections[current] = "\n".join(buf).strip()
    return title, sections


def first_sentences(text: str | None, limit: int = 2, max_len: int = 420) -> str | None:
    """1–2 первых предложения для карточки. Не сочиняем — берём из источника."""
    if not text:
        return None
    flat = " ".join(text.split())
    if not flat:
        return None
    parts = re.split(r"(?<=[.!?])\s+", flat)
    out = ""
    for p in parts[:limit]:
        candidate = (out + " " + p).strip()
        if len(candidate) > max_len:
            break
        out = candidate
    return (out or parts[0])[:max_len].strip() or None


def main() -> int:
    depts_cfg = json.loads((DATA / "departments.json").read_text(encoding="utf-8"))
    file2dept = depts_cfg["file2dept"]
    base_url = depts_cfg["base_url"].rstrip("/")
    url_scheme = depts_cfg["url_scheme"]

    # обратная карта: dept -> lang -> имя файла
    dept_files: dict[str, dict[str, str]] = {}
    for fname, (dslug, lang) in file2dept.items():
        dept_files.setdefault(dslug, {})[lang] = fname

    # slug'и и пары берём из экстрактора — единый источник истины
    import importlib.util
    spec = importlib.util.spec_from_file_location("extract_md", REPO / "tools" / "extract_md.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)

    departments_out = []
    counts = {"departments": 0, "projects": 0, "projects_with_both_langs": 0,
              "projects_ru_only": 0, "projects_en_only": 0, "pages": 0, "qr_codes": 0}

    for dep in depts_cfg["departments"]:
        dslug = dep["slug"]
        files = dept_files.get(dslug, {})

        projects_out = []
        for k, slug in enumerate(ex.SLUGS.get(dslug, [])):
            pair = ex.PAIRS[dslug][k] if dslug in ex.PAIRS else None
            flags: list[str] = []

            rec = {
                "slug": slug,
                "title_ru": "", "title_en": "",
                "annotation_ru": None, "annotation_en": None,
                "description_ru": None, "description_en": None,
                "keywords_ru": [], "keywords_en": [],
                "team_raw_ru": None, "team_raw_en": None,
                "collaboration_ru": None, "collaboration_en": None,
                "langs_available": [],
                "translation_status": "ok",
                "url_ru": None, "url_en": None,
                "status": None, "years": None, "funding": None,
                "authors": [], "publications": [], "images": [], "links": [],
                "source_file_ru": files.get("ru"), "source_file_en": files.get("en"),
                "source_block_ru": None, "source_block_en": None,
                "review_flags": [],
            }

            for lang, idx in (("ru", pair[0]), ("en", pair[1])):
                md_path = MD / dslug / f"{slug}.{lang}.md"
                if not md_path.exists():
                    continue
                rec["langs_available"].append(lang)
                text = md_path.read_text(encoding="utf-8")
                title, sections = split_sections(text)

                rec[f"title_{lang}"] = title
                rec[f"description_{lang}"] = text.strip()
                rec[f"source_block_{lang}"] = idx + 1

                # цель → аннотация
                goal = sections.get("goal") or sections.get("intro")
                rec[f"annotation_{lang}"] = first_sentences(goal)

                team = sections.get("team")
                rec[f"team_raw_{lang}"] = " ".join(team.split()) if team else None
                if team is None:
                    flags.append("team_label_missing")

                joint = sections.get("joint")
                rec[f"collaboration_{lang}"] = " ".join(joint.split()) if joint else None

                authors, aflags = parse_authors(team, lang)
                # объединяем авторов ru и en по порядку, не теряя ничьих данных
                if lang == "ru":
                    rec["authors"] = authors
                else:
                    if not rec["authors"]:
                        rec["authors"] = authors
                    else:
                        # дополняем: если у ru-автора нет латинского имени, подставим
                        for i, a in enumerate(authors):
                            if i < len(rec["authors"]):
                                if not rec["authors"][i]["name_en"]:
                                    rec["authors"][i]["name_en"] = a["name_en"]
                                    rec["authors"][i]["position_en"] = a["position_en"]
                                    rec["authors"][i]["role_en"] = a["role_en"]
                            else:
                                rec["authors"].append(a)
                for f in aflags:
                    if f not in flags:
                        flags.append(f)

                pubs, pflags = parse_publications(sections.get("publications"))
                if pubs and not rec["publications"]:
                    rec["publications"] = pubs
                elif not pubs and lang == "ru":
                    flags.append("no_publications")
                for f in pflags:
                    if f not in flags:
                        flags.append(f)

            # URL — по шаблону из departments.json
            for lang in rec["langs_available"]:
                path = url_scheme.format(lang=lang, dept=dslug, slug=slug)
                rec[f"url_{lang}"] = base_url + path

            if not rec["langs_available"]:
                rec["translation_status"] = "missing"
            elif len(rec["langs_available"]) == 1:
                rec["translation_status"] = "missing"

            if rec["title_ru"] and "\n" in rec["title_ru"]:
                flags.append("title_multiline")

            # вопросы прямо в тексте источника
            blob = (rec["description_ru"] or "") + (rec["description_en"] or "")
            if re.search(r"\bTODO\b|\?\?\?|уточнить у|to be clarified", blob, re.I):
                flags.append("question_in_source")

            rec["review_flags"] = sorted(set(flags))
            projects_out.append(rec)

        ready = bool(projects_out)
        departments_out.append({
            "slug": dep["slug"],
            "name_ru": dep["name_ru"],
            "name_en": dep["name_en"],
            "abbr": dep.get("abbr"),
            "faculty_ru": dep.get("faculty_ru"),
            "faculty_en": dep.get("faculty_en"),
            "page_url": dep.get("page_url"),
            "status": dep.get("status", "ready" if ready else "pending"),
            "source_files": {"ru": files.get("ru"), "en": files.get("en")},
            "projects": projects_out,
        })

        if projects_out:
            counts["departments"] += 1
            counts["projects"] += len(projects_out)
            for p in projects_out:
                n = len(p["langs_available"])
                if n == 2:
                    counts["projects_with_both_langs"] += 1
                elif p["langs_available"] == ["ru"]:
                    counts["projects_ru_only"] += 1
                elif p["langs_available"] == ["en"]:
                    counts["projects_en_only"] += 1
                counts["pages"] += n
                counts["qr_codes"] += n

    out = {
        "meta": {
            "schema_version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_commit": None,
            "base_url": base_url,
            "url_scheme": url_scheme,
            "counts": counts,
        },
        "departments": departments_out,
    }

    path = DATA / "projects.json"
    new_text = json.dumps(out, ensure_ascii=False, indent=1)

    # Идемпотентность: если изменилась ТОЛЬКО метка времени сборки, файл не
    # перезаписываем. Иначе каждый прогон даёт бессмысленный дифф в git и
    # история засоряется — а по ней должно быть видно, что реально менялось.
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        old["meta"]["generated_at"] = out["meta"]["generated_at"]
        if json.dumps(old, ensure_ascii=False, indent=1) == new_text:
            print(f"Данные не изменились — файл не перезаписан")
            return 0

    path.write_text(new_text, encoding="utf-8")

    print(f"Записано: {path.relative_to(REPO)}")
    print(f"  кафедр с проектами: {counts['departments']}")
    print(f"  проектов:           {counts['projects']}")
    print(f"    с обоими языками: {counts['projects_with_both_langs']}")
    print(f"    только ru:        {counts['projects_ru_only']}")
    print(f"    только en:        {counts['projects_en_only']}")
    print(f"  страниц:            {counts['pages']}")
    print(f"  QR:                 {counts['qr_codes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
