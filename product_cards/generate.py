"""Validate the LLM plan, then render only source facts and safe editorial text."""

from datetime import datetime, timezone

from .errors import CardError
from .input import Product
from .llm import OllamaClient
from .prompts import ANGLES, AUDIENCES, PROMPT_VERSION


def validate_plan(plan: object, product: Product) -> dict:
    required = {"spec_priority", "description_id", "audience", "angle", "review_ids"}
    if not isinstance(plan, dict) or set(plan) != required:
        raise CardError("invalid_plan", "План должен содержать только пять полей из схемы.")
    specs = {f.id for f in product.spec_facts()}
    descriptions = {f.id for f in product.description_facts()}
    for key, allowed, minimum, maximum in (
        ("spec_priority", specs, 1 if specs else 0, min(5, len(specs))),
        ("review_ids", specs | descriptions, 0, len(specs | descriptions)),
    ):
        value = plan[key]
        if (not isinstance(value, list) or not minimum <= len(value) <= maximum
                or any(not isinstance(item, str) or item not in allowed for item in value)
                or len(value) != len(set(value))):
            raise CardError("invalid_plan", f"Проверьте уникальные исходные ID и количество элементов в {key}.")
    if plan["description_id"] is not None and (
        not isinstance(plan["description_id"], str) or plan["description_id"] not in descriptions
    ):
        raise CardError("invalid_plan", "description_id отсутствует в исходном каталоге.")
    if not isinstance(plan["audience"], str) or plan["audience"] not in AUDIENCES:
        raise CardError("invalid_plan", "audience должна быть одним из разрешённых вариантов.")
    if not isinstance(plan["angle"], str) or plan["angle"] not in ANGLES:
        raise CardError("invalid_plan", "angle должен быть одним из разрешённых вариантов.")
    return plan


def _punctuate(text: str) -> str:
    return text if text.endswith((".", "!", "?", "…")) else text + "."


def _title(product: Product) -> tuple[str, bool]:
    if len(product.name) > 70:
        prefix = product.name[:69]
        if " " in prefix:
            prefix = prefix.rsplit(" ", 1)[0]
        return prefix.rstrip() + "…", True
    extended = f"{product.name} — {product.manufacturer}"
    return (extended if product.manufacturer and len(extended) <= 70 else product.name), False


def render_card(product: Product, plan: dict, metadata: dict) -> dict:
    validate_plan(plan, product)
    spec_map = {fact.id: fact for fact in product.spec_facts()}
    descriptions = {fact.id: fact for fact in product.description_facts()}
    review = set(plan["review_ids"])
    ordered_ids = plan["spec_priority"] + [key for key in spec_map if key not in plan["spec_priority"]]
    ordered = [spec_map[key] for key in ordered_ids]
    title, shortened = _title(product)
    notes = ["Черновик требует проверки человеком по паспорту конкретного исполнения. "
             "Совпадение с входными данными не подтверждает их достоверность."]
    if shortened:
        notes.append("Название длиннее лимита SEO-заголовка: заголовок сокращён с многоточием; полное название сохранено в product_name.")
    if review:
        notes.append("Модель отметила фрагменты для проверки: " + ", ".join(sorted(review)) +
                     ". Они исключены из SEO-описания и задач; исходные характеристики сохранены с пометкой review_required.")
    missing = product.missing_fields()
    selected_description = descriptions.get(plan["description_id"])
    if selected_description and selected_description.id in review:
        selected_description = None

    paragraphs = [_punctuate(product.name) + " " + (
        _punctuate("Производитель: " + product.manufacturer) if product.manufacturer
        else "Производитель: данных нет; уточните перед оформлением заказа.")]
    if selected_description and len(selected_description.value) <= 420:
        paragraphs.append(_punctuate(selected_description.value))
    elif product.description:
        paragraphs.append("Назначение и условия применения необходимо уточнить по исходному описанию и паспорту конкретного исполнения.")
        notes.append("Фрагмент описания не включён в SEO-текст: не выбран, требует проверки или превышает 420 символов. Исходный текст сохранён в source_facts.")
    else:
        paragraphs.append("Описание и назначение: данных нет. Для подготовки карточки необходимо получить описание или фрагмент технического паспорта.")

    # Complete facts only: skip a long fact instead of truncating a value or unit.
    spec_sentences = []
    for fact in ordered:
        if fact.id in review:
            continue
        candidate = _punctuate(fact.sentence)
        if sum(map(len, spec_sentences)) + len(candidate) <= 300:
            spec_sentences.append(candidate)
    if spec_sentences:
        paragraphs.append("По исходным данным: " + " ".join(spec_sentences))
    else:
        paragraphs.append("Ключевые параметры требуют уточнения: в краткое описание не включены неподтверждённые или слишком длинные значения.")

    if missing:
        names = ", ".join(item["label"] for item in missing)
        if len(names) <= 180:
            paragraphs.append("Данных нет: " + names + ". Уточните значения и применимость этих полей к выбранному прибору.")
        else:
            paragraphs.append("Часть сведений отсутствует. Полный перечень полей для уточнения приведён отдельно; отсутствие значения не означает отсутствия функции у прибора.")

    # A safe, bounded editorial vocabulary supplies context without performance,
    # compatibility, stock, certification, warranty or pricing claims.
    editorial = [
        ANGLES[plan["angle"]],
        "Перед заказом согласуйте с поставщиком точное исполнение и комплект поставки. Условия применения следует проверить по техническому паспорту; приведённых сведений недостаточно для подтверждения совместимости с конкретным оборудованием.",
        "Для подготовки коммерческого предложения передайте менеджеру требования к прибору и перечень параметров, которые необходимо уточнить. Стоимость, наличие и срок поставки согласовываются отдельно.",
        "Используйте эту карточку как основу для обсуждения с техническим специалистом. Окончательный выбор следует делать после проверки документации и согласования требований к применению.",
        "Если у поставщика доступны разные исполнения, запросите сведения именно о выбранном варианте. Не переносите параметры похожего прибора в спецификацию заказа без документального подтверждения.",
    ]
    # Preserve the name/manufacturer and add whole paragraphs up to the cap.
    description_parts = []
    omitted = False
    for paragraph in paragraphs:
        candidate = "\n\n".join(description_parts + [paragraph])
        if len(candidate) <= 1050:
            description_parts.append(paragraph)
        else:
            omitted = True
    for paragraph in editorial:
        if len("\n\n".join(description_parts)) >= 800:
            break
        if len("\n\n".join(description_parts + [paragraph])) <= 1200:
            description_parts.append(paragraph)
    seo_description = "\n\n".join(description_parts)
    if not 800 <= len(seo_description) <= 1200:
        raise CardError("render_error", "Не удалось составить описание нужной длины. Уточните исходные данные.")
    if omitted:
        notes.append("Некоторые абзацы не вошли в SEO-описание из-за ограничения длины. Полные данные доступны в характеристиках и source_facts.")

    key_specs = [{"name": fact.label, "value": fact.value, "source": fact.source,
                  "review_required": fact.id in review} for fact in ordered]
    key_specs += [{"name": item["label"], "value": "данных нет", "source": None,
                   "review_required": True} for item in missing if item["field"].startswith("/specs/")]

    # Queries suggest search intent, never claim demand, availability or suitability.
    queries = [product.name, f"{product.name} характеристики", f"{product.name} запрос цены"]
    if product.manufacturer:
        queries.append(f"{product.name} {product.manufacturer}")
    if ordered:
        clean = next((f for f in ordered if f.id not in review), None)
        if clean:
            queries.append(f"{product.name} {clean.label} {clean.value}")
    queries = list(dict.fromkeys(queries))[:5]

    tasks = (selected_description.value if selected_description
             else "Назначение не сформулировано: требуется уточнение по описанию или паспорту.")
    return {
        "status": "draft_requires_review",
        "product_name": product.name,
        "source_note": product.source_note,
        "seo_title": title,
        "seo_description": seo_description,
        "character_counts": {"seo_title": len(title), "seo_description": len(seo_description)},
        "key_specs": key_specs,
        "search_queries": queries,
        "commercial": {"audience": AUDIENCES[plan["audience"]], "tasks": tasks,
                       "next_step": "Сверить требования заказчика с указанными параметрами и запросить недостающие сведения у поставщика."},
        "missing_fields": missing,
        "review_notes": notes,
        "source_facts": [{"id": f.id, "label": f.label, "value": f.value, "source": f.source}
                         for f in product.spec_facts() + product.description_facts()],
        "generation": {**metadata, "prompt_version": PROMPT_VERSION, "plan": plan,
                       "generated_at": datetime.now(timezone.utc).isoformat(),
                       "method": "llm_plan_with_source_only_renderer"},
    }


def generate(product: Product, client: OllamaClient | None = None) -> dict:
    client = client or OllamaClient()
    correction = None
    # Retry only an invalid model plan/JSON, once. Network errors are returned
    # immediately; there is no hidden template-only fallback masquerading as AI.
    for attempt in range(2):
        try:
            plan, metadata = client.generate_plan(product, correction)
            validate_plan(plan, product)
            metadata["attempts"] = attempt + 1
            return render_card(product, plan, metadata)
        except CardError as exc:
            if exc.code not in {"invalid_plan", "llm_invalid_response"} or attempt == 1:
                raise
            correction = exc.message
    raise AssertionError("unreachable")
