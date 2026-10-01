#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Применение ответов заказчика (data/reviews.json) к данным проектов.

Зачем отдельный модуль. Ответы — РУЧНОЙ файл, данные — генерируемые.
Если писать ответы прямо в data_report.md, они исчезнут при следующей
пересборке (этот файл генерируется). Поэтому:

    data/reviews.json   ← правит человек
            ↓  apply_reviews()
    data/projects.json  ← пересобирается скриптом

Поддерживаемые действия (поле action в ответе):

    add_author        — добавить авторов, названных заказчиком вручную
    set_lead          — отметить руководителя по фамилии
    accepted          — данные верны, претензий нет: снимаем флаги разбора
    mark_todo         — заказчик вынес вопрос в TODO: помечаем отдельно
    recheck_parser    — заказчик дал эталонное число авторов:
                        если разбор разошёлся с ним на любом языке,
                        ставим флаг, но НЕ подгоняем данные молча
    parse_publications_from_results
                      — публикации лежат в разделе «Основные научные
                        результаты»: берём их оттуда
    info              — пояснение, ни на что не влияет

Модуль возвращает новый список авторов/публикаций и набор добавочных
флагов. Он НЕ переписывает данные «на глазок»: там, где уверенности нет,
ставится флаг для отчёта.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"


def load_reviews() -> dict:
    """Читает ответы заказчика. Отсутствие файла — не ошибка."""
    path = DATA / "reviews.json"
    if not path.exists():
        return {"answers": []}
    return json.loads(path.read_text(encoding="utf-8"))


def index_by_project(reviews: dict) -> dict[str, list[dict]]:
    """Раскладывает ответы по проектам: 'dept/slug' → [ответы]."""
    out: dict[str, list[dict]] = {}
    for a in reviews.get("answers", []):
        proj = a.get("project")
        if proj:
            out.setdefault(proj, []).append(a)
    return out


def _mk_author_from_name(name: str, lang: str) -> dict:
    """Собирает запись автора из ФИО, написанного заказчиком.

    ФИО может быть с отчеством («Кокорекин Владимир Алексеевич») или с
    инициалами («Боков Д.О.»). Инициалы вычисляем, только если уверены.
    """
    name = " ".join(name.split())
    parts = name.split()

    # инициалы: из второй и третьей части, если они начинаются с заглавной
    initials = ""
    if len(parts) >= 2:
        collected = []
        for p in parts[1:]:
            if p and p[0].isupper():
                collected.append(f"{p[0]}.")
            elif p and p[0].isalpha() and len(p) <= 3 and "." in p:
                collected.append(p)
            else:
                break
        initials = "".join(collected)

    if lang == "ru":
        name_ru, name_en = name, None
    else:
        name_ru, name_en = None, name

    return {
        "name_ru": name_ru,
        "name_en": name_en,
        "initials": initials or None,
        "position_ru": None,
        "position_en": None,
        "role_ru": "не указана",
        "role_en": None,
        "photo": None, "profile_url": None, "orcid": None, "scopus_id": None,
        "researcher_id": None, "elibrary_id": None, "google_scholar": None,
        "researchgate": None,
        "is_lead": False,
        "_added_from_review": True,   # служебная метка: автор дописан вручную
    }


def apply_reviews(
    project_key: str,
    authors: list[dict],
    publications: list[dict],
    flags: list[str],
    answers: list[dict],
    results_section: str | None = None,
) -> tuple[list[dict], list[dict], list[str]]:
    """Применяет ответы к одному проекту.

    project_key — 'dept/slug', нужен только для сообщений.
    Возвращает (авторы, публикации, флаги).
    """
    authors = list(authors)
    publications = list(publications)
    flags = list(flags)

    for a in answers:
        action = a.get("action")

        # --- данные подтверждены: снимаем флаги разбора ---------------------
        if action == "accepted":
            for f in ("author_parsing_uncertain", "no_lead_marked"):
                if f in flags:
                    flags.remove(f)

        # --- авторы дописаны заказчиком вручную -----------------------------
        elif action == "add_author":
            for nm in a.get("authors", []) or []:
                rec = _mk_author_from_name(nm, "ru")
                # не дублируем: сверяем по фамилии
                surname = nm.split()[0]
                if any((au.get("name_ru") or au.get("name_en") or "").startswith(surname)
                       for au in authors):
                    continue
                authors.append(rec)
            if "no_authors" in flags:
                flags.remove("no_authors")

        # --- руководитель назван по фамилии ---------------------------------
        elif action == "set_lead":
            lead = (a.get("lead") or a.get("answer") or "").strip()
            if lead:
                for au in authors:
                    nm = au.get("name_ru") or au.get("name_en") or ""
                    if nm.startswith(lead):
                        au["is_lead"] = True
                        if au["role_ru"] in ("не указана", "участник"):
                            au["role_ru"] = "руководитель"
                if any(au.get("is_lead") for au in authors):
                    if "no_lead_marked" in flags:
                        flags.remove("no_lead_marked")

        # --- заказчик дал эталон: сверяем, но не подгоняем ------------------
        elif action == "recheck_parser":
            expected = a.get("expected_authors")
            if isinstance(expected, int) and expected != len(authors):
                if "author_count_mismatch" not in flags:
                    flags.append("author_count_mismatch")

        # --- публикации лежат в разделе «результаты» ------------------------
        elif action == "parse_publications_from_results":
            if results_section and not publications:
                from importlib.util import module_from_spec, spec_from_file_location
                spec = spec_from_file_location(
                    "build_data", REPO / "tools" / "build_data.py")
                bd = module_from_spec(spec)
                spec.loader.exec_module(bd)
                found, pflags = bd.parse_publications(results_section)
                if found:
                    publications = found
                    if "no_publications" in flags:
                        flags.remove("no_publications")
            elif results_section and publications:
                # публикации уже разобраны — считаем вопрос закрытым
                if "no_publications" in flags:
                    flags.remove("no_publications")

        # --- вопрос вынесен в TODO ------------------------------------------
        elif action == "mark_todo":
            if "todo_from_reviewer" not in flags:
                flags.append("todo_from_reviewer")

        # --- просто пояснение ------------------------------------------------
        elif action == "info":
            pass

    return authors, publications, flags


def design_notes(reviews: dict) -> list[str]:
    """Замечания заказчика по оформлению — уходят в отчёт отдельным блоком."""
    out = []
    for a in reviews.get("answers", []):
        note = a.get("design_note")
        if note:
            out.append(f"[{a.get('project') or 'общее'}] {note}")
    return out


if __name__ == "__main__":
    r = load_reviews()
    n = len(r.get("answers", []))
    by_proj = index_by_project(r)
    print(f"Ответов загружено: {n}")
    print(f"Проектов затронуто: {len(by_proj)}")
    from collections import Counter
    print("Действия:", dict(Counter(a.get("action") for a in r.get("answers", []))))
    notes = design_notes(r)
    if notes:
        print(f"\nЗамечаний по оформлению: {len(notes)}")
        for x in notes:
            print("  -", x[:150])
