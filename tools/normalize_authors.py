#!/usr/bin/env python3
"""
ЭТАП 11.3: Нормализация инициалов и степеней авторов.

Правила:
1. Инициалы: А.А. → А. А. (пробел после каждой точки)
2. Степени: к.ф.н. → к. фарм. н. (правильное название + пробелы)
3. Применяется к name_ru, degree_ru, initials
"""

import json
import re
from pathlib import Path

# Маппинг неправильных степеней на правильные
DEGREE_CORRECTIONS = {
    # Физические науки (НЕПРАВИЛЬНО для нас)
    r'\bк\.?\s*?ф\.?\s*?н\.?': 'к. фарм. н.',      # к.ф.н. → к. фарм. н.
    r'\bд\.?\s*?ф\.?\s*?н\.?': 'д. фарм. н.',      # д.ф.н. → д. фарм. н.
    
    # Химические (правильные, но нужны пробелы)
    r'\bк\.?\s*?х\.?\s*?н\.?': 'к. х. н.',
    r'\bд\.?\s*?х\.?\s*?н\.?': 'д. х. н.',
    
    # Биологические (правильные, но нужны пробелы)
    r'\bк\.?\s*?б\.?\s*?н\.?': 'к. б. н.',
    r'\bд\.?\s*?б\.?\s*?н\.?': 'д. б. н.',
}

def normalize_initials(text):
    """Нормализует инициалы: А.А. → А. А."""
    if not text:
        return text
    
    # Паттерн: буква, точка, буква, точка (опционально ещё буквы)
    # А.А. → А. А.
    # А.Б. → А. Б.
    # И.О. → И. О.
    
    def replace_initials(match):
        initials = match.group(0)
        # Добавляем пробел после каждой точки, кроме последней
        result = re.sub(r'([A-ЯЁ])\.(?=[A-ЯЁ]\.)', r'\1. ', initials, flags=re.IGNORECASE)
        return result
    
    # Ищем паттерны вида Х.Х. или Х.Х.Х.
    text = re.sub(r'[A-ЯЁ]\.[A-ЯЁ]\.(?:[A-ЯЁ]\.)?', replace_initials, text, flags=re.IGNORECASE)
    
    return text

def normalize_degrees(text):
    """Нормализует степени: к.ф.н. → к. фарм. н., к.б.н. → к. б. н."""
    if not text:
        return text
    
    result = text
    for pattern, replacement in DEGREE_CORRECTIONS.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    return result

def normalize_author(author):
    """Нормализует все поля автора."""
    
    # Нормализуем initials
    if author.get('initials'):
        author['initials'] = normalize_initials(author['initials'])
    
    # Нормализуем name_ru (может содержать инициалы)
    if author.get('name_ru'):
        author['name_ru'] = normalize_initials(author['name_ru'])
    
    # Нормализуем name_en (может содержать инициалы латиницей, но пробелы)
    if author.get('name_en'):
        # Латинские инициалы: J.K. → J. K.
        author['name_en'] = re.sub(
            r'([A-Z])\.(?=[A-Z]\.)',
            r'\1. ',
            author['name_en']
        )
    
    # Нормализуем degree_ru
    if author.get('degree_ru'):
        author['degree_ru'] = normalize_degrees(author['degree_ru'])
    
    # Нормализуем degree_en (может быть, но обычно PhD или Doctor of Sciences)
    # Пока не трогаем, так как формат английских степеней другой
    
    # Нормализуем academic_title_ru (обычно не содержит аббревиатур, но на всякий)
    if author.get('academic_title_ru'):
        author['academic_title_ru'] = normalize_initials(author['academic_title_ru'])
    
    # Нормализуем position_ru
    if author.get('position_ru'):
        author['position_ru'] = normalize_degrees(author['position_ru'])
        author['position_ru'] = normalize_initials(author['position_ru'])
    
    return author

def main():
    repo = Path(__file__).resolve().parent.parent
    projects_file = repo / "data" / "projects.json"
    
    print(f"Читаю {projects_file}...")
    with open(projects_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    changes = {
        "initials_fixed": 0,
        "degrees_corrected": 0,
        "name_ru_fixed": 0,
    }
    
    print("Нормализую авторов...")
    for dept in data.get("departments", []):
        for project in dept.get("projects", []):
            for author in project.get("authors", []):
                old_initials = author.get('initials')
                old_degree = author.get('degree_ru')
                old_name_ru = author.get('name_ru')
                
                # Нормализуем
                author = normalize_author(author)
                
                # Считаем изменения
                if old_initials and old_initials != author.get('initials'):
                    changes["initials_fixed"] += 1
                if old_degree and old_degree != author.get('degree_ru'):
                    changes["degrees_corrected"] += 1
                if old_name_ru and old_name_ru != author.get('name_ru'):
                    changes["name_ru_fixed"] += 1
    
    print(f"Сохраняю обновлённый {projects_file}...")
    with open(projects_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    
    print("✓ Нормализация завершена!")
    print()
    print("Изменения:")
    print(f"  • Инициалов исправлено: {changes['initials_fixed']}")
    print(f"  • Степеней исправлено: {changes['degrees_corrected']}")
    print(f"  • Имён (name_ru) исправлено: {changes['name_ru_fixed']}")

if __name__ == "__main__":
    main()
