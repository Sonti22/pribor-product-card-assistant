import re


def _escape(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+.!|~>-])", r"\\\1", text)


def to_markdown(card: dict) -> str:
    e = _escape
    lines = ["# " + e(card["seo_title"]), "", "> Черновик — требуется проверка человеком.", ""]
    if card["source_note"]:
        lines += ["**Источник:** " + e(card["source_note"]), ""]
    lines += ["## SEO-описание", "", e(card["seo_description"]), "",
              f"*Символов в исходном тексте: заголовок {card['character_counts']['seo_title']}; описание {card['character_counts']['seo_description']}.*",
              "", "## Ключевые характеристики", "", "| Характеристика | Значение |", "| --- | --- |"]
    for spec in card["key_specs"]:
        suffix = " (уточнить)" if spec["review_required"] else ""
        lines.append(f"| {e(spec['name'])} | {e(spec['value'] + suffix)} |")
    lines += ["", "## Поисковые запросы", ""] + ["- " + e(q) for q in card["search_queries"]]
    lines += ["", "## Для менеджера", "", "**Кому подходит:** " + e(card["commercial"]["audience"]),
              "", "**Задачи по исходному описанию:** " + e(card["commercial"]["tasks"]),
              "", "**Следующий шаг:** " + e(card["commercial"]["next_step"]),
              "", "## Что уточнить", ""]
    lines += ["- " + e(m["label"]) + ": данных нет." for m in card["missing_fields"]] or ["Пропусков по заданному перечню полей нет."]
    lines += ["", "## Замечания", ""] + ["- " + e(n) for n in card["review_notes"]]
    lines += ["", "*Модель: " + e(card["generation"]["model"]) + "; " + e(card["generation"]["prompt_version"]) + ".*", ""]
    return "\n".join(lines)
