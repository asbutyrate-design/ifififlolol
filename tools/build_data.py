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

import difflib
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

# Фамилия + Имя ПОЛНОСТЬЮ, без отчества: «Байрамкулова Диана», «Фам Фыонг Нам».
# Отчества в источниках есть не всегда, а инициалов может не быть вовсе —
# без этого правила такие люди находились только в английской версии,
# и возникало ложное «расхождение ru↔en»: в EN человек есть, в RU нет.
RE_RU_NAME_FULL = re.compile(
    r"\b([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s+"
    r"([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\b"
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

# Метки ГРУПП, за которыми идёт перечисление людей. Роль в источнике
# задаётся именно ими, поэтому они имеют приоритет над одиночными словами.
GROUP_ROLE_PATTERNS = [
    (r"руководител[ья]\s+проекта\s*:|project\s+lead(?:er)?\s*:|team\s+lead\s*:", "руководитель"),
    (r"аспиранты\s*:|аспирантка\s*:|аспирант\s*:",
     "аспирант"),
    (r"postgraduates?\s*:|postgraduate\s+students?\s*:|phd\s+students?\s*:|"
     r"doctoral\s+students?\s*:", "аспирант"),
    (r"магистранты?\s*:|master'?s\s+students?\s*:", "магистрант"),
    (r"\bстуденты\s*:|\bстудентка\s*:|\bstudents\s*:|\bstudent\s*:", "студент"),
    (r"ординаторы?\s*:|residents?\s*:", "ординатор"),
    (r"соискатели?\s*:", "соискатель"),
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
    # Слова из НАЗВАНИЙ подразделений. В англоязычных источниках должность
    # переходит в ФИО без разделителя:
    #   «…of the Department of Nervous Diseases Shindryaeva N.N.»
    #   «…of the Department of Organization and Economics of Pharmacy Gerasimova D.A.»
    # Из-за этого «Nervous Diseases» и «Pharmacy Gerasimova» становились
    # авторами. Настоящий человек в таких строках идёт СРАЗУ ПОСЛЕ названия
    # и находится отдельно («Shindryaeva N.N.», «Gerasimova D.A.»), так что
    # запрет этих слов на роль фамилии никого не теряет.
    "Nervous", "Diseases", "Disease", "Pharmacy", "Pharmacology", "Organization",
    "Economics", "Economy", "Medical", "Medicine", "Natural", "Pharmaceutical",
    "Sciences", "Science", "Clinic", "Clinical", "Hospital", "State", "Moscow",
    "System", "Systems", "Technology", "Chemistry", "Chemical", "Biology",
    "Biological", "Physical", "First", "Russian", "Novosibirsk",
    # Обрывки СОКРАЩЁННЫХ степеней. В источнике пишут «Dr. Pharm. Sci.»,
    # после чего остаётся пара «Pharm Sci», похожая на «Фамилия Имя».
    # Полные формы («Pharmaceutical Sciences») отсекаются TITLE_WORD_RE,
    # а сокращения — нет, поэтому перечисляем их явно.
    "Pharm", "Sci", "Dr", "Cand", "Assoc", "Prof", "Med", "Biol", "Chem",
    "Phys", "Tech", "Acad", "Univ", "Res",
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
# Конец перечисления команды. После этой фразы начинается описание, ГДЕ
# выполняется проект, а не новые люди. Без обрезки из названий кафедр,
# институтов и клиник рождаются фантомные «авторы»:
#     «Nervous Diseases», «First Moscow», «Clinical Hospital», «Pharmacy Gerasimova».
# Заказчик указал на это прямо (ответ №9).
TEAM_END_RE = re.compile(
    r"(Проект\s+выполняется|Работа\s+выполняется|"
    r"The\s+project\s+is\s+carried\s+out|The\s+work\s+is\s+being\s+carried\s+out|"
    r"The\s+work\s+is\s+carried\s+out)",
    re.IGNORECASE,
)


def cut_at_team_end(team: str) -> str:
    """Обрезает секцию команды там, где начинается описание места работы.

    Если до фразы нет ничего осмысленного — вся «команда» и есть описание,
    резать нечего: возвращаем исходный текст.
    """
    m = TEAM_END_RE.search(team)
    if not m:
        return team
    head = team[:m.start()].rstrip(" ,;.\u2014-")
    return head if head.strip() else team


COLLECTIVE_RE = re.compile(
    r"коллектив|сотрудники кафедры|научный коллектив|"
    r"\bresearch staff\b|\bthe team of the department\b|\bstaff of the department\b",
    re.IGNORECASE,
)


def normalize_homoglyphs(text: str) -> str:
    """Заменяет латинские буквы, похожие на кириллические, внутри русских слов.

    Зачем: в источнике встречается «Cтуденты:» с ЛАТИНСКОЙ C. Из-за этого
    русское правило роли «студент» не срабатывало, и роль у человека
    оставалась неопределённой. Ошибка была незаметна глазом — буквы
    выглядят одинаково.
    """
    # латинские двойники кириллицы
    lat2cyr = str.maketrans({
        "C": "С", "c": "с", "A": "А", "a": "а", "B": "В", "E": "Е", "e": "е",
        "O": "О", "o": "о", "P": "Р", "p": "р", "H": "Н", "K": "К", "k": "к",
        "M": "М", "T": "Т", "y": "у", "X": "Х", "x": "х",
    })
    out = []
    for token in re.split(r"(\s+)", text):
        if not token.strip():
            out.append(token)
            continue
        has_cyr = any("\u0400" <= ch <= "\u04ff" for ch in token)
        if has_cyr:
            token = token.translate(lat2cyr)
        out.append(token)
    return "".join(out)


def strip_degrees(text: str) -> str:
    """Заменяет регалии и должности ПРОБЕЛАМИ, СОХРАНЯЯ ДЛИНУ строки.

    Почему сохраняя длину. Раньше регалии удалялись (``sub(" ", ...)``),
    строка укорачивалась, но позиции найденных ФИО брались из очищенной
    строки и применялись к СЫРОЙ при вычислении ``before``. Сдвиг доходил
    до 26 символов, и роли приписывались не тем людям: профессор получал
    «роль не указана», магистрант — «участник», студент — «магистрант».

    Подстановка пробелов той же длины убирает источник ошибки целиком:
    индекс символа в очищенной строке совпадает с индексом в исходной,
    поэтому ``before`` всегда соответствует тому же человеку.
    """
    def blank(mm: "re.Match[str]") -> str:
        # каждый непробельный символ → пробел, переводы строк сохраняем,
        # чтобы не ломать структуру и границы строк
        return "".join("\n" if ch == "\n" else " " for ch in mm.group(0))

    cleaned = DEGREE_RE.sub(blank, text)
    # «(мл.)», «(Jr.)» — не часть ФИО
    cleaned = re.sub(
        r"\((?:мл|ст|jr|sr)\.?\)",
        lambda mm: " " * len(mm.group(0)),
        cleaned, flags=re.IGNORECASE,
    )
    # разделители-двоеточия не удаляем, а превращаем в запятые — длина та же
    cleaned = cleaned.replace(":", ",").replace(";", ",")
    assert len(cleaned) == len(text), "strip_degrees обязан сохранять длину"
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
    """Роль человека по тексту ПЕРЕД его ФИО.

    Ключевое отличие от первой версии: приоритет у ГРУППОВОЙ метки
    («Магистранты:», «Студенты:», «Аспиранты:»), а не у ближайшего слова.
    В источниках роль задаётся именно меткой, которая стоит ПЕРЕД списком:

        «Магистранты: Запевалов А.Т., Низова А.Р. Студенты: Дрозд А.А.»

    Здесь у Запевалова перед именем встречается ещё и «профессор» —
    регалия ПЕРВОГО человека в строке. Ближайшее слово давало ему
    «участник», а студент Дрозд получал «магистрант» от метки предыдущей
    группы. Ошибку заметил заказчик.

    Логика: ищем последнюю групповую метку; если она есть и стоит ближе,
    чем любое «одиночное» указание роли, — берём её. Иначе — ближайшее
    одиночное слово.
    """
    low = text_before.lower()
    low = normalize_homoglyphs(low)

    # 1) Групповые метки. Собираем ВСЕ совпадения, затем выбрасываем те,
    #    что целиком лежат внутри более длинного: в «postgraduate student:»
    #    метка «student:» — часть «postgraduate student:», и без чистки
    #    аспирант получал роль «студент». Из оставшихся берём ПОСЛЕДНЮЮ:
    #    роль задаёт ближайшая к человеку группа.
    found_groups: list[tuple[int, int, str]] = []
    for pattern, role in GROUP_ROLE_PATTERNS:
        for m in re.finditer(pattern, low):
            found_groups.append((m.start(), m.end(), role))
    # выбрасываем вложенные
    outer = [
        g for g in found_groups
        if not any(
            o is not g and o[0] <= g[0] and g[1] <= o[1] and (o[0], o[1]) != (g[0], g[1])
            for o in found_groups
        )
    ]
    group_pos, group_role, group_end = -1, None, -1
    for s, e, role in outer:
        if s > group_pos:
            group_pos, group_role, group_end = s, role, e

    # 2) ближайшее одиночное указание роли
    single_role, single_pos = "не указана", -1
    for pattern, role in ROLE_PATTERNS:
        for m in re.finditer(pattern, low):
            if m.start() > single_pos:
                single_pos, single_role = m.start(), role

    # Групповая метка выигрывает всегда, если она вообще есть в тексте:
    # «доцент Иванов, студенты: Петров» — Петров студент, хотя «доцент»
    # стоит правее начала. Но если одиночное указание идёт ПОСЛЕ группы,
    # значит началась новая группа/персональная роль — тогда оно.
    # Групповая метка выигрывает, если одиночное указание лежит ВНУТРИ неё
    # («student» внутри «Master's students:») — иначе одиночное слово
    # перебивало собственную группу, и магистрант становился студентом.
    if group_role and (group_pos >= single_pos or
                       (group_pos <= single_pos < group_end)):
        return group_role
    return single_role


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


def _split_name(nm: str) -> tuple[str, str]:
    """Разбирает запись имени на (фамилия, первый инициал).

    Форматы в данных разные, и «наивный» разбор ломается:
        «E.A. Smolyarchuk»  → parts[0]='E', parts[1]='A'  → фамилия «E»   ← неверно
        «Смолярчук Е.А.»    → parts[0]='Смолярчук', 'Е'   → верно
        «Kokorekin Vladimir Alekseevich» → верно
    Поэтому: если первая часть — одиночная буква (или «E.A.» после замены
    точек), значит перед нами инициалы, и фамилия ИДЁТ СЛЕДОМ.
    """
    raw = nm.strip()
    # «E.A. Smolyarchuk» — инициалы впереди.
    # Инициал бывает ДВУХБУКВЕННЫМ: «Zh.M. Kozlova», «Yu.A. Saksonova»,
    # «Shch.S. Ivanov». Раньше шаблон требовал ровно одну букву, и такая
    # фамилия разбиралась как «Zh» с инициалом «M» — человек терялся.
    m = re.match(r"^((?:[A-Za-zА-Яа-яЁё]{1,2}\s*\.\s*){1,3})(.+)$", raw)
    if m:
        ini = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", m.group(1))
        rest = m.group(2).strip().split()
        surname = rest[0] if rest else ""
        return surname, (ini[0] if ini else "")
    parts = raw.replace(".", " ").split()
    if not parts:
        return "", ""
    # «И.И. Иванов» — первый токен после снятия точек пуст/односимвольный
    if len(parts) >= 2 and len(parts[0]) == 1 and len(parts[1]) > 1:
        return parts[1], parts[0].upper()
    surname = parts[0]
    initial = parts[1][0].upper() if len(parts) > 1 and parts[1] else ""
    return surname, initial


def _person_key(a: dict) -> str:
    """Ключ сведения одного человека: «фамилия|инициал».

    Раньше ключ строился как parts[0] от строки с инициалами впереди, из-за чего
    «E.A. Smolyarchuk» и «E.A. Zavadich» давали ОДИН ключ 'e|A' и склеивались
    в одного человека — один из двоих терялся.
    """
    nm = a.get("name_ru") or a.get("name_en") or ""
    surname, initial = _split_name(nm)
    return f"{surname.lower()}|{initial.upper()}"


def _script_of(text: str) -> str:
    """Письменность строки: "cyr", "lat" или "mixed"/"none".

    Нужна, чтобы имена, досланные заказчиком в ответах, попадали ТОЛЬКО
    в свою языковую версию. Иначе при разборе английского текста русское
    «Кокорекин Владимир Алексеевич» дописывалось как name_en и человек
    задваивался: один раз латиницей из источника, второй — кириллицей
    из ответа.
    """
    cyr = sum(1 for ch in text if "\u0400" <= ch <= "\u04ff")
    lat = sum(1 for ch in text if ("a" <= ch <= "z") or ("A" <= ch <= "Z"))
    if cyr and not lat:
        return "cyr"
    if lat and not cyr:
        return "lat"
    return "mixed" if (cyr or lat) else "none"



def _find_pos(text: str, *words: str) -> int:
    """Позиция начала ФИО в тексте. -1, если не найдено.

    Ищем слова ПОСЛЕДОВАТЕЛЬНО: «Pham Phuong Nam» должно находиться как
    единая фраза, а не как позиция слова «Pham» в постороннем месте.
    """
    pat = r"\b" + r"\s+".join(re.escape(w) for w in words if w) + r"\b"
    m = re.search(pat, text)
    return m.start() if m else -1


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
    want = "cyr" if lang == "ru" else "lat"
    for nm in (extra_names or []):
        nm = nm.strip()
        if not nm:
            continue
        # имя идёт ТОЛЬКО в свою языковую версию — иначе дубли
        if _script_of(nm) not in (want, "mixed"):
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

    # Гомоглифы: «Cтуденты» с латинской C и подобное. Правим ДО разбора.
    team = normalize_homoglyphs(team)

    # Описание места работы («The project is carried out at the Department…»)
    # отрезаем ДО разбора людей — иначе названия кафедр и клиник становятся
    # «авторами». После обрезки индексы в team и clean совпадают.
    team = cut_at_team_end(team)
    # Регалии гасим ДО поиска, чтобы они не попадали в авторов.
    # strip_degrees СОХРАНЯЕТ ДЛИНУ (см. его докстроку), поэтому индексы
    # в clean и в team совпадают. ФИО ищем в clean, а роль читаем из team —
    # там групповые метки («Магистранты:», «Студенты:») не затёрты.
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

    # Латинские написания ищем в блоках ЛЮБОГО языка: в русском тексте тоже
    # бывают сотрудники, записанные латиницей («Bello Taye»), поэтому условие
    # не «lang == "en"», а проверка обоих языков.
    if lang in ("ru", "en"):
        # 2б) Фамилия + Имя без отчества (кириллица): «Байрамкулова Диана».
        #     Идёт ПОСЛЕ шага 2 (инициалы) и ДО латинских шагов.
        for m in RE_RU_NAME_FULL.finditer(clean):
            surname, name_ = m.group(1), m.group(2)
            if not looks_like_surname(surname) or name_ in NAME_STOPWORDS:
                continue
            if len(name_) < 3:
                continue
            # отчество уже разобрано шагом 1 — здесь только без него
            if PATRONYMIC_END.search(name_):
                continue
            # не часть «Фамилия Имя Отчество»: если следом отчество — пропускаем
            tail = clean[m.end():m.end() + 40]
            if re.match(r"\s+[А-ЯЁ][а-яё]+(?:ич|вна|чна|евич|овна|евна|ична|инична)\b", tail):
                continue
            key = f"{surname} {name_}"
            if key in found:
                continue
            # ВАЖНО: роль берём из СЫРОГО текста (team), а не из clean.
            # strip_degrees превращает «аспирант:» в «аспирант,», из-за чего
            # групповые метки перестают опознаваться и человек получает
            # роль «не указана». Индексы совпадают: strip_degrees сохраняет
            # длину строки (это проверяется assert'ом внутри неё).
            before = team[max(0, m.start() - 90):m.start()]
            found[key] = _mk_author(
                f"{surname} {name_}", None, f"{name_[0]}.",
                before, role_for(before), lang,
            )

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
        # 4б) ПОЛНОЕ ИМЯ латиницей: «Kokorekin Vladimir Alekseevich».
        #
        # Идём СКОЛЬЗЯЩИМ ОКНОМ по словам, а не регуляркой на три слова подряд.
        # Регулярка не подходит: в «…of the Department Kokorekin Vladimir
        # Alekseevich» она жадным совпадением захватывает
        # «Department Kokorekin Vladimir» как ФИО, отбрасывает его (Department —
        # служебное слово) и до настоящей тройки уже не доходит, потому что
        # совпадения не перекрываются. Окно такой ошибки не делает.
        words = re.findall(r"[A-Za-z\-]+", clean)
        for k in range(len(words) - 2):
            surname, name_, patr = words[k], words[k + 1], words[k + 2]
            if not looks_like_surname(surname):
                continue
            if name_ in NAME_STOPWORDS or not looks_like_person_name(surname, name_):
                continue
            # третье слово обязано быть отчеством, иначе это не ФИО
            if not re.search(r"(ovich|evich|ovna|evna|ichna|inichna)$", patr, re.IGNORECASE):
                continue
            # предыдущее слово не должно быть отчеством: иначе мы поймали
            # хвост чужого ФИО («…Alekseevich, Turetsky Evgeny»)
            prev = words[k - 1] if k > 0 else ""
            if prev and re.search(r"(ovich|evich|ovna|evna|ichna|inichna)$", prev, re.IGNORECASE):
                continue
            key = f"{surname} {name_}"
            if key in found:
                continue
            found[key] = _mk_author(
                None, f"{surname} {name_} {patr}",
                f"{name_[0]}.{patr[0]}.", "", "не указана", lang,
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
            # 4) Предыдущее слово — отчество? Тогда пара («отчество», «фамилия»)
            #    не человек. Без этой проверки «Alekseevich Turetsky» из
            #    «Kokorekin Vladimir Alekseevich, Turetsky Evgeny» рождало
            #    фантомного человека с фамилией Alekseevich.
            prev = words[i - 1] if i > 0 else ""
            if prev and re.search(r"(ovich|evich|ovna|evna|ichna|inichna)$", prev, re.IGNORECASE):
                continue
            # Пара обязана быть соседней В ОРИГИНАЛЕ, а не только в очищенном
            # тексте: strip_degrees выбрасывает звания («PhD», «Professor»),
            # и слова, между которыми в источнике стояло «. PhD, Professor »,
            # становятся «соседями». Так рождался фантомный автор
            # «Saksonova Anurova» — два человека, склеенные в одного.
            if not re.search(
                rf"\b{re.escape(surname)}\s+{re.escape(name_)}\b", team
            ):
                continue
            key = f"{surname} {name_}"
            if key in found:
                continue
            full = f"{surname} {name_}" + (f" {patr}" if patr else "")
            # Одно ФИО не должно распадаться на двух людей. «Pham Phuong Nam»
            # давало «Pham Phuong» и «Phuong Nam», потому что каждая пара
            # соседних слов выглядит правдоподобным «Фамилия Имя».
            # Если слово уже вошло в ЧУЖОЕ полное имя как первое или второе —
            # это то же самое ФИО, а не новый человек.
            taken_words = set()
            for rec_ in found.values():
                nm = rec_.get("name_en") or ""
                taken_words.update(nm.split())
            # Если имя уже внутри чужой записи — не плодим второго человека.
            # Но если за name_ идёт ЕЩЁ одно слово-имя, значит ФИО длиннее:
            # «Pham Phuong Nam» — берём целиком, а не «Pham Phuong».
            nxt2 = words[i + 2] if i + 2 < len(words) else ""
            longer = (
                nxt2
                and nxt2[0].isupper()
                and nxt2 not in NAME_STOPWORDS
                and not re.search(r"(ovich|evich|ovna|evna)$", nxt2, re.I)
            )
            if (surname in taken_words or name_ in taken_words) and not longer:
                continue
            if longer:
                full_candidate = f"{surname} {name_} {nxt2}"
                if not re.search(
                    rf"\b{re.escape(surname)}\s+{re.escape(name_)}\s+{re.escape(nxt2)}\b",
                    team,
                ):
                    longer = False
            if longer:
                key2 = f"{surname} {name_} {nxt2}"
                if key2 not in found:
                    pos2 = _find_pos(clean, surname, name_, nxt2)
                    before2 = clean[max(0, pos2 - 90):pos2] if pos2 >= 0 else ""
                    found[key2] = _mk_author(
                        None, full_candidate, f"{name_[0]}.", before2,
                        role_for(before2) if pos2 >= 0 else "не указана", lang,
                    )
                continue
            pos_ = _find_pos(clean, surname, name_)
            before_ = clean[max(0, pos_ - 90):pos_] if pos_ >= 0 else ""
            found[key] = _mk_author(
                None, full, f"{name_[0]}.", before_,
                role_for(before_) if pos_ >= 0 else "не указана", lang,
            )

    # --- Сведение дублей -----------------------------------------------------
    # Один человек может прийти из разных источников: из ответа заказчика
    # («Кокорекин Владимир Алексеевич»), полным ФИО в тексте и инициалами.
    # Ключ сведения — фамилия + первый инициал: «Кокорекин Владимир»,
    # «Кокорекин В.А.» и «Кокорекин Владимир Алексеевич» это один человек.
    merged: dict[str, dict] = {}
    for a in found.values():
        key = _person_key(a)
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

    # --- Убираем разорванные ФИО -------------------------------------------
    # Иногда одно имя распадается на две записи: «Pham Phuong Nam» и «Phuong Nam».
    # Ключ сведения их не ловит (фамилии разные: Pham и Phuong). Признак
    # осколка: ВСЕ слова одной записи входят в другую запись. Такую запись
    # удаляем — иначе на странице появится человек, которого нет.
    vals = list(merged.values())
    keep: list[dict] = []
    for i, a in enumerate(vals):
        ta = set((a.get("name_en") or a.get("name_ru") or "").replace(".", " ").split())
        if not ta:
            continue
        fragment = False
        for j, b in enumerate(vals):
            if i == j:
                continue
            tb = set((b.get("name_en") or b.get("name_ru") or "").replace(".", " ").split())
            if len(ta) < len(tb) and ta < tb:
                fragment = True
                break
        if not fragment:
            keep.append(a)

    authors = keep
    if not authors:
        flags.append("no_authors")
    elif not any(a["is_lead"] for a in authors):
        flags.append("no_lead_marked")
    authors = _drop_name_fragments(authors, lang)

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


# ---------------------------------------------------------------------------
# Сопоставление людей между языковыми версиями
#
# Раньше ru и en склеивались ПО НОМЕРУ В СПИСКЕ:
#     rec["authors"][i]["name_en"] = authors[i]["name_en"]
# Если английский список короче русского хотя бы на человека, все следующие
# получают ЧУЖУЮ фамилию. Это уже случилось в farmak/digital-prescribing:
# Завадич Е.А. получила фамилию Тращенковой.
#
# Теперь сопоставление идёт ПО ЧЕЛОВЕКУ: фамилия переводится в латиницу и
# сравнивается с английской фамилией. Инициалы служат усилителем (совпали —
# плюс к счёту) и тормозом (разошлись — сильный минус). Несопоставленный
# англичанин ДОБАВЛЯЕТСЯ в список, а не выбрасывается; русский без пары
# остаётся с name_en = None и получает флаг.
# ---------------------------------------------------------------------------

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _translit(s: str) -> str:
    """Русская фамилия в латиницу — чтобы сравнивать с английским написанием."""
    out = []
    for ch in s.lower():
        out.append(_TRANSLIT.get(ch, ch))
    return "".join(out)


def _surname_latin(a: dict) -> str:
    """Латинское написание фамилии автора, чем бы оно ни было записано.

    Оставлено для обратной совместимости: берёт ПЕРВОЕ слово. Для записей
    вида «Diana Bayramkulova» (Имя Фамилия) это неверно — используйте
    _surname_candidates().
    """
    for nm in (a.get("name_ru"), a.get("name_en")):
        if not nm:
            continue
        surname, _ = _split_name(nm)
        if not surname:
            continue
        if re.search(r"[а-яё]", surname.lower()):
            return _translit(surname)
        return surname.lower()
    return ""


def _surname_candidates(a: dict) -> list[str]:
    """ВСЕ возможные латинские написания фамилии автора.

    Порядок слов в источниках разный и не подчиняется одному правилу:
        «Байрамкулова Диана»      — фамилия первая
        «Diana Bayramkulova»      — фамилия последняя
        «Pham Phuong Nam»         — фамилия первая, имён два
        «Kokorekin Vladimir …»    — фамилия первая
        «V.G. Yankova»            — инициалы, затем фамилия
        «Feldman N.B.»            — фамилия, затем инициалы
    Поэтому кандидатом считается КАЖДОЕ содержательное слово, а пара
    ru↔en выбирается по наибольшему совпадению. Ошибка «взяли первое
    слово» приводила к тому, что один человек попадал в список дважды:
    отдельно кириллицей и отдельно латиницей.
    """
    out: list[str] = []
    for key in ("name_ru", "name_en"):
        nm = a.get(key)
        if not nm:
            continue
        for tok in re.findall(r"[A-Za-zА-Яа-яЁё\-]{2,}", nm):
            lat = _translit(tok) if re.search(r"[а-яё]", tok.lower()) else tok.lower()
            if lat and lat not in out:
                out.append(lat)
    return out


def _has_initials(a: dict) -> bool:
    """Есть ли в записи имени НАСТОЯЩИЕ инициалы (однобуквенные токены).

    Нужно разделить два случая:
        «Бобкова Н.В.»         — инициалы есть, сравнивать их осмысленно;
        «Diana Bayramkulova»   — инициалов нет, а первые буквы слов
                                 сравнивать нельзя: «Байрамкулова Диана»
                                 даёт {B, D}, «Diana Bayramkulova» — {D, B},
                                 пересечение есть, но это совпадение ни о чём
                                 не говорит, а ложный штраф мешает слиянию.
    """
    for key in ("name_ru", "name_en"):
        nm = a.get(key)
        if not nm:
            continue
        toks = re.findall(r"[A-Za-zА-Яа-яЁё]+", nm)
        if any(len(t) == 1 for t in toks):
            return True
    return False


def _initials_latin(a: dict) -> set[str]:
    """Множество первых букв всех слов имени в латинице.

    Множество, а не одна буква: нам важно не «угадать инициал», а увидеть,
    что он ВООБЩЕ присутствует. Для «Diana Bayramkulova» это {D, B}.
    """
    out: set[str] = set()
    for key in ("name_ru", "name_en"):
        nm = a.get(key)
        if not nm:
            continue
        for tok in re.findall(r"[A-Za-zА-Яа-яЁё]+", nm):
            out.add(_translit(tok[0]).upper()[:1])
    return out


def _initial(a: dict) -> str:
    """Первый инициал в ЛАТИНИЦЕ.

    Русская «Е» и латинская «E» — разные символы: если их не привести к
    одной азбуке, инициалы «не совпадают», и верная пара отвергается.
    """
    for nm in (a.get("name_ru"), a.get("name_en")):
        if nm:
            _s, ini = _split_name(nm)
            if ini:
                # ТОЛЬКО первая буква. Раньше возвращался весь транслит:
                # «Я» → «YA» против латинского «Y» — инициалы «не совпадали»,
                # пара Грибова/gribova отвергалась, человек задваивался.
                # Транслитерируем один символ и берём его первый знак:
                # «Я» → «Ya» → «Y», «Y» → «Y». Совпадает.
                return _translit(ini[0]).upper()[:1]
    return ""


def merge_authors_by_person(
    ru_authors: list[dict], en_authors: list[dict]
) -> tuple[list[dict], list[str]]:
    """Сливает два списка авторов одного проекта по ЛЮДЯМ, а не по позициям.

    Возвращает (объединённый список, флаги).
    """
    flags: list[str] = []
    if not ru_authors:
        return list(en_authors), flags
    if not en_authors:
        flags.append("en_team_missing")
        return list(ru_authors), flags

    pairs: list[tuple[float, int, int]] = []
    for i, ru in enumerate(ru_authors):
        ru_cands = _surname_candidates(ru)
        ru_ini = _initials_latin(ru)
        if not ru_cands:
            continue
        for j, en in enumerate(en_authors):
            en_cands = _surname_candidates(en)
            en_ini = _initials_latin(en)
            if not en_cands:
                continue
            # Сравниваем КАЖДОЕ слово с КАЖДЫМ и берём лучшее совпадение:
            # так находится пара «Байрамкулова» ↔ «Bayramkulova», хотя в
            # латинской записи фамилия стоит второй.
            best = 0.0
            for rs in ru_cands:
                for es in en_cands:
                    best = max(best, difflib.SequenceMatcher(None, rs, es).ratio())
            # Общий инициал — сильный признак. Отсутствие общего инициала
            # ослабляет пару, но не отменяет: в источниках инициалы бывают
            # только в одной из версий.
            # Инициалы сравниваем, только если они реально есть хотя бы
            # в одной записи: иначе «общая буква» — случайность.
            if (ru_ini and en_ini) and (_has_initials(ru) or _has_initials(en)):
                best += 0.35 if (ru_ini & en_ini) else -0.45
            pairs.append((best, i, j))

    pairs.sort(reverse=True)
    assigned_ru: dict[int, int] = {}
    used_en: set[int] = set()
    for score, i, j in pairs:
        if i in assigned_ru or j in used_en:
            continue
        if score < 0.62:          # ниже порога — считаем, что это разные люди
            continue
        assigned_ru[i] = j
        used_en.add(j)

    merged: list[dict] = []
    for i, ru in enumerate(ru_authors):
        rec = dict(ru)
        if i in assigned_ru:
            en = en_authors[assigned_ru[i]]
            rec["name_en"] = en.get("name_en")
            rec["position_en"] = en.get("position_en")
            rec["role_en"] = en.get("role_en")
            if not rec.get("initials"):
                rec["initials"] = en.get("initials")
        else:
            # русская запись без пары: латинского имени нет — не выдумываем
            if rec.get("name_en") is None:
                flags.append("en_name_not_matched")
        merged.append(rec)

    # англичане, которым не нашлось пары, добавляются, а не теряются
    for j, en in enumerate(en_authors):
        if j not in used_en:
            extra = dict(en)
            extra["added_from_review"] = extra.get("added_from_review", False)
            merged.append(extra)
            flags.append("en_only_author")

    return merged, flags


def _drop_name_fragments(authors: list[dict], lang: str) -> list[dict]:
    """Убирает «авторов», которые на самом деле — часть другого ФИО.

    Разные шаги разбора смотрят на текст независимо, и одно длинное имя
    попадает в результат дважды: целиком («Pham Phuong Nam») и осколком
    («Phuong Nam»). Проверять каждый шаг по отдельности ненадёжно —
    шагов пять, и они добавлялись в разное время. Поэтому чистим результат
    один раз, в конце: если ВСЕ слова короткой записи содержатся в более
    длинной записи того же проекта, короткая — осколок.

    Отбрасываем только при полном вхождении: «Иванов И.И.» и «Иванов П.С.» —
    разные люди, общее слово «Иванов» их не склеивает.
    """
    def words_of(a: dict) -> set[str]:
        nm = a.get("name_en") or a.get("name_ru") or ""
        # инициалы вроде «N.N.» в слова не берём — это не отличительный признак
        return {
            w for w in re.findall(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]{1,}", nm)
        }

    key_field = "name_en" if lang == "en" else "name_ru"
    kept: list[dict] = []
    for a in authors:
        aw = words_of(a)
        if not aw:
            kept.append(a)
            continue
        fragment = False
        for b in authors:
            if a is b:
                continue
            bw = words_of(b)
            if len(bw) > len(aw) and aw <= bw:
                fragment = True
                break
        if not fragment:
            kept.append(a)
    return kept


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
                # Объединяем авторов ru и en ПО ЛЮДЯМ, а не по номеру в списке.
                # Старое слияние по индексу ломается, как только списки
                # разной длины: фамилии сдвигаются на человека.
                if lang == "ru":
                    rec["authors"] = authors
                else:
                    if not rec["authors"]:
                        rec["authors"] = authors
                    else:
                        rec["authors"], mflags = merge_authors_by_person(
                            rec["authors"], authors
                        )
                        for f in mflags:
                            if f not in flags:
                                flags.append(f)
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
