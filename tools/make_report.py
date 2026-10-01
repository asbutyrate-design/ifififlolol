#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ЭТАП 3. Генерация docs/data_report.md из data/projects.json.

Отчёт НЕ пишется руками: все числа и списки собираются из данных, поэтому
после правки источников он пересчитывается одной командой и не расходится
с действительностью.

Запуск:  python3 tools/make_report.py
"""

from __future__ import annotations

import importlib.util
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
DOCS = REPO / "docs"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def norm_title(s: str | None) -> str:
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


FLAG_HUMAN = {
    "no_lead_marked": "Руководитель не указан в источнике",
    "no_authors": "Команда проекта отсутствует в источнике",
    "no_publications": "Публикации не указаны",
    "broken_doi_in_source": "DOI разорван в источнике — как ссылку не отдаём",
    "team_label_missing": "Метка «Команда проекта» отсутствует, автор указан без неё",
    "author_parsing_uncertain": "Разбор авторов ненадёжен",
    "title_multiline": "Название проекта разбито на строки",
    "question_in_source": "В тексте источника есть вопрос/пометка",
    "external_data_expected": "Ожидаются данные извне",
}


def main() -> int:
    bd = _load(REPO / "tools" / "build_data.py", "bd")
    doc = json.loads((DATA / "projects.json").read_text(encoding="utf-8"))

    projects = [
        (dep, p) for dep in doc["departments"] for p in dep["projects"]
    ]
    counts = doc["meta"]["counts"]

    # ---- вычисления из данных -------------------------------------------
    flag_counter: Counter = Counter()
    by_flag: dict[str, list[str]] = defaultdict(list)
    for dep, p in projects:
        for f in p["review_flags"]:
            flag_counter[f] += 1
            by_flag[f].append(f"{dep['abbr']} · {p['slug']}")

    no_en = [f"{d['abbr']} · {p['slug']}" for d, p in projects if "en" not in p["langs_available"]]
    no_ru = [f"{d['abbr']} · {p['slug']}" for d, p in projects if "ru" not in p["langs_available"]]

    # противоречия ru↔en по числу авторов
    contradictions = []
    for dep, p in projects:
        ru_a, _ = bd.parse_authors(p["team_raw_ru"], "ru")
        en_a, _ = bd.parse_authors(p["team_raw_en"], "en")
        if len(ru_a) != len(en_a):
            contradictions.append((dep["abbr"], p["slug"], len(ru_a), len(en_a)))

    # авторы без фото
    authors_total = 0
    for _, p in projects:
        authors_total += len(p["authors"])

    # дубликаты названий
    seen: dict[str, list[str]] = defaultdict(list)
    for dep, p in projects:
        seen[norm_title(p["title_ru"])].append(f"{dep['abbr']} · {p['slug']}")
    dups = {k: v for k, v in seen.items() if len(v) > 1}

    # таблицы в извлечённом тексте
    tables = [
        f"{f.parent.name}/{f.name}"
        for f in sorted((REPO / "content-md").glob("*/*.md"))
        if re.search(r"(?m)^\s*\|", f.read_text(encoding="utf-8"))
    ]

    pubs_total = sum(len(p["publications"]) for _, p in projects)
    pubs_with_url = sum(
        1 for _, p in projects for pub in p["publications"] if pub["url"]
    )

    # ---- сборка markdown -------------------------------------------------
    L: list[str] = []
    add = L.append

    add("# ЭТАП 3: ОТЧЁТ О КАЧЕСТВЕ ДАННЫХ")
    add("")
    add("> Файл сгенерирован скриптом `tools/make_report.py` из `data/projects.json`.")
    add("> Руками не правится — правки затрутся при следующем пересчёте.")
    add("> После исправления источников запустите `python3 tools/make_report.py` заново.")
    add("")
    add(f"Дата сборки: `{doc['meta']['generated_at']}`")
    add("")

    # 1. сводка
    add("## 1. Сводка")
    add("")
    add("| Показатель | Значение |")
    add("|---|---|")
    add(f"| Кафедр с проектами | {counts['departments']} |")
    add(f"| Проектов | {counts['projects']} |")
    add(f"| — с обоими языками | {counts['projects_with_both_langs']} |")
    add(f"| — только по-русски | {counts['projects_ru_only']} |")
    add(f"| — только по-английски | {counts['projects_en_only']} |")
    add(f"| Страниц к публикации | {counts['pages']} |")
    add(f"| QR-кодов | {counts['qr_codes']} |")
    add(f"| Авторов разобрано | {authors_total} |")
    add(f"| Публикаций разобрано | {pubs_total} (из них со ссылкой {pubs_with_url}) |")
    add("")

    add("### Пометки по данным")
    add("")
    add("| Пометка | Проектов | Что означает |")
    add("|---|---|---|")
    for flag, n in flag_counter.most_common():
        add(f"| `{flag}` | {n} | {FLAG_HUMAN.get(flag, flag)} |")
    add("")

    # 2. без английской версии
    add("## 2. Проекты без английской версии")
    add("")
    if no_en:
        add(f"Таких проектов: **{len(no_en)}**.")
        add("")
        for x in no_en:
            add(f"- {x}")
        add("")
        add("> Следствие для QR: английский QR для этих проектов **не генерируется**, "
            "потому что вести ему некуда. Решение фиксируется в ЭТАПЕ 9.")
    else:
        add("**Таких проектов нет.** У всех проектов есть и русская, и английская версия.")
        add("")
        add("Каждый проект получает **два** QR-кода и **две** страницы. Для сравнения, "
            "если бы переводы отсутствовали, для каждого такого проекта пришлось бы "
            "решить отдельно: не выпускать английский QR вовсе либо вести его на "
            "русскую страницу с явным уведомлением. Сейчас этот сценарий не нужен, "
            "но порядок на него описан в ЭТАПЕ 9 — он может понадобиться при "
            "добавлении новых проектов.")
    add("")

    add("## 3. Проекты без русской версии")
    add("")
    if no_ru:
        for x in no_ru:
            add(f"- {x}")
    else:
        add("**Таких проектов нет.**")
    add("")

    # 4. без авторов
    add("## 4. Проекты без авторов")
    add("")
    if by_flag["no_authors"]:
        add(f"Проектов: **{len(by_flag['no_authors'])}**. В источнике команда не "
            "перечислена вовсе либо перечислена без метки, и разобрать её не удалось.")
        add("")
        add("| Проект | Что именно нужно |")
        add("|---|---|")
        for x in by_flag["no_authors"]:
            add(f"| {x} | Прислать состав команды: ФИО, должность, роль |")
        add("")
        add("Люди не потеряны молча: дословный текст команды сохранён в поле "
            "`team_raw_*` соответствующего проекта, его можно проверить.")
    else:
        add("**Таких проектов нет.**")
    add("")

    # 5. без руководителя
    add("## 5. Проекты, где руководитель не помечен")
    add("")
    if by_flag["no_lead_marked"]:
        add(f"Проектов: **{len(by_flag['no_lead_marked'])}** из {counts['projects']}. "
            "Это **не ошибка разбора**: в исходных файлах роль «руководитель проекта» "
            "почти нигде не проставлена явно.")
        add("")
        add("На странице бейдж «руководитель» показывает только там, где роль "
            "действительно указана. У остальных авторов бейджа не будет — это "
            "честнее, чем назначать руководителя догадкой.")
        add("")
        add("Полный список проектов этой группы — в `data/projects.json` по пометке "
            "`no_lead_marked`. Здесь перечисляю только те, где роль, скорее всего, "
            "есть в источнике, но записана нестандартно:")
        add("")
        for dep, p in projects:
            if "no_lead_marked" not in p["review_flags"]:
                continue
            ru = p["team_raw_ru"] or ""
            if re.search(r"заведующ|руководител|head of|project lead", ru, re.I):
                add(f"- {dep['abbr']} · {p['slug']} — в тексте есть указание на "
                    f"руководящую должность, подтвердите, кто руководитель")
        add("")
    else:
        add("**Таких проектов нет.**")
    add("")

    # 6. без публикаций
    add("## 6. Проекты без публикаций")
    add("")
    if by_flag["no_publications"]:
        add(f"Проектов: **{len(by_flag['no_publications'])}**.")
        add("")
        add("| Проект | Что именно нужно |")
        add("|---|---|")
        for x in by_flag["no_publications"]:
            add(f"| {x} | Прислать список публикаций либо подтвердить, что их нет |")
    else:
        add("**Таких проектов нет.**")
    add("")

    # 7. DOI
    add("## 7. Проблемы со ссылками на публикации")
    add("")
    if by_flag["broken_doi_in_source"]:
        add(f"Проектов: **{len(by_flag['broken_doi_in_source'])}**.")
        add("")
        for dep, p in projects:
            if "broken_doi_in_source" not in p["review_flags"]:
                continue
            add(f"**{dep['abbr']} · {p['slug']}**")
            add("")
            for pub in p["publications"]:
                if pub["doi"] is None and re.search(r"10\.\d{4}", pub["raw"]):
                    add(f"- в источнике: `{pub['raw'][:200]}`")
            add("")
        add("Причина: в исходном файле DOI разорван пробелом, из-за чего ссылка "
            "не открывается. Строка публикации сохранена целиком, но кликабельной "
            "ссылки у неё нет. Нужно подтвердить правильный DOI.")
    else:
        add("**Проблем нет.**")
    add("")

    # 8. ненадёжный разбор
    add("## 8. Ненадёжный разбор авторов")
    add("")
    if by_flag["author_parsing_uncertain"]:
        add(f"Проектов: **{len(by_flag['author_parsing_uncertain'])}**.")
        add("")
        for dep, p in projects:
            if "author_parsing_uncertain" not in p["review_flags"]:
                continue
            add(f"**{dep['abbr']} · {p['slug']}**")
            add("")
            add(f"- источник: `{(p['team_raw_ru'] or p['team_raw_en'] or '')[:250]}`")
            add(f"- разобрано авторов: {len(p['authors'])}")
            add("")
    else:
        add("**Таких проектов нет.**")
    add("")

    # 9. противоречия языков
    add("## 9. Противоречия между языковыми версиями")
    add("")
    if contradictions:
        add("Число авторов в русской и английской версиях одного проекта не совпадает:")
        add("")
        add("| Кафедра | Проект | Авторов в RU | Авторов в EN |")
        add("|---|---|---|---|")
        for abbr, slug, nru, nen in contradictions:
            add(f"| {abbr} | {slug} | {nru} | {nen} |")
        add("")
        add("На публикуемых страницах это не ошибка вёрстки, а расхождение "
            "содержания: на русской странице может быть человек, которого нет на "
            "английской. Нужно подтвердить, кто должен быть в списке.")
    else:
        add("**Расхождений нет:** число авторов в русской и английской версиях "
            "совпадает у всех проектов.")
    add("")

    # 10. фото
    add("## 10. Фотографии авторов")
    add("")
    add(f"Разобрано авторов: **{authors_total}**. Ни у одного нет фотографии — "
        "в исходных файлах фотографий нет и ссылок на них тоже.")
    add("")
    add("Пока на страницах будут монограммы — инициалы на фирменном цвете. "
        "Это осознанное решение, а не заглушка: монограмма выглядит как элемент "
        "дизайна и не требует доработки, если фото так и не появятся.")
    add("")
    add("Если фотографии будут переданы, требования такие:")
    add("")
    add("- формат: квадратный кадр, лицо по центру;")
    add("- размер: от 400×400 px (на странице показываются 40–56 px);")
    add("- имя файла: фамилия латиницей и инициалы, например `Zhukova_AA.jpg`;")
    add("- куда положить: в репозиторий, каталог `assets/avatars/`;")
    add("- одно фото на человека, **не** два: лицо не зависит от языка страницы.")
    add("")
    add("Автоматически скачивать фото из интернета я не буду, даже если найду "
        "совпадение по фамилии: это чужие изображения и чужие права.")
    add("")

    # 11. дубликаты
    add("## 11. Дубликаты")
    add("")
    if dups:
        for k, v in dups.items():
            add(f"- проекты с одинаковым названием: {', '.join(v)}")
    else:
        add("**Дубликатов нет.** Названия всех проектов уникальны.")
    add("")

    # 12. таблицы
    add("## 12. Таблицы в исходных данных")
    add("")
    if tables:
        add("Найдены таблицы в извлечённом тексте: " + ", ".join(f"`{t}`" for t in tables))
    else:
        add("**Таблиц нет.** Ни один исходный файл не содержит табличной разметки, "
            "поэтому проблем с «склеенными колонками» не возникло.")
    add("")

    # 13. вопросы
    add("## 13. Вопросы заказчику")
    add("")
    add("Формат ответа: «да» / «нет» / «вот данные». Номера совпадают с блоком "
        "ответов в конце файла.")
    add("")

    qnum = 0
    q_items: list[tuple[int, str]] = []

    for x in by_flag["no_authors"]:
        qnum += 1
        q_items.append((qnum, f"**{x}** — прислать состав команды (ФИО, должность, роль)?"))
    for x in by_flag["no_publications"]:
        qnum += 1
        q_items.append((qnum, f"**{x}** — прислать список публикаций или подтвердить, что их нет?"))
    for x in by_flag["broken_doi_in_source"]:
        qnum += 1
        q_items.append((qnum, f"**{x}** — подтвердить правильный DOI для публикации, "
                              f"разорванной пробелом в источнике?"))
    for x in by_flag["author_parsing_uncertain"]:
        qnum += 1
        q_items.append((qnum, f"**{x}** — проверить состав команды вручную: разбор ненадёжен?"))
    for abbr, slug, nru, nen in contradictions:
        qnum += 1
        q_items.append((qnum, f"**{abbr} · {slug}** — почему в русской версии {nru} "
                              f"авторов, а в английской {nen}? Кто должен быть в списке?"))
    for dep, p in projects:
        if "no_lead_marked" not in p["review_flags"]:
            continue
        ru = p["team_raw_ru"] or ""
        if re.search(r"заведующ|руководител|head of|project lead", ru, re.I):
            qnum += 1
            q_items.append((qnum, f"**{dep['abbr']} · {p['slug']}** — кто руководитель проекта?"))

    if q_items:
        for n, text in q_items:
            add(f"{n}. {text}")
    else:
        add("Вопросов нет — данные полные.")
    add("")
    add(f"Всего вопросов: **{len(q_items)}**.")
    add("")

    # 14. ответы заказчика
    add("## 14. Ответы заказчика")
    add("")
    add("Заполняется прямо здесь, через веб-интерфейс GitHub: нажмите карандаш "
        "«Edit this file», впишите ответы, внизу страницы «Commit changes».")
    add("")
    add("| № | Проект | Ответ |")
    add("|---|---|---|")
    for n, text in q_items:
        proj = re.search(r"\*\*(.+?)\*\*", text)
        add(f"| {n} | {proj.group(1) if proj else '—'} |  |")
    add("")
    add("### Общие вопросы")
    add("")
    add("| № | Вопрос | Ответ |")
    add("|---|---|---|")
    add(f"| О1 | Кафедра Химии: подтверждаете, что файлы будут присланы? |  |")
    add(f"| О2 | Кафедра ФП: ожидаются ещё 2 проекта — когда будут файлы? |  |")
    add(f"| О3 | Фотографии авторов будут переданы? |  |")
    add(f"| О4 | Есть ли страницы сотрудников на сайте университета, "
        f"на которые можно ссылаться? |  |")
    add("")

    report = "\n".join(L) + "\n"
    DOCS.mkdir(exist_ok=True)
    out = DOCS / "data_report.md"
    out.write_text(report, encoding="utf-8")

    print(f"Записано: {out.relative_to(REPO)}")
    print(f"  флагов: {len(flag_counter)} видов, всего пометок {sum(flag_counter.values())}")
    print(f"  проектов без авторов: {len(by_flag['no_authors'])}")
    print(f"  без публикаций: {len(by_flag['no_publications'])}")
    print(f"  противоречий ru/en: {len(contradictions)}")
    print(f"  вопросов заказчику: {len(q_items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
