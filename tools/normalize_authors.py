#!/usr/bin/env python3
"""
ЭТАП 11.3: Нормализация инициалов и степеней авторов (исправленная версия).

Задачи:
1. Инициалы: А.А. → А. А. (добавить пробел после каждой точки)
2. Степени: к.ф.н. → к. фарм. н., к.б.н. → к. б. н., к.х.н. → к. х. н.
3. Исходные team_raw_ru / team_raw_en остаются неизменными
"""

import json
import re
from pathlib import Path

# Маппинг неправильных степеней на правильные
DEGREE_FIXES = [
    # Кандидат фармацевтических наук
    (r"к\.ф\.н\.", "к. фарм. н."),
    (r"к\.ф\.н", "к. фарм. н."),
    (r"к\. ф\. н\.", "к. фарм. н."),
    
    # Кандидат биологических наук
    (r"к\.б\.н\.", "к. б. н."),
    (r"к\.б\.н", "к. б. н."),
    
    # Кандидат химических наук
    (r"к\.х\.н\.", "к. х. н."),
    (r"к\.х\.н", "к. х. н."),
    
    # Доктор фармацевтических наук
    (r"д\.ф\.н\.", "д. фарм. н."),
    (r"д\.ф\.н", "д. фарм. н."),
    
    # Доктор биологических наук
    (r"д\.б\.н\.", "д. б. н."),
    (r"д\.б\.н", "д. б. н."),
    
    # Доктор химических наук
    (r"д\.х\.н\.", "д. х. н."),
    (r"д\.х\.н", "д. х. н."),
]

def normalize_initials(text):
    """Нормализует инициалы: А.А. → А. А."""
    if not text:
        return text
    
    # Русские инициалы: А.А. → А. А.
    text = re.sub(r"([А-ЯЁ])\.([А-ЯЁ])\.", r"\1. \2.", text)
    
    # Английские инициалы: A.A. → A. A.
    text = re.sub(r"([A-Z])\.([A-Z])\.", r"\1. \2.", text)
    
    # Фамилия И.О. → Фамилия И. О.
    text = re.sub(r"([А-ЯЁ]+)\s+([А-ЯЁ])\.([А-ЯЁ])\.", r"\1 \2. \3.", text)
    
    return text

def normalize_degrees(text):
    """Нормализует степени: к.ф.н. → к. фарм. н."""
    if not text:
        return text
    
    for pattern, replacement in DEGREE_FIXES:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    
    # Очищаем дублирующиеся пробелы
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def main():
    repo = Path(__file__).resolve().parent.parent
    projects_file = repo / "data" / "projects.json"
    
    print("Читаю data/projects.json...")
    with open(projects_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print("Нормализую авторов...")
    
    stats = {
        "initials_fixed": 0,
        "degrees_fixed": 0,
        "names_fixed": 0,
    }
    
    for dept in data.get("departments", []):
        for proj in dept.get("projects", []):
            for author in proj.get("authors", []):
                # Нормализуем name_ru
                if author.get("name_ru"):
                    before = author["name_ru"]
                    author["name_ru"] = normalize_initials(author["name_ru"])
                    if before != author["name_ru"]:
                        stats["initials_fixed"] += 1
                
                # Нормализуем name_en
                if author.get("name_en"):
                    before = author["name_en"]
                    author["name_en"] = normalize_initials(author["name_en"])
                    if before != author["name_en"]:
                        stats["initials_fixed"] += 1
                
                # Нормализуем degree_ru
                if author.get("degree_ru"):
                    before = author["degree_ru"]
                    author["degree_ru"] = normalize_degrees(author["degree_ru"])
                    if before != author["degree_ru"]:
                        stats["degrees_fixed"] += 1
                
                # Нормализуем degree_en
                if author.get("degree_en"):
                    before = author["degree_en"]
                    author["degree_en"] = normalize_degrees(author["degree_en"])
                    if before != author["degree_en"]:
                        stats["degrees_fixed"] += 1
    
    print(f"Сохраняю обновлённый data/projects.json...")
    with open(projects_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    
    print(f"\n✓ Нормализация завершена!")
    print(f"  • Инициалов исправлено: {stats['initials_fixed']}")
    print(f"  • Степеней исправлено: {stats['degrees_fixed']}")

if __name__ == "__main__":
    main()
