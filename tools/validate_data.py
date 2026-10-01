#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Валидация /data/projects.json против /data/schema.json.

Проверяет:
  • структуру и типы по схеме;
  • внутреннюю согласованность данных (это схема выразить не может):
      – slug уникален среди проектов И среди кафедр;
      – langs_available совпадает с наличием url_* и source_file_*;
      – url строится ровно по meta.url_scheme и meta.base_url;
      – counts в meta совпадают с фактическим содержимым;
      – флаги из review_flags входят в разрешённый список схемы;
      – у каждого проекта есть хотя бы один язык;
      – парность: у проекта с двумя языками адреса отличаются только языком.

Запуск:  python3 tools/validate_data.py
Код выхода: 0 — валидно, 1 — есть ошибки.
"""

from __future__ import annotations

import difflib
import importlib.util
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    schema = load("schema.json")
    doc = load("projects.json")

    # --- 1. Формальная проверка по схеме (если доступна jsonschema) ---------
    try:
        import jsonschema  # type: ignore

        try:
            jsonschema.validate(doc, schema)
            print("jsonschema: структура соответствует схеме")
        except jsonschema.ValidationError as e:
            path = "/".join(str(p) for p in e.absolute_path)
            errors.append(f"схема: {path}: {e.message}")
    except ImportError:
        warnings.append("модуль jsonschema не установлен — проверена только логика")

    # --- 2. Логические проверки ---------------------------------------------
    meta = doc["meta"]
    scheme = meta["url_scheme"]
    base = meta["base_url"].rstrip("/")

    allowed_flags = set(
        schema["$defs"]["project"]["properties"]["review_flags"]["items"]["enum"]
    )

    seen_dept_slugs: set[str] = set()
    seen_project_slugs: set[str] = set()

    counts = {
        "departments": 0, "projects": 0, "projects_with_both_langs": 0,
        "projects_ru_only": 0, "projects_en_only": 0, "pages": 0, "qr_codes": 0,
    }

    for dep in doc["departments"]:
        dslug = dep["slug"]
        if dslug in seen_dept_slugs:
            errors.append(f"дубликат slug кафедры: {dslug}")
        seen_dept_slugs.add(dslug)

        if dep["status"] == "ready" and not dep["projects"]:
            warnings.append(f"кафедра {dslug}: status=ready, но проектов нет")

        for p in dep["projects"]:
            slug = p["slug"]
            # slug не должен повторяться даже между кафедрами: он часть адреса
            if slug in seen_project_slugs:
                errors.append(f"дубликат slug проекта: {slug} (кафедра {dslug})")
            seen_project_slugs.add(slug)

            langs = p["langs_available"]
            if not langs:
                errors.append(f"{dslug}/{slug}: langs_available пуст")

            # url_* и source_file_* должны соответствовать langs_available
            for lang in ("ru", "en"):
                has_url = bool(p[f"url_{lang}"])
                has_src = bool(p[f"source_file_{lang}"])
                if lang in langs:
                    if not has_url:
                        errors.append(f"{dslug}/{slug}: нет url_{lang} при наличии языка")
                    if not has_src:
                        errors.append(f"{dslug}/{slug}: нет source_file_{lang} при наличии языка")
                    expected = base + scheme.format(
                        lang=lang, dept=dslug, slug=slug,
                        suffix=doc["meta"].get("lang_suffix", {}).get(lang, lang),
                    )
                    if p[f"url_{lang}"] != expected:
                        errors.append(
                            f"{dslug}/{slug}: url_{lang} не совпадает с шаблоном\n"
                            f"      есть:  {p[f'url_{lang}']}\n"
                            f"      ждём:  {expected}"
                        )
                else:
                    if has_url:
                        errors.append(f"{dslug}/{slug}: url_{lang} есть, но языка нет")

            # парность адресов: отличаются только сегментом языка
            if len(langs) == 2:
                suff = doc["meta"].get("lang_suffix", {"ru": "ru", "en": "en"})
                ru = p["url_ru"].replace(f'_{suff["ru"]}', "_{suffix}")
                en = p["url_en"].replace(f'_{suff["en"]}', "_{suffix}")
                if ru != en:
                    errors.append(f"{dslug}/{slug}: адреса ru/en расходятся не только языком")

            # флаги
            for f in p["review_flags"]:
                if f not in allowed_flags:
                    errors.append(f"{dslug}/{slug}: неизвестный флаг {f}")

            # счётчики
            counts["projects"] += 1
            n = len(langs)
            counts["pages"] += n
            counts["qr_codes"] += n
            if n == 2:
                counts["projects_with_both_langs"] += 1
            elif langs == ["ru"]:
                counts["projects_ru_only"] += 1
            elif langs == ["en"]:
                counts["projects_en_only"] += 1

        if dep["projects"]:
            counts["departments"] += 1

    declared = meta.get("counts", {})
    for k, v in counts.items():
        if declared.get(k) != v:
            errors.append(
                f"meta.counts.{k}: заявлено {declared.get(k)}, фактически {v}"
            )

    # --- Перекрёстная проверка: сборщик ↔ схема -------------------------------
    # Флаги, которые build_data.py МОЖЕТ выдать, обязаны быть объявлены в схеме.
    # Так рассинхрон («сборщик придумал новый флаг, схема о нём не знает»)
    # обнаруживается сразу, а не через этап.
    # Сканируем ВСЕ модули, которые могут добавить флаг: сборщик данных и
    # прослойку ответов заказчика. Иначе новый флаг из apply_reviews проскочит.
    emitted: set[str] = set()
    for mod_name in ("build_data.py", "apply_reviews.py"):
        mod_path = REPO / "tools" / mod_name
        if mod_path.exists():
            src = mod_path.read_text(encoding="utf-8")
            emitted |= set(re.findall(r'flags\.append\("([a-z_]+)"\)', src))
    undeclared = sorted(emitted - allowed_flags)
    if undeclared:
        errors.append(
            "build_data.py выдаёт флаги, не объявленные в схеме: "
            + ", ".join(undeclared)
        )
    else:
        print(f"сборщик ↔ схема: все {len(emitted)} флагов объявлены")

    # --- Регрессия: слияние авторов ru↔en --------------------------------
    # Проверяем, что у каждого автора русская и латинская записи — ОДИН человек.
    # Именно здесь был дефект: слияние по номеру в списке сдвигало фамилии
    # (Завадич Е.А. получала фамилию Тращенковой). Молчаливый сдвиг страшнее
    # падения, поэтому проверка обязательная и постоянная.
    spec_bd = importlib.util.spec_from_file_location(
        "build_data_for_validation", REPO / "tools" / "build_data.py"
    )
    bd_mod = importlib.util.module_from_spec(spec_bd)
    spec_bd.loader.exec_module(bd_mod)

    # Пары могут писаться латиницей по-разному: «Фам Фыонг» → «Pham Phuong»
    # даёт всего 67% по буквам. Поэтому абсолютный порог ненадёжен и даёт
    # ложные тревоги на ВЕРНЫХ парах. Проверяем иначе — по существу ошибки:
    # убеждаемся, что для каждого автора именно его партнёр является лучшим
    # совпадением в проекте. Если да — склейка осмысленна. Если лучшим
    # оказался ЧУЖОЙ человек, значит записи перепутаны — вот это ошибка.
    def best_match_score(ru_nm: str, en_nm: str) -> float:
        ru_c = bd_mod._surname_candidates({"name_ru": ru_nm, "name_en": None})
        en_c = bd_mod._surname_candidates({"name_ru": None, "name_en": en_nm})
        return max(
            (difflib.SequenceMatcher(None, a, b).ratio() for a in ru_c for b in en_c),
            default=0.0,
        )

    mismatched: list[str] = []
    checked_pairs = 0
    for dep in doc["departments"]:
        for p in dep["projects"]:
            paired = [a for a in p["authors"] if a.get("name_ru") and a.get("name_en")]
            if not paired:
                continue
            en_names = [a["name_en"] for a in p["authors"] if a.get("name_en")]
            for a in paired:
                checked_pairs += 1
                own = best_match_score(a["name_ru"], a["name_en"])
                # лучший вариант среди всех: не мог ли этот русский автор
                # «подойти» кому-то другому сильнее?
                stolen_by = [
                    en for en in en_names
                    if en != a["name_en"] and best_match_score(a["name_ru"], en) > own + 0.02
                ]
                if stolen_by:
                    mismatched.append(
                        f"{dep['slug']}/{p['slug']}: {a['name_ru']} ↔ {a['name_en']} "
                        f"({own:.0%}), но сильнее подходит {stolen_by[0]!r} "
                        f"({best_match_score(a['name_ru'], stolen_by[0]):.0%})"
                    )

    if mismatched:
        errors.append(
            f"автор склеен с чужим человеком ({len(mismatched)}):\n      "
            + "\n      ".join(mismatched[:10])
        )
    else:
        print(f"авторы ru↔en: {checked_pairs} пар проверено, чужих совпадений нет")

    # --- Решения ЭТАПА 4: домен, протокол, суффикс, коллизии ----------------
    # Эти проверки закрепляют решения заказчика от 2026-10-01, чтобы схема
    # не «сползла» обратно при будущих правках.
    if not base.startswith("https://"):
        errors.append(
            f"base_url без https: {base}; редирект включён, в QR должен идти https"
        )
    if "{slug}" not in scheme or "{suffix}" not in scheme:
        errors.append(
            f"url_scheme не соответствует решению заказчика: {scheme}. "
            f"Ожидается '/{{slug}}_{{suffix}}'"
        )
    suff = doc["meta"].get("lang_suffix") or {}
    if suff.get("ru") != "rus" or suff.get("en") != "eng":
        errors.append(f"lang_suffix должен быть rus/eng, а не {suff}")

    # коллизии с уже существующими страницами сайта — иначе 404 или перезапись
    existing_path = DATA / "existing-pages.json"
    if existing_path.exists():
        taken = {
            e.strip("/")
            for e in json.loads(existing_path.read_text(encoding="utf-8"))["pages"]
        }
        clashes = [
            path
            for dep in doc["departments"]
            for p in dep["projects"]
            for lang in ("ru", "en")
            if p.get(f"url_{lang}")
            for path in [p[f"url_{lang}"].split("://", 1)[1].split("/", 1)[-1].strip("/")]
            if path in taken
        ]
        if clashes:
            errors.append(
                "адреса заняты существующими страницами сайта: " + ", ".join(clashes)
            )
        else:
            print(f"коллизии с сайтом: {len(taken)} существующих страниц проверено, свободно")

    # длина адреса и версия QR: следим, чтобы код не перескочил на v6
    def qr_version(data: str, ecc_caps: dict[int, int]) -> int:
        n = len(data.encode())
        for ver_, cap in ecc_caps.items():
            if n <= cap:
                return ver_
        return 41

    # ёмкость одного сегмента при ECC M, байты
    CAP_M = {1:14,2:26,3:42,4:62,5:84,6:106,7:122,8:152,9:180,10:213,11:251,
             12:287,13:331,14:362,15:412,16:450,17:504,18:560,19:624,20:666,
             21:711,22:779,23:857,24:911,25:997,26:1059,27:1125,28:1190,
             29:1264,30:1370,31:1452,32:1538,33:1628,34:1722,35:1809,36:1911,
             37:1989,38:2099,39:2213,40:2331}
    versions = [
        qr_version(p[f"url_{lang}"], CAP_M)
        for dep in doc["departments"]
        for p in dep["projects"]
        for lang in ("ru", "en")
        if p.get(f"url_{lang}")
    ]
    if versions:
        worst = max(versions)
        if worst > 5:
            errors.append(
                f"адрес перерос пятую версию QR (максимум v{worst}): "
                f"код станет плотнее, а на экране мельче. Сократите slug."
            )
        else:
            longest = max(
                (p[f"url_{lang}"] for dep in doc["departments"] for p in dep["projects"]
                 for lang in ("ru", "en") if p.get(f"url_{lang}")),
                key=len,
            )
            print(
                f"QR: все {len(versions)} адресов пятой версии "
                f"(самый длинный {len(longest)} симв., запас {106 - len(longest)} до v6)"
            )

    # --- Итог --------------------------------------------------------------- -------------------------------------------------------------
    # --- Проверка: все поля проектов объявлены в схеме ------------------
    declared_props = set(
        schema["$defs"]["project"]["properties"].keys()
    )
    seen_props: set[str] = set()
    for dep in doc["departments"]:
        for p in dep["projects"]:
            seen_props |= set(p.keys())
    undeclared_props = sorted(seen_props - declared_props)
    if undeclared_props:
        errors.append(
            "в данных есть поля, не объявленные в схеме: "
            + ", ".join(undeclared_props)
        )
    else:
        print(f"поля проектов: все {len(seen_props)} объявлены в схеме")

    for w in warnings:
        print(f"ПРЕДУПРЕЖДЕНИЕ: {w}")
    if errors:
        print(f"\nОШИБОК: {len(errors)}", file=sys.stderr)
        for e in errors[:50]:
            print("  -", e, file=sys.stderr)
        if len(errors) > 50:
            print(f"  ... и ещё {len(errors) - 50}", file=sys.stderr)
        return 1

    print(f"\nOK: projects.json валиден")
    print(f"  кафедр:  {counts['departments']}")
    print(f"  проектов: {counts['projects']} "
          f"(обоих языков: {counts['projects_with_both_langs']})")
    print(f"  страниц: {counts['pages']}  QR: {counts['qr_codes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
