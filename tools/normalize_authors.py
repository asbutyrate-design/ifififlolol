#!/usr/bin/env python3
"""
ЭТАП 11.3: Нормализация написания инициалов, степеней и сокращений.

Исправляет:
1. Неправильные сокращения степеней:
   - к.ф.н. → к. фарм. н. (физика → фармацевтика)
   - д.ф.н. → д. фарм. н.
2. Добавляет пробелы в инициалах и сокращениях:
   - А.А. → А. А.
   - к.б.н. → к. б. н.
   - проф. → проф.
   - доц. → доц.

Все замены логированы, ничего не теряется.
"""

import json
import re
from pathlib import Path
from collections import defaultdict

# Маппинг неправильных степеней на правильные
DEGREE_CORRECTIONS = {
    # Неправильные физические науки → правильные фармацевтические
    r'\bк\.ф\.н\.': 'к. фарм. н.',
    r'\bд\.ф\.н\.': 'д. фарм. н.',
    
    # Добавляем пробелы в уже правильных сокращениях
    r'\bк\.х\.н\.': 'к. х. н.',
    r'\bд\.х\.н\.': 'д. х. н.',
    r'\bк\.б\.н\.': 'к. б. н.',
    r'\bд\.б\.н\.': 'д. б. н.',
    
    # Звания и должности с пробелами
    r'\bпроф\.': 'проф.',  # Уже есть точка, просто проверка
    r'\bдоц\.': 'доц.',
    r'\bас\.': 'ас.',
}

# Функция для нормализации инициалов: А.А. → А. А.
def normalize_initials(text):
    """Добавляет пробелы в инициалы: А.А. → А. А."""
    if not text:
        return text
    
    # Ищем паттерн: [Буква].[Буква]. и добавляем пробел
    # Например: В.Г. → В. Г.
    text = re.sub(r'([А-Яа-яЁё])\.([А-Яа-яЁё])\.', r'\1. \2.', text)
    
    # Английские инициалы тоже
    text = re.sub(r'([A-Z])\.([A-Z])\.', r'\1. \2.', text)
    
    return text

def normalize_degrees(text):
    """Исправляет сокращения степеней и добавляет пробелы."""
    if not text:
        return text
    
    result = text
    
    # Применяем коррекции в порядке важности
    # Сначала исправляем неправильные степени
    result = re.sub(r'\bк\.ф\.н\.', 'к. фарм. н.', result, flags=re.IGNORECASE)
    result = re.sub(r'\bд\.ф\.н\.', 'д. фарм. н.', result, flags=re.IGNORECASE)
    
    # Затем добавляем пробелы в остальные степени (если их ещё нет)
    # к.х.н. → к. х. н. (только если ещё не нормализовано)
    if 'к.х.н.' in result or 'К.Х.Н.' in result:
        result = re.sub(r'\bк\.х\.н\.', 'к. х. н.', result, flags=re.IGNORECASE)
    
    if 'д.х.н.' in result or 'Д.Х.Н.' in result:
        result = re.sub(r'\bд\.х\.н\.', 'д. х. н.', result, flags=re.IGNORECASE)
    
    if 'к.б.н.' in result or 'К.Б.Н.' in result:
        result = re.sub(r'\bк\.б\.н\.', 'к. б. н.', result, flags=re.IGNORECASE)
    
    if 'д.б.н.' in result or 'Д.Б.Н.' in result:
        result = re.sub(r'\bд\.б\.н\.', 'д. б. н.', result, flags=re.IGNORECASE)
    
    return result

def normalize_text(text):
    """Комплексная нормализация текста."""
    if not text:
        return text
    
    # Сначала инициалы
    text = normalize_initials(text)
    
    # Затем степени
    text = normalize_degrees(text)
    
    return text

def migrate_authors(projects_data):
    """Обновляет авторов: нормализует инициалы и степени."""
    
    stats = {
        'names_fixed': 0,
        'degrees_fixed': 0,
        'titles_fixed': 0,
        'positions_fixed': 0,
        'corrections': defaultdict(int),
    }
    
    for dept in projects_data.get("departments", []):
        for project in dept.get("projects", []):
            for author in project.get("authors", []):
                # Нормализуем name_ru
                if author.get("name_ru"):
                    original = author["name_ru"]
                    author["name_ru"] = normalize_text(author["name_ru"])
                    if original != author["name_ru"]:
                        stats['names_fixed'] += 1
                
                # Нормализуем name_en (инициалы)
                if author.get("name_en"):
                    original = author["name_en"]
                    author["name_en"] = normalize_initials(author["name_en"])
                    if original != author["name_en"]:
                        stats['names_fixed'] += 1
                
                # Нормализуем degree_ru
                if author.get("degree_ru"):
                    original = author["degree_ru"]
                    author["degree_ru"] = normalize_degrees(author["degree_ru"])
                    if original != author["degree_ru"]:
                        stats['degrees_fixed'] += 1
                        stats['corrections'][f"{original} → {author['degree_ru']}"] += 1
                
                # Нормализуем academic_title_ru (вдруг там что-то с точками)
                if author.get("academic_title_ru"):
                    original = author["academic_title_ru"]
                    author["academic_title_ru"] = normalize_text(author["academic_title_ru"])
                    if original != author["academic_title_ru"]:
                        stats['titles_fixed'] += 1
                
                # Нормализуем position_ru
                if author.get("position_ru"):
                    original = author["position_ru"]
                    author["position_ru"] = normalize_text(author["position_ru"])
                    if original != author["position_ru"]:
                        stats['positions_fixed'] += 1
                
                # Нормализуем position_en
                if author.get("position_en"):
                    original = author["position_en"]
                    author["position_en"] = normalize_initials(author["position_en"])
                    if original != author["position_en"]:
                        stats['positions_fixed'] += 1
    
    return projects_data, stats

def main():
    repo = Path(__file__).resolve().parent.parent
    projects_file = repo / "data" / "projects.json"
    
    print(f"Читаю {projects_file}...")
    with open(projects_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    print("Нормализую инициалы и степени...")
    data, stats = migrate_authors(data)
    
    print(f"\nРезультаты нормализации:")
    print(f"  Имён исправлено: {stats['names_fixed']}")
    print(f"  Степеней исправлено: {stats['degrees_fixed']}")
    print(f"  Звания исправлены: {stats['titles_fixed']}")
    print(f"  Должностей исправлено: {stats['positions_fixed']}")
    
    if stats['corrections']:
        print(f"\nОсновные замены степеней:")
        for correction, count in sorted(stats['corrections'].items(), key=lambda x: -x[1])[:10]:
            print(f"  {correction}: {count} раз")
    
    print(f"\nСохраняю обновлённый {projects_file}...")
    with open(projects_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    
    print("✓ Готово!")

if __name__ == "__main__":
    main()
