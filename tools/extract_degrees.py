#!/usr/bin/env python3
"""
ЭТАП 11.2: Извлечение учёных степеней и звания из position_* в отдельные поля.

Это миграционный скрипт. Он:
1. Читает data/projects.json
2. Для каждого автора в position_ru и position_en:
   - Извлекает учёную степень (д.ф.н., к.ф.н., k.х.н., и т.д.)
   - Извлекает учёное звание (профессор, доцент, член-корреспондент РАН)
   - Оставляет в position только должность
3. Добавляет новые поля: degree_ru, degree_en, academic_title_ru, academic_title_en
4. Сохраняет обновлённый projects.json

Исходный текст хранится в team_raw_ru / team_raw_en и не теряется.
"""

import json
import re
from pathlib import Path

# Маркеры учёных степеней
DEGREES_RU = [
    (r"\bд\.?\s*?ф\.?\s*?н\.?(?:\s+|$)", "д.ф.н."),
    (r"\bк\.?\s*?ф\.?\s*?н\.?(?:\s+|$)", "к.ф.н."),
    (r"\bд\.?\s*?х\.?\s*?н\.?(?:\s+|$)", "д.х.н."),
    (r"\bк\.?\s*?х\.?\s*?н\.?(?:\s+|$)", "к.х.н."),
    (r"\bд\.?\s*?б\.?\s*?н\.?(?:\s+|$)", "д.б.н."),
    (r"\bк\.?\s*?б\.?\s*?н\.?(?:\s+|$)", "к.б.н."),
]

DEGREES_EN = [
    (r"\bDoctor\s+of\s+\w+\s+Sciences\b", "Doctor of Sciences"),
    (r"\bCandidatе\s+of\s+\w+\s+Sciences\b", "Candidate of Sciences"),
    (r"\bPhD\b", "PhD"),
    (r"\bM\.?S\.?\b", "M.S."),
]

# Маркеры учёных званий
TITLES_RU = [
    (r"\bпрофессор\b|\bпроф\.?\b", "профессор"),
    (r"\bдоцент\b", "доцент"),
    (r"\bассистент\b", "ассистент"),
    (r"\bчл\.?-?\s*корр\.?", "член-корреспондент РАН"),
    (r"\bакадемик\b", "академик РАН"),
]

TITLES_EN = [
    (r"\bProfessor\b|\bProf\.?\b", "Professor"),
    (r"\b(Associate|Assoc\.?)\s+Professor\b", "Associate Professor"),
    (r"\bAssistant\s+Professor\b", "Assistant Professor"),
    (r"\bAssistant\b", "Assistant"),
    (r"\bCorresponding\s+Member\b", "Corresponding Member of RAS"),
    (r"\bAcademician\b", "Academician of RAS"),
]

# Должности (то, что остаётся в position)
POSITIONS_RU = [
    r"\bзаведующий\s+кафедр\w*\b",
    r"\bзав\.?\s+кафедр\w*\b",
    r"\bзав\.?\s+лаб\w+\b",
    r"\bзав\.?\s+отдел\w+\b",
    r"\bруководитель\s+группы\b",
    r"\bnаучный\s+сотрудник\b",
    r"\bстарший\s+преподаватель\b",
    r"\bпреподаватель\b",
    r"\bсоискатель\b",
]

POSITIONS_EN = [
    r"\bHead\s+of\s+Department\b",
    r"\bHead\s+of\s+Laboratory\b",
    r"\bLead\s+Researcher\b",
    r"\bSenior\s+Researcher\b",
    r"\bResearch\s+Associate\b",
    r"\bResearcher\b",
    r"\bLecturer\b",
]

def extract_marker(text, markers, case_insensitive=True):
    """Извлекает первый найденный маркер из текста и возвращает его."""
    if not text:
        return None
    
    text_search = text.lower() if case_insensitive else text
    for pattern, replacement in markers:
        match = re.search(pattern, text_search, re.IGNORECASE if case_insensitive else 0)
        if match:
            return replacement
    
    return None

def clean_position(text, to_remove):
    """Удаляет степени и звания из position, оставляя только должность."""
    if not text:
        return ""
    
    result = text
    
    # Удаляем все маркеры степеней и звания
    for pattern, _ in to_remove:
        result = re.sub(pattern, " ", result, flags=re.IGNORECASE)
    
    # Очищаем от дублей пробелов и пунктуации
    result = re.sub(r'\s+', ' ', result).strip()
    result = re.sub(r',\s*,', ',', result).strip()
    result = re.sub(r',\s*$', '', result).strip()
    
    return result

def migrate_authors(projects_data):
    """Обновляет авторов: извлекает степени и звания."""
    
    for dept in projects_data.get("departments", []):
        for project in dept.get("projects", []):
            for author in project.get("authors", []):
                # Русский
                if author.get("position_ru"):
                    degree = extract_marker(author["position_ru"], DEGREES_RU)
                    title = extract_marker(author["position_ru"], TITLES_RU)
                    
                    author["degree_ru"] = degree
                    author["academic_title_ru"] = title
                    
                    # Очищаем position
                    to_remove = DEGREES_RU + TITLES_RU
                    author["position_ru"] = clean_position(author["position_ru"], to_remove)
                
                # Английский
                if author.get("position_en"):
                    degree = extract_marker(author["position_en"], DEGREES_EN)
                    title = extract_marker(author["position_en"], TITLES_EN)
                    
                    author["degree_en"] = degree
                    author["academic_title_en"] = title
                    
                    # Очищаем position
                    to_remove = DEGREES_EN + TITLES_EN
                    author["position_en"] = clean_position(author["position_en"], to_remove)
    
    return projects_data

def main():
    repo = Path(__file__).resolve().parent.parent
    projects_file = repo / "data" / "projects.json"
    
    print(f"Читаю {projects_file}...")
    with open(projects_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    print("Мигрирую авторов...")
    data = migrate_authors(data)
    
    print(f"Сохраняю обновлённый {projects_file}...")
    with open(projects_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    
    print("✓ Готово!")

if __name__ == "__main__":
    main()
