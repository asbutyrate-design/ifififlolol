#!/usr/bin/env python3
"""
Диагностика полей авторов в projects.json.
Ищет смешение степеней, должностей и звания в name и position.
Не меняет данные, только анализирует и выводит примеры аномалий.
"""

import json
import re
from collections import defaultdict
from pathlib import Path

# Маркеры, по которым ловим степени и звания
DEGREE_MARKERS = [
    r'\bд\.?\s*ф\.?\s*н\.?',      # д.ф.н., д. ф. н., дфн, д.ф.н
    r'\bк\.?\s*ф\.?\s*н\.?',      # к.ф.н.
    r'\bд\.?\s*х\.?\s*н\.?',      # д.х.н.
    r'\bк\.?\s*х\.?\s*н\.?',      # к.х.н.
    r'\bбакалавр\b',
    r'\bмагистр\b',
    r'\bкандидат\b',
    r'\bдоктор\b',
]

TITLE_MARKERS = [
    r'\bпрофессор\b',
    r'\bпроф\.?\b',
    r'\bчл\.?-корр\.?\b',         # членский корреспондент
]

POSITION_MARKERS = [
    r'\bдоцент\b',
    r'\bассистент\b',
    r'\bстарший\s+преподаватель\b',
    r'\bпреподаватель\b',
    r'\bзав\.?\s*кафедр\b',
    r'\bзаведующий\b',
    r'\bначальник\b',
    r'\bнаучный\s+сотрудник\b',
    r'\bсоискатель\b',
]

def contains_marker(text, markers):
    """Проверяет, есть ли маркеры в тексте."""
    if not text:
        return False
    text_lower = text.lower()
    for marker in markers:
        if re.search(marker, text_lower):
            return True
    return False

def analyze_name_format(name_ru, name_en):
    """Анализирует формат имени и возвращает тип."""
    formats = []
    
    if name_ru:
        # Ищем паттерны: "Фамилия И.О." vs "И.О. Фамилия" vs "Фамилия Имя Отчество"
        ru_lower = name_ru.lower()
        if re.match(r'^[А-Яа-яЁё]+\s+[А-ЯА-Я]\.\s*[А-ЯА-Я]\.?', name_ru):
            formats.append(("ru", "Фамилия И.О."))
        elif re.match(r'^[А-ЯА-Я]\.\s*[А-ЯА-Я]\.\s+[А-Яа-яЁё]+', name_ru):
            formats.append(("ru", "И.О. Фамилия"))
        else:
            formats.append(("ru", "другой"))
    
    if name_en:
        # "Surname I.I." vs "I.I. Surname" vs "Full Name"
        if re.match(r'^[A-Za-z]+\s+[A-Z]\.\s*[A-Z]\.?', name_en):
            formats.append(("en", "Surname I.I."))
        elif re.match(r'^[A-Z]\.\s*[A-Z]\.\s+[A-Za-z]+', name_en):
            formats.append(("en", "I.I. Surname"))
        else:
            formats.append(("en", "другой"))
    
    return formats

def diagnose(projects_path):
    """Запускает диагностику авторов."""
    
    with open(projects_path) as f:
        data = json.load(f)
    
    stats = {
        "total_authors": 0,
        "authors_with_degree_in_name_ru": [],
        "authors_with_degree_in_name_en": [],
        "authors_with_position_in_name_ru": [],
        "authors_with_position_in_name_en": [],
        "authors_with_title_in_name_ru": [],
        "authors_with_title_in_name_en": [],
        "name_formats": defaultdict(int),
        "position_contains_degree": [],
        "position_contains_title": [],
        "missing_position_ru": [],
        "missing_position_en": [],
        "missing_initials": [],
    }
    
    for dept in data.get("departments", []):
        for project in dept.get("projects", []):
            project_slug = project.get("slug", "unknown")
            dept_slug = dept.get("slug", "unknown")
            
            for author in project.get("authors", []):
                stats["total_authors"] += 1
                
                name_ru = author.get("name_ru", "")
                name_en = author.get("name_en", "")
                position_ru = author.get("position_ru", "")
                position_en = author.get("position_en", "")
                initials = author.get("initials", "")
                
                # Проверяем формат имён
                formats = analyze_name_format(name_ru, name_en)
                for lang, fmt in formats:
                    stats["name_formats"][f"{lang}:{fmt}"] += 1
                
                # Проверяем наличие маркеров в имени
                if contains_marker(name_ru, DEGREE_MARKERS):
                    stats["authors_with_degree_in_name_ru"].append({
                        "project": f"{dept_slug}/{project_slug}",
                        "name_ru": name_ru,
                        "position_ru": position_ru,
                    })
                
                if contains_marker(name_en, DEGREE_MARKERS):
                    stats["authors_with_degree_in_name_en"].append({
                        "project": f"{dept_slug}/{project_slug}",
                        "name_en": name_en,
                        "position_en": position_en,
                    })
                
                if contains_marker(name_ru, POSITION_MARKERS):
                    stats["authors_with_position_in_name_ru"].append({
                        "project": f"{dept_slug}/{project_slug}",
                        "name_ru": name_ru,
                        "position_ru": position_ru,
                    })
                
                if contains_marker(name_en, POSITION_MARKERS):
                    stats["authors_with_position_in_name_en"].append({
                        "project": f"{dept_slug}/{project_slug}",
                        "name_en": name_en,
                        "position_en": position_en,
                    })
                
                if contains_marker(name_ru, TITLE_MARKERS):
                    stats["authors_with_title_in_name_ru"].append({
                        "project": f"{dept_slug}/{project_slug}",
                        "name_ru": name_ru,
                        "position_ru": position_ru,
                    })
                
                if contains_marker(name_en, TITLE_MARKERS):
                    stats["authors_with_title_in_name_en"].append({
                        "project": f"{dept_slug}/{project_slug}",
                        "name_en": name_en,
                        "position_en": position_en,
                    })
                
                # Проверяем position на степени/звания
                if contains_marker(position_ru, DEGREE_MARKERS):
                    stats["position_contains_degree"].append({
                        "lang": "ru",
                        "project": f"{dept_slug}/{project_slug}",
                        "name_ru": name_ru,
                        "position_ru": position_ru,
                    })
                
                if contains_marker(position_en, DEGREE_MARKERS):
                    stats["position_contains_degree"].append({
                        "lang": "en",
                        "project": f"{dept_slug}/{project_slug}",
                        "name_en": name_en,
                        "position_en": position_en,
                    })
                
                if contains_marker(position_ru, TITLE_MARKERS):
                    stats["position_contains_title"].append({
                        "lang": "ru",
                        "project": f"{dept_slug}/{project_slug}",
                        "name_ru": name_ru,
                        "position_ru": position_ru,
                    })
                
                if contains_marker(position_en, TITLE_MARKERS):
                    stats["position_contains_title"].append({
                        "lang": "en",
                        "project": f"{dept_slug}/{project_slug}",
                        "name_en": name_en,
                        "position_en": position_en,
                    })
                
                # Проверяем пропущенные поля
                if not position_ru:
                    stats["missing_position_ru"].append({
                        "project": f"{dept_slug}/{project_slug}",
                        "name_ru": name_ru,
                    })
                
                if not position_en:
                    stats["missing_position_en"].append({
                        "project": f"{dept_slug}/{project_slug}",
                        "name_en": name_en,
                    })
                
                if not initials:
                    stats["missing_initials"].append({
                        "project": f"{dept_slug}/{project_slug}",
                        "name_ru": name_ru,
                        "name_en": name_en,
                    })
    
    return stats

def format_report(stats):
    """Форматирует отчёт для вывода."""
    
    report = []
    report.append("=" * 80)
    report.append("ДИАГНОСТИКА ПОЛЕЙ АВТОРОВ")
    report.append("=" * 80)
    report.append("")
    
    report.append(f"Всего авторов проанализировано: {stats['total_authors']}")
    report.append("")
    
    # Формат имён
    report.append("ФОРМАТЫ ИМЁН:")
    for fmt, count in sorted(stats["name_formats"].items()):
        report.append(f"  {fmt}: {count}")
    report.append("")
    
    # Степени в имени
    report.append(f"СТЕПЕНИ В ПОЛЕ name_ru: {len(stats['authors_with_degree_in_name_ru'])} авторов")
    for item in stats["authors_with_degree_in_name_ru"][:5]:
        report.append(f"  {item['project']}")
        report.append(f"    name_ru: {item['name_ru']}")
        report.append(f"    position_ru: {item['position_ru']}")
    if len(stats["authors_with_degree_in_name_ru"]) > 5:
        report.append(f"  ... и ещё {len(stats['authors_with_degree_in_name_ru']) - 5}")
    report.append("")
    
    report.append(f"СТЕПЕНИ В ПОЛЕ name_en: {len(stats['authors_with_degree_in_name_en'])} авторов")
    for item in stats["authors_with_degree_in_name_en"][:5]:
        report.append(f"  {item['project']}")
        report.append(f"    name_en: {item['name_en']}")
        report.append(f"    position_en: {item['position_en']}")
    if len(stats["authors_with_degree_in_name_en"]) > 5:
        report.append(f"  ... и ещё {len(stats['authors_with_degree_in_name_en']) - 5}")
    report.append("")
    
    # Должности в имени
    report.append(f"ДОЛЖНОСТИ В ПОЛЕ name_ru: {len(stats['authors_with_position_in_name_ru'])} авторов")
    for item in stats["authors_with_position_in_name_ru"][:5]:
        report.append(f"  {item['project']}")
        report.append(f"    name_ru: {item['name_ru']}")
        report.append(f"    position_ru: {item['position_ru']}")
    if len(stats["authors_with_position_in_name_ru"]) > 5:
        report.append(f"  ... и ещё {len(stats['authors_with_position_in_name_ru']) - 5}")
    report.append("")
    
    report.append(f"ДОЛЖНОСТИ В ПОЛЕ name_en: {len(stats['authors_with_position_in_name_en'])} авторов")
    for item in stats["authors_with_position_in_name_en"][:5]:
        report.append(f"  {item['project']}")
        report.append(f"    name_en: {item['name_en']}")
        report.append(f"    position_en: {item['position_en']}")
    if len(stats["authors_with_position_in_name_en"]) > 5:
        report.append(f"  ... и ещё {len(stats['authors_with_position_in_name_en']) - 5}")
    report.append("")
    
    # Звания в имени
    report.append(f"ЗВАНИЯ В ПОЛЕ name_ru: {len(stats['authors_with_title_in_name_ru'])} авторов")
    for item in stats["authors_with_title_in_name_ru"][:5]:
        report.append(f"  {item['project']}")
        report.append(f"    name_ru: {item['name_ru']}")
        report.append(f"    position_ru: {item['position_ru']}")
    if len(stats["authors_with_title_in_name_ru"]) > 5:
        report.append(f"  ... и ещё {len(stats['authors_with_title_in_name_ru']) - 5}")
    report.append("")
    
    report.append(f"ЗВАНИЯ В ПОЛЕ name_en: {len(stats['authors_with_title_in_name_en'])} авторов")
    for item in stats["authors_with_title_in_name_en"][:5]:
        report.append(f"  {item['project']}")
        report.append(f"    name_en: {item['name_en']}")
        report.append(f"    position_en: {item['position_en']}")
    if len(stats["authors_with_title_in_name_en"]) > 5:
        report.append(f"  ... и ещё {len(stats['authors_with_title_in_name_en']) - 5}")
    report.append("")
    
    # Степени и звания в position
    report.append(f"СТЕПЕНИ И ЗВАНИЯ В ПОЛЕ position_*: {len(stats['position_contains_degree']) + len(stats['position_contains_title'])} авторов")
    report.append(f"  (это может быть нормально, если position содержит полное описание)")
    
    for item in (stats["position_contains_degree"] + stats["position_contains_title"])[:8]:
        report.append(f"  {item['project']} ({item['lang']})")
        if item['lang'] == 'ru':
            report.append(f"    {item['position_ru']}")
        else:
            report.append(f"    {item['position_en']}")
    total = len(stats["position_contains_degree"]) + len(stats["position_contains_title"])
    if total > 8:
        report.append(f"  ... и ещё {total - 8}")
    report.append("")
    
    # Пропущенные поля
    report.append(f"ОТСУТСТВУЕТ position_ru: {len(stats['missing_position_ru'])} авторов")
    for item in stats["missing_position_ru"][:5]:
        report.append(f"  {item['project']}: {item['name_ru']}")
    if len(stats["missing_position_ru"]) > 5:
        report.append(f"  ... и ещё {len(stats['missing_position_ru']) - 5}")
    report.append("")
    
    report.append(f"ОТСУТСТВУЕТ position_en: {len(stats['missing_position_en'])} авторов")
    for item in stats["missing_position_en"][:5]:
        report.append(f"  {item['project']}: {item['name_en']}")
    if len(stats["missing_position_en"]) > 5:
        report.append(f"  ... и ещё {len(stats['missing_position_en']) - 5}")
    report.append("")
    
    report.append(f"ОТСУТСТВУЕТ поле initials: {len(stats['missing_initials'])} авторов")
    for item in stats["missing_initials"][:5]:
        report.append(f"  {item['project']}: {item['name_ru']} / {item['name_en']}")
    if len(stats["missing_initials"]) > 5:
        report.append(f"  ... и ещё {len(stats['missing_initials']) - 5}")
    report.append("")
    
    report.append("=" * 80)
    
    return "\n".join(report)

if __name__ == "__main__":
    projects_path = Path(__file__).parent.parent / "data" / "projects.json"
    stats = diagnose(projects_path)
    print(format_report(stats))
