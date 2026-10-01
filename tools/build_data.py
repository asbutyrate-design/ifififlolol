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

# Ответы заказчика — отдельный модуль: их применяем к данным поверх разбора.
_ar_spec = __import__("importlib.util", fromlist=["util"]).spec_from_file_location(
    "apply_reviews", Path(__file__).resolve().parent / "apply_reviews.py"
)
apply_reviews_mod = __import__("importlib.util", fromlist=["util"]).module_from_spec(_ar_spec)
_ar_spec.loader.exec_module(apply_reviews_mod)

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
# Инициал в латинице бывает ДВУХБУКВЕННЫЙ: Ya., Yu., Ye., Zh., Kh., Ts., Sh.
# Если допускать только одну букву, «Gribova Ya.V.» и «Medvedev Yu.V.» не находятся
# вовсе, а «Grigorieva V.Yu.» обрезается до «Grigorieva V.» — теряется второй инициал.
LETTER = r"[A-Z][a-z]?"
RE_EN_NAME = re.compile(
    r"\b((?:" + LETTER + r"\.\s*){1,2})\s*([A-Z][a-z]+(?:-[A-Z][a-z]+)?)"
)
# Фамилия + инициалы (латиница): «Feldman N.B.», «Zhukova A.A.»
RE_EN_NAME2 = re.compile(
    r"\b([A-Z][a-z]+)\s+((?:" + LETTER + r"\.\s*){1,2})"
)
# ФИО полностью латиницей: «Kokorekin Vladimir Alekseevich»
RE_EN_FULLNAME = re.compile(
    r"\b([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\s+([A-Z][a-z]+)\s+([A-Z][a-z]+)\b"
)

ROLE_PATTERNS = [
    (r"руководител|project lead|project leader|head of the project|team lead", "руководитель"),
    (r"аспирант|postgraduate|phd student|doctoral", "аспирант"),
    (r"магистрант|master'?s student", "магистрант"),
    (r"студент|student", "студент"),
    (r"профессор|professor|доцент|associate professor|assistant|lecturer|"
     r"преподаватель|научный сотрудник|researcher|кандидат|доктор|"
     r"candidate|d\.sc|phd|к\.ф\.н|к\.б\.н|к\.м\.н|к\.х\.н|д\.ф\.н|д\.м\.н|д\.б\.н",
     "участник"),
]

# ---------------------------------------------------------------------------
# Регалии и служебные слова. ВЫРЕЗАЮТСЯ из текста команды ДО поиска ФИО.
#
# Зачем именно вырезать, а не пропускать при проверке: регулярка «инициалы +
# слово с заглавной» ловит обрывки званий как фамилии:
#     «Professor, D.Sc. Feldman N.B.»  →  «D. Sc»      ← мусор
#     «PhD Gavryushina I.A.»           →  «I.A. Ph»    ← обрывок «PhD»
#     «PhD student: Kravchenko E.»     →  «E. Student» ← мусор
#     «Anurova M.N. Master's students» →  «M.N. Master»← мусор
# Из-за этого английские версии показывали 4 авторов там, где их 2.
# Вырезание регалий убирает источник ошибки целиком, а не лечит симптом.
# ---------------------------------------------------------------------------
DEGREE_WORDS = [
    # английские
    r"Doctor of Medical Sciences", r"Doctor of Pharmaceutical Sciences",
    r"Doctor of Biological Sciences", r"Doctor of Chemical Sciences",
    r"Doctor of Sciences", r"Candidate of Medical Sciences",
    r"Candidate of Pharmaceutical Sciences", r"Candidate of Biological Sciences",
    r"Candidate of Chemical Sciences", r"Candidate of Sciences",
    r"Doctor", r"Candidate", r"Professor", r"Associate Professor",
    r"Assistant Professor", r"Assistant", r"Senior Lecturer", r"Lecturer",
    r"Head of the Department", r"Head of Department", r"Head of the",
    r"Department of", r"Research staff", r"staff of the department",
    r"PhD student", r"PhD", r"Postgraduate", r"Doctoral",
    r"Master's students?", r"Master", r"Students?", r"Resident",
    r"\bD\.Sc\.?", r"\bPh\.?D\.?", r"\bDr\.", r"\bM\.D\.",
    r"\bPh\.D\.",
    # русские
    r"заведующий кафедрой", r"зав\. кафедрой", r"заведующая кафедрой",
    r"профессор", r"доцент", r"ассистент", r"старший преподаватель",
    r"ст\. преп\.", r"преподаватель", r"научный сотрудник",
    r"кандидат наук", r"доктор наук",
    r"аспиранты?", r"магистранты?", r"студенты?", r"ординатор",
    r"д\.ф\.н\.?", r"д\.м\.н\.?", r"д\.б\.н\.?", r"д\.х\.н\.",
    r"к\.ф\.н\.?", r"к\.м\.н\.?", r"к\.б\.н\.?", r"к\.х\.н\.",
    r"д\.фарм\.н\.?", r"к\.фарм\.н\.?", r"д\.мед\.н\.?", r"к\.мед\.н\.",
]
DEGREE_RE = re.compile("|".join(DEGREE_WORDS), re.IGNORECASE)

# Слова, которые фамилией быть не могут даже после вырезания регалий.
NAME_STOPWORDS = {
    # русские служебные и названия
    "Проект", "Команда", "Описание", "Цель", "Задачи", "Результаты", "Публикации",
    "Кафедра", "Кафедры", "Институт", "Университет", "Коллектив", "Работа",
    "Исследование", "Разработка", "Создание", "Изучение", "Обучение",
    # английские служебные и названия
    "Project", "Team", "Students", "Professor", "Department", "Institute",
    "University", "The", "Head", "Associate", "Assistant", "Senior", "Doctor",
    "Candidate", "Research", "Staff", "Laboratory", "Center", "Centre", "Group",
    "Shemyakin", "Ovchinnikov", "Orekhovich", "Sechenov", "Lomonosov",
    "Kutateladze", "Kozhevnikov", "Nelyubin", "Arzamastsev", "Vilar",
}

# Минимальная длина фамилии. Одно- и двухбуквенные обрывки («Sc», «Ph», «Dr»)
# фамилиями быть не могут — именно так отсекаются хвосты званий.
MIN_SURNAME_LEN = 3

# Отчество: слово с характерным суффиксом. Нужно, чтобы «Кокорекин Владимир
# Алексеевич» распознавалось как ФИО целиком, а «Новые перспективные виды» — нет.
PATRONYMIC_END = re.compile(
    r"(ич|ична|инична|вна|чна|евич|овна|евна)$", re.IGNORECASE
)

# Коллективная запись команды вместо списка людей: «Коллектив кафедры …»,
# «сотрудники кафедры», «research staff of the Department». В этом случае
# авторов поимённо в источнике НЕТ, выдумывать их нельзя.
COLLECTIVE_RE = re.compile(
    r"коллектив|сотрудники кафедры|научный коллектив|"
    r"\bresearch staff\b|\bthe team of the department\b|\bstaff of the department\b",
    re.IGNORECASE,
)


def strip_degrees(text: str) -> str:
    """Убирает регалии и должности из текста команды, оставляя ФИО и разделители."""
    cleaned = DEGREE_RE.sub(" ", text)
    # «(мл.)», «(Jr.)» — не часть ФИО
    cleaned = re.sub(r"\((?:мл|ст|jr|sr)\.?\)", " ", cleaned, flags=re.IGNORECASE)
    # После вырезания «PhD»/«Doctor»/«Candidate» остаются висеть предлоги
    # и одиночные служебные слова: «…, in Pharmaceutical Sciences, …».
    # Если их не убрать, шаг разбора «Фамилия Имя» соберёт из них
    # несуществующего человека «Pharmaceutical Sciences».
    cleaned = re.sub(r"[;:]+", ",", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned


# Обрывки званий, которые регулярки принимают за фамилию или имя.
# Пример: из «Doctor of Pharmaceutical Sciences» рождался автор
# «Pharmaceutical Sciences». Это не человек.
TITLE_WORD_RE = re.compile(
    r"^(pharmaceutical|medical|biological|chemical|physical|technical|"
    r"mathematical|agricultural|veterinary|economical|sciences?|"
    r"наук|медицинских|фармацевтических|биологических|химических|"
    r"физических|технических)$",
    re.IGNORECASE,
)


def looks_like_person_name(*parts: str) -> bool:
    """Ни одна часть ФИО не должна быть обрывком звания."""
    for p in parts:
        if not p:
            continue
        if TITLE_WORD_RE.match(p.strip(" .,")):
            return False
    return True


def looks_like_surname(word: str) -> bool:
    """Фамилия — слово не короче MIN_SURNAME_LEN, не служебное, с заглавной."""
    if len(word) < MIN_SURNAME_LEN:
        return False
    if word in NAME_STOPWORDS:
        return False
    if not word[0].isupper():
        return False
    # аббревиатуры из заглавных целиком («PhD», «VILAR») — не фамилия
    if word.isupper() and len(word) > 2:
        return False
    return True


def role_for(text_before: str) -> str:
    low = text_before.lower()
    # ищем ближайшее ключевое слово — с конца
    best, best_pos = "не указана", -1
    for pattern, role in ROLE_PATTERNS:
        for m in re.finditer(pattern, low):
            if m.start() > best_pos:
                best_pos, best = m.start(), role
    return best


def _mk_author(name_ru, name_en, initials, before, role, lang):
    """Единый конструктор записи автора — чтобы поля не разъезжались."""
    return {
        "name_ru": name_ru,
        "name_en": name_en,
        "initials": initials,
        "position_ru": before.strip(" ,;.")[-90:] if lang == "ru" else None,
        "position_en": before.strip(" ,;.")[-90:] if lang == "en" else None,
        "role_ru": role,
        "role_en": None,
        "photo": None, "profile_url": None, "orcid": None, "scopus_id": None,
        "researcher_id": None, "elibrary_id": None, "google_scholar": None,
        "researchgate": None,
        "is_lead": role == "руководитель",
        "added_from_review": False,
    }


def parse_authors(
    team: str | None, lang: str, extra_names: list[str] | None = None
) -> tuple[list[dict], list[str]]:
    """Возвращает (авторы, пометки). ФИО не теряются: всё, что не разобралось,
    остаётся в team_raw_* и фиксируется флагом.

    extra_names — имена, дописанные заказчиком вручную (data/reviews.json).
    Они добавляются первыми, чтобы не терялись при повторной сборке.
    """
    flags: list[str] = []
    found: dict[str, dict] = {}

    # 0) имена, подтверждённые заказчиком
    for nm in (extra_names or []):
        nm = nm.strip()
        if not nm:
            continue
        parts = nm.split()
        ini = ""
        if len(parts) >= 2:
            ini = "".join(f"{p[0]}." for p in parts[1:] if p)
        key = nm
        rec_ = _mk_author(
            nm if lang == "ru" else None,
            None if lang == "ru" else nm,
            ini or None, "добавлено из ответа заказчика", "не указана", lang,
        )
        rec_["added_from_review"] = True
        found[key] = rec_

    if not team or not team.strip():
        return list(found.values()), (["no_authors"] if not found else flags)

    # Коллективная запись команды вместо списка людей — это не ошибка разбора,
    # а факт: авторов поимённо в источнике нет. Выдумывать их нельзя.
    if COLLECTIVE_RE.search(team) and not found:
        return [], ["authors_collective_only"]

    # Регалии вырезаем ДО поиска — иначе они попадают в авторов
    clean = strip_degrees(team)

    # 1) ФИО полностью: «Кокорекин Владимир Алексеевич»
    for m in RE_RU_FULLNAME.finditer(clean):
        surname, name_, patron = m.group(1), m.group(2), m.group(3)
        if not looks_like_surname(surname) or name_ in NAME_STOPWORDS:
            continue
        if not PATRONYMIC_END.search(patron):
            continue
        key = f"{surname} {name_}"
        if key in found:
            continue
        before = team[max(0, m.start() - 90):m.start()]
        found[key] = _mk_author(
            f"{surname} {name_} {patron}", None,
            f"{name_[0]}.{patron[0]}.", before, role_for(before), lang,
        )

    # 2) Фамилия + инициалы (кириллица): «Янкова В.Г.»
    for m in RE_RU_NAME.finditer(clean):
        surname, ini = m.group(1).strip(), re.sub(r"\s+", "", m.group(2))
        if not looks_like_surname(surname):
            continue
        key = f"{surname} {ini}"
        if key in found:
            continue
        before = team[max(0, m.start() - 90):m.start()]
        found[key] = _mk_author(
            f"{surname} {ini}", None, ini, before, role_for(before), lang,
        )

    if lang == "en":
        # 3) Инициалы + фамилия: «V.G. Yankova»
        for m in RE_EN_NAME.finditer(clean):
            ini, surname = re.sub(r"\s+", "", m.group(1)), m.group(2)
            if not looks_like_surname(surname):
                continue
            key = f"{surname} {ini}"
            if key in found:
                continue
            before = team[max(0, m.start() - 90):m.start()]
            found[key] = _mk_author(
                None, f"{ini} {surname}", ini, before, role_for(before), lang,
            )
        # 4) Фамилия + инициалы: «Feldman N.B.»
        for m in RE_EN_NAME2.finditer(clean):
            surname, ini = m.group(1), re.sub(r"\s+", "", m.group(2))
            if not looks_like_surname(surname):
                continue
            key = f"{surname} {ini}"
            if key in found:
                continue
            before = team[max(0, m.start() - 90):m.start()]
            found[key] = _mk_author(
                None, f"{surname} {ini}", ini, before, role_for(before), lang,
            )
        # 5) ФАМИЛИЯ + Имя (без отчества латиницей): «Kokorekin Vladimir».
        #
        # Здесь НЕЛЬЗЯ использовать регулярку на три слова подряд:
        # в «Associate Professor of the Department Kokorekin Vladimir Alekseevich»
        # первыми двумя словами окажутся «Department Kokorekin» — и фамилия будет
        # прочитана неверно. Поэтому идём по словам и берём пару
        # «Фамилия Имя», только если первое слово похоже на фамилию,
        # а второе — не служебное и не часть звания.
        words = re.findall(r"[A-Za-z\-]+", clean)
        for i in range(len(words) - 1):
            surname, name_ = words[i], words[i + 1]
            if not looks_like_surname(surname):
                continue
            if not looks_like_person_name(surname, name_):
                continue
            if name_ in NAME_STOPWORDS or not name_[0].isupper():
                continue
            # --- три защиты от мусорных «людей» ---------------------------------
            # 1) Одиночная буква — это инициал. Такие уже разобраны шагами 3–4.
            #    Без проверки «Krasnyuk I.I.» давал лишнего «Krasnyuk I».
            if len(name_) < 3:
                continue
            # 2) Отчество — не имя. «Alekseevich» человеком не является.
            if re.search(r"(ovich|evich|ovna|evna|ichna|inichna)$", name_, re.IGNORECASE):
                continue
            # 3) Внутри «Фамилия Имя Отчество» пара (Имя, Отчество) — не человек,
            #    а всю тройку уже разобрал шаг 1. Иначе «Kokorekin Vladimir
            #    Alekseevich» порождал ещё и «Vladimir Alekseevich».
            nxt = words[i + 2] if i + 2 < len(words) else ""
            if nxt and re.search(r"(ovich|evich|ovna|evna|ichna|inichna)$", nxt, re.IGNORECASE):
                continue
            # отчество следом — берём его же, если оно есть
            patr = words[i + 2] if i + 2 < len(words) else ""
            if not re.search(r"(ovich|evich|ovna|evna|ich|vna)$", patr, re.IGNORECASE):
                patr = ""
            # защита от «of the Department»: следующее слово не должно
            # быть предлогом/служебным
            if surname.lower() in {"of", "the", "and", "sciences", "science"}:
                continue
            key = f"{surname} {name_}"
            if key in found:
                continue
            full = f"{surname} {name_}" + (f" {patr}" if patr else "")
            found[key] = _mk_author(
                None, full, f"{name_[0]}.", "", "не указана", lang,
            )

    # --- Сведение дублей -----------------------------------------------------
    # Один человек может прийти из разных источников: из ответа заказчика
    # («Кокорекин Владимир Алексеевич»), полным ФИО в тексте и инициалами.
    # Ключ сведения — фамилия + первый инициал: «Кокорекин Владимир»,
    # «Кокорекин В.А.» и «Кокорекин Владимир Алексеевич» это один человек.
    merged: dict[str, dict] = {}
    for a in found.values():
        nm = a["name_ru"] or a["name_en"] or ""
        parts = nm.replace(".", " ").split()
        if not parts:
            continue
        surname = parts[0]
        initial = parts[1][0].upper() if len(parts) > 1 and parts[1] else ""
        key = f"{surname.lower()}|{initial}"
        if key in merged:
            # дополняем уже найденную запись недостающими полями
            cur = merged[key]
            for field in ("name_ru", "name_en", "initials", "position_ru",
                          "position_en", "role_en"):
                if not cur.get(field) and a.get(field):
                    cur[field] = a[field]
            # полное ФИО информативнее инициалов — предпочитаем его
            if a.get("name_ru") and cur.get("name_ru") and len(a["name_ru"]) > len(cur["name_ru"]):
                cur["name_ru"] = a["name_ru"]
            if a.get("name_en") and cur.get("name_en") and len(a["name_en"]) > len(cur["name_en"]):
                cur["name_en"] = a["name_en"]
            if a.get("added_from_review"):
                cur["added_from_review"] = True
            if a.get("is_lead"):
                cur["is_lead"] = True
        else:
            merged[key] = dict(a)

    authors = list(merged.values())
    if not authors:
        flags.append("no_authors")
    elif not any(a["is_lead"] for a in authors):
        flags.append("no_lead_marked")
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

    sections: dict[str, list[str]] = {}
    current = "intro"
    buf: list[str] = []
    for line in lines:
        if line.startswith("## "):
            sections.setdefault(current, []).append("\n".join(buf).strip())
            head = line[3:].strip()
            current = "intro"
            for role, names in SECTION_ALIASES.items():
                if head in names:
                    current = role
                    break
            buf = []
        else:
            buf.append(line)
    sections.setdefault(current, []).append("\n".join(buf).strip())

    # ВАЖНО: один и тот же заголовок встречается в файле несколько раз.
    # Пример: ФП_анг содержит ДВА «## Project Team» — руководитель отдельной
    # секцией, остальные участники в следующей. Если присваивать по ключу,
    # вторая секция затирает первую и руководитель исчезает.
    # Поэтому куски СОЕДИНЯЕМ, а не перезаписываем.
    joined: dict[str, str] = {}
    for role, chunks in sections.items():
        merged = "\n".join(c for c in chunks if c.strip())
        if merged:
            joined[role] = merged
    return title, joined


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

    # --- ответы заказчика (data/reviews.json) -----------------------------
    reviews = apply_reviews_mod.load_reviews()
    reviews_by_project = apply_reviews_mod.index_by_project(reviews)
    # имена, дописанные заказчиком вручную: project_key -> [ФИО]
    extra_names_by_project: dict[str, list[str]] = {}
    for key, answers in reviews_by_project.items():
        names: list[str] = []
        for a in answers:
            if a.get("action") == "add_author":
                names.extend(a.get("authors") or [])
        if names:
            extra_names_by_project[key] = names

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

                authors, aflags = parse_authors(
                    team, lang, extra_names_by_project.get(f"{dslug}/{slug}")
                )
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

            # --- ответы заказчика к этому проекту -------------------------
            project_key = f"{dslug}/{slug}"
            answers = reviews_by_project.get(project_key)
            if answers:
                results_ru = None
                md_ru = MD / dslug / f"{slug}.ru.md"
                if md_ru.exists():
                    _, sec_ru = split_sections(md_ru.read_text(encoding="utf-8"))
                    results_ru = sec_ru.get("results") or sec_ru.get("tasks")
                rec["authors"], rec["publications"], flags = apply_reviews_mod.apply_reviews(
                    project_key, rec["authors"], rec["publications"], flags,
                    answers, results_section=results_ru,
                )
            rec["review_flags"] = sorted(set(flags))

            # отклик заказчика виден на странице кафедры, а не только в отчёте
            for a in answers or []:
                if a.get("action") == "mark_todo":
                    rec.setdefault("todos", []).append({
                        "source": a.get("item"),
                        "text": a.get("answer"),
                        "doer": "кафедра",
                    })

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
