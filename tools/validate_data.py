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
                    expected = base + scheme.format(lang=lang, dept=dslug, slug=slug)
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
                ru = p["url_ru"].replace("/ru/", "/{lang}/")
                en = p["url_en"].replace("/en/", "/{lang}/")
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
