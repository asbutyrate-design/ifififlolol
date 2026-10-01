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
    "authors_collective_only": "Команда записана коллективно («коллектив кафедры»), без имён",
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
    apply_reviews_mod = _load(REPO / "tools" / "apply_reviews.py", "apply_reviews_mod")
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
    add("Привязка вопросов и ответов — **по названию проекта** (кафедра · slug), "
        "а не по номеру: нумерация пересчитывается при каждой сборке, "
        "поэтому номер как идентификатор не годится.")
    add("")

    # ответы заказчика нужны уже здесь — чтобы не задавать повторно то,
    # на что ответ уже получен
    reviews_now = {}
    _rv = DATA / "reviews.json"
    if _rv.exists():
        reviews_now = json.loads(_rv.read_text(encoding="utf-8"))
    # Ключи ответов в reviews.json записаны как «afkh/spray-quality-aerosols»
    # (латиница-слаг), а в флагах проекты обозначены как «АФКХ · spray-quality-aerosols».
    # Приводим оба вида к одному: «dept-slug/slug».
    abbr2slug = {d["abbr"]: d["slug"] for d in doc.get("departments", []) if d.get("abbr")}

    def _flag_key(label: str) -> str:
        """К единому виду «dept-slug/slug». Принимает обе записи:
        «АФКХ · spray-quality-aerosols» и «АФКХ/spray-quality-aerosols»."""
        s = label.strip()
        m = re.match(r"^(\S+)\s*·\s*(\S+)$", s)
        if m:
            abbr, slug = m.group(1), m.group(2)
        elif "/" in s:
            abbr, slug = s.split("/", 1)
        else:
            return s
        return f"{abbr2slug.get(abbr, abbr)}/{slug}"

    answered_keys = set()
    for a in (reviews_now.get("answers") or []):
        proj = a.get("project")
        if not proj or a.get("action") in (None, "info"):
            continue
        answered_keys.add(proj if "/" in proj else _flag_key(proj))

    qnum = 0
    q_items: list[tuple[int, str]] = []
    skipped_answered = 0

    def _add_q(text: str, key: str) -> None:
        """Добавляет вопрос, если по проекту ещё нет ответа."""
        nonlocal qnum, skipped_answered
        if key in answered_keys:
            skipped_answered += 1
            return
        qnum += 1
        q_items.append((qnum, text))

    for x in by_flag["no_authors"]:
        _add_q(f"**{x}** — прислать состав команды (ФИО, должность, роль)?", _flag_key(x))
    for x in by_flag["no_publications"]:
        _add_q(f"**{x}** — прислать список публикаций или подтвердить, что их нет?", _flag_key(x))
    for x in by_flag["broken_doi_in_source"]:
        _add_q(f"**{x}** — подтвердить правильный DOI для публикации, "
               f"разорванной пробелом в источнике?", _flag_key(x))
    for x in by_flag["author_parsing_uncertain"]:
        _add_q(f"**{x}** — проверить состав команды вручную: разбор ненадёжен?", _flag_key(x))
    for x in by_flag["author_count_mismatch"]:
        _add_q(f"**{x}** — состав команды расходится с указанным вами числом, уточните?", _flag_key(x))
    for abbr, slug, nru, nen in contradictions:
        _add_q(f"**{abbr} · {slug}** — почему в русской версии {nru} "
               f"авторов, а в английской {nen}? Кто должен быть в списке?", _flag_key(f"{abbr}/{slug}"))
    for dep, p in projects:
        if "no_lead_marked" not in p["review_flags"]:
            continue
        ru = p["team_raw_ru"] or ""
        if re.search(r"заведующ|руководител|head of|project lead", ru, re.I):
            _add_q(f"**{dep['abbr']} · {p['slug']}** — кто руководитель проекта?",
                   _flag_key(f"{dep['abbr']}/{p['slug']}"))

    if q_items:
        for n, text in q_items:
            add(f"{n}. {text}")
    else:
        add("**Открытых вопросов нет** — по всем замечаниям получены ответы.")
    add("")
    add(f"Всего открытых вопросов: **{len(q_items)}**.")
    add("")
    if skipped_answered:
        add(f"Вопросов снято как уже отвеченные: {skipped_answered}. Подробности — в разделе 14.")
        add("")

    # 14. ответы заказчика
    # ВАЖНО: ответы живут в data/reviews.json (ручной файл), а не в этом
    # отчёте. Отчёт генерируется заново при каждом запуске, поэтому
    # вписанные сюда руками ответы исчезали бы. Здесь они только
    # ПОКАЗЫВАЮТСЯ — правятся в reviews.json.
    add("## 14. Ответы заказчика")
    add("")
    add("Ответы хранятся в `data/reviews.json` и подставляются при каждой сборке. "
        "Этот отчёт генерируется, правки в нём не сохраняются.")
    add("")

    reviews_data = {}
    rv_path = DATA / "reviews.json"
    if rv_path.exists():
        reviews_data = json.loads(rv_path.read_text(encoding="utf-8"))

    if reviews_data:
        add(f"Получено: `{reviews_data.get('received_at', '—')}`. "
            f"Ответов: **{len(reviews_data.get('answers', []))}**.")
        add("")
        add("| № | Проект | Ответ | Что сделано |")
        add("|---|---|---|---|")
        ACTION_RU = {
            "add_author": "автор добавлен",
            "set_lead": "отмечен руководитель",
            "accepted": "принято без правок",
            "mark_todo": "вынесено в TODO для кафедры",
            "recheck_parser": "дано эталонное число авторов, разбор перепроверен",
            "parse_publications_from_results": "публикации взяты из раздела «результаты»",
            "info": "принято к сведению",
        }
        for a in reviews_data.get("answers", []):
            n = a.get("item", "—")
            raw = a.get("answer") or ""
            # в таблице не место переносам строк и вертикальным чертам
            ans = raw.replace("|", "/").replace("\n", " ").strip()
            proj = a.get("project") or "общее"
            done = ACTION_RU.get(a.get("action"), a.get("action") or "")
            add(f"| {n} | {proj} | {ans[:300]} | {done} |")
        add("")

        # отдельно — то, что заказчик просил уточнить у кафедры
        todos = [a for a in reviews_data.get("answers", []) if a.get("action") == "mark_todo"]
        if todos:
            add("### Вынесено в TODO (кафедра разбирается сама)")
            add("")
            for a in todos:
                add(f"- **{a.get('project')}** — {a.get('answer', '')}")
            add("")
        # замечания по оформлению — это требования к страницам,
        # а не к данным: выводим отдельно, чтобы учли на ЭТАПЕ 5–6.
        notes = apply_reviews_mod.design_notes(reviews_data)
        if notes:
            add("### Замечания по оформлению — учесть при вёрстке страниц")
            add("")
            for x in notes:
                add(f"- {x}")
            add("")

        # общие ответы, влияющие на сборку (шаблон URL страницы сотрудника, ответ О4)
        infos = [a for a in reviews_data.get("answers", [])
                 if a.get("action") == "info" and (a.get("url_template") or a.get("note"))]
        if infos:
            add("### Сведения для сборки")
            add("")
            for a in infos:
                line = f"- **{a.get('item')}** — {a.get('answer', '')}"
                if a.get("url_template"):
                    line += f" · шаблон: `{a['url_template']}`"
                if a.get("note"):
                    line += f" · {a['note']}"
                add(line)
            add("")

    else:
        add("`data/reviews.json` не найден — ответы ещё не получены.")
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
