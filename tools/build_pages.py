#!/usr/bin/env python3
"""
ЭТАП 5.1: Генератор страниц проектов для Tilda.

Читает data/projects.json и генерирует:
- /build/ru/<dept>/<slug>/index.html  — русская страница проекта
- /build/en/<dept>/<slug>/index.html  — английская страница проекта

Каждая страница:
- Полностью автономная (стили и скрипты встроены)
- Содержит hreflang разметку
- Имеет переключатель языка (если есть обе версии)
"""

import json
from pathlib import Path
from datetime import datetime

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
BUILD = REPO / "build"

# CSS встроенный (минимальный)
CSS_EMBEDDED = """
<style>
:root {
  --sech-color-primary: #1f4788;
  --sech-color-secondary: #0066cc;
  --sech-color-text: #333;
  --sech-color-text-light: #666;
  --sech-color-bg: #f9f9f9;
  --sech-font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --sech-font-serif: "Georgia", serif;
}

* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: var(--sech-font-sans);
  color: var(--sech-color-text);
  background: #fff;
  line-height: 1.6;
}

.sech-projects {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
}

.sech-projects__header {
  display: flex;
  justify-content: space-between;
  align-items: start;
  margin-bottom: 40px;
  gap: 20px;
}

.sech-projects__title {
  font-size: 28px;
  font-weight: 600;
  color: var(--sech-color-primary);
}

.sech-projects__lang-switch {
  display: flex;
  gap: 8px;
}

.sech-projects__lang-btn {
  padding: 8px 16px;
  border: 1px solid var(--sech-color-primary);
  background: white;
  color: var(--sech-color-primary);
  cursor: pointer;
  border-radius: 4px;
  font-size: 14px;
  transition: all 0.2s ease;
}

.sech-projects__lang-btn.active {
  background: var(--sech-color-primary);
  color: white;
}

.sech-projects__lang-btn:hover {
  opacity: 0.8;
}

.sech-projects__section {
  margin-bottom: 30px;
}

.sech-projects__section-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--sech-color-primary);
  margin-bottom: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.sech-projects__authors {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin: 16px 0;
}

.sech-projects__author {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: var(--sech-color-bg);
  border-radius: 4px;
  font-size: 14px;
}

.sech-projects__author-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--sech-color-primary);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 12px;
}

.sech-projects__author-name {
  font-weight: 600;
}

.sech-projects__author-role {
  font-size: 12px;
  color: var(--sech-color-text-light);
}

@media (max-width: 768px) {
  .sech-projects {
    padding: 16px;
  }
  .sech-projects__title {
    font-size: 20px;
  }
  .sech-projects__header {
    flex-direction: column;
  }
}
</style>
"""

# JS встроенный (переключатель языка)
JS_EMBEDDED = """
<script>
document.addEventListener('DOMContentLoaded', function() {
  // Переключатель языка
  const langBtns = document.querySelectorAll('[data-lang-switch]');
  const currentLang = document.documentElement.lang;
  
  langBtns.forEach(btn => {
    if (btn.dataset.lang === currentLang) {
      btn.classList.add('active');
    }
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      const newLang = this.dataset.lang;
      const newUrl = location.pathname.replace(/\\/(ru|en)\\//, '/' + newLang + '/');
      location.href = newUrl;
    });
  });
});
</script>
"""

def get_author_initials(name_ru):
    """Извлекает инициалы из имени для монограммы."""
    if not name_ru:
        return ""
    parts = name_ru.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    elif parts:
        return parts[0][0].upper()
    return ""

def render_project_page(project, dept, lang):
    """Рендерит HTML-страницу проекта."""
    
    slug = project.get("slug", "unknown")
    
    if lang == "ru":
        title = project.get("title_ru", "Проект")
        description = project.get("description_ru", "")
        status = project.get("status_ru", "Активный проект")
        lang_other = "en"
        lang_other_text = "English"
        lang_current_text = "Русский"
    else:
        title = project.get("title_en", "Project")
        description = project.get("description_en", "")
        status = project.get("status_en", "Active Project")
        lang_other = "ru"
        lang_other_text = "Русский"
        lang_current_text = "English"
    
    # Составляем URL для альтернативного языка
    url_other = f"/{lang_other}/{dept['slug']}/{slug}/"
    
    # Рендерим авторов
    authors_html = ""
    for author in project.get("authors", [])[:6]:
        if lang == "ru":
            name = author.get("name_ru", "")
            degree = author.get("degree_ru", "")
            position = author.get("position_ru", "")
            title_text = author.get("academic_title_ru", "")
        else:
            name = author.get("name_en", "")
            degree = author.get("degree_en", "")
            position = author.get("position_en", "")
            title_text = author.get("academic_title_en", "")
        
        if not name:
            continue
        
        initials = get_author_initials(author.get("name_ru", ""))
        
        role_parts = []
        if title_text:
            role_parts.append(title_text)
        if degree:
            role_parts.append(degree)
        if position:
            role_parts.append(position)
        role = ", ".join(role_parts) if role_parts else ""
        
        authors_html += f"""
        <div class="sech-projects__author">
          <div class="sech-projects__author-avatar">{initials}</div>
          <div>
            <div class="sech-projects__author-name">{name}</div>
            {f'<div class="sech-projects__author-role">{role}</div>' if role else ''}
          </div>
        </div>
        """
    
    # Основной HTML
    html = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  
  <!-- hreflang разметка для SEO -->
  <link rel="canonical" href="https://innovativedrugsconference.sechenov.ru/{lang}/{dept['slug']}/{slug}/">
  <link rel="alternate" hreflang="ru" href="https://innovativedrugsconference.sechenov.ru/ru/{dept['slug']}/{slug}/">
  <link rel="alternate" hreflang="en" href="https://innovativedrugsconference.sechenov.ru/en/{dept['slug']}/{slug}/">
  <link rel="alternate" hreflang="x-default" href="https://innovativedrugsconference.sechenov.ru/ru/{dept['slug']}/{slug}/">
  
  {CSS_EMBEDDED}
</head>
<body>
  <div class="sech-projects">
    <div class="sech-projects__header">
      <div>
        <h1 class="sech-projects__title">{title}</h1>
        <p style="color: var(--sech-color-text-light); margin-top: 8px;">{status}</p>
      </div>
      <div class="sech-projects__lang-switch">
        <button class="sech-projects__lang-btn" data-lang-switch data-lang="{lang}">{lang_current_text}</button>
        {f'<button class="sech-projects__lang-btn" data-lang-switch data-lang="{lang_other}"><a href="{url_other}" style="color: inherit; text-decoration: none;">{lang_other_text}</a></button>' if project.get('description_' + lang_other) else ''}
      </div>
    </div>
    
    <div class="sech-projects__section">
      <h2 class="sech-projects__section-title">
        {"Авторы" if lang == "ru" else "Authors"}
      </h2>
      <div class="sech-projects__authors">
        {authors_html}
      </div>
    </div>
    
    <div class="sech-projects__section">
      <h2 class="sech-projects__section-title">
        {"Описание" if lang == "ru" else "Description"}
      </h2>
      <div style="line-height: 1.8; color: var(--sech-color-text);">
        {description}
      </div>
    </div>
    
    <div style="margin-top: 60px; padding-top: 20px; border-top: 1px solid var(--sech-color-bg); font-size: 12px; color: var(--sech-color-text-light);">
      {"Сгенерировано:" if lang == "ru" else "Generated:"} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC
    </div>
  </div>
  
  {JS_EMBEDDED}
</body>
</html>
"""
    
    return html

def main():
    with open(DATA / "projects.json") as f:
        data = json.load(f)
    
    total_pages = 0
    
    for dept in data.get("departments", []):
        dept_slug = dept.get("slug", "unknown")
        
        for project in dept.get("projects", []):
            slug = project.get("slug", "unknown")
            
            # Русская страница
            if project.get("description_ru"):
                ru_dir = BUILD / "ru" / dept_slug / slug
                ru_dir.mkdir(parents=True, exist_ok=True)
                
                html = render_project_page(project, dept, "ru")
                (ru_dir / "index.html").write_text(html, encoding="utf-8")
                total_pages += 1
                print(f"✓ /ru/{dept_slug}/{slug}/")
            
            # Английская страница
            if project.get("description_en"):
                en_dir = BUILD / "en" / dept_slug / slug
                en_dir.mkdir(parents=True, exist_ok=True)
                
                html = render_project_page(project, dept, "en")
                (en_dir / "index.html").write_text(html, encoding="utf-8")
                total_pages += 1
                print(f"✓ /en/{dept_slug}/{slug}/")
    
    print(f"\n✓ Всего страниц сгенерировано: {total_pages}")

if __name__ == "__main__":
    main()
