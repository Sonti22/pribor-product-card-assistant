const $ = (id) => document.getElementById(id);
const sample = {
  name: "Манометр показывающий DM 02",
  manufacturer: "Манотомь",
  specs: {
    "диапазон измерений": "0–1,6 МПа",
    "класс точности": "1,5",
    присоединение: "G1/2",
    "диаметр корпуса": "100 мм",
  },
  description: "Прибор предназначен для измерения избыточного давления...",
  source_note:
    "Пример из задания; сведения не проверялись по каталогу производителя.",
};
let result = null;
const setSample = () => {
  $("source").value = JSON.stringify(sample, null, 2);
};
$("sample").addEventListener("click", setSample);
setSample();
function fillList(id, values) {
  $(id).replaceChildren(
    ...values.map((text) => {
      const li = document.createElement("li");
      li.textContent = text;
      return li;
    }),
  );
}
function show(data) {
  const c = data.card;
  $("empty").hidden = true;
  $("output").hidden = false;
  $("badge").textContent = "Нужна проверка";
  $("note").textContent =
    c.source_note || "Черновик по предоставленным данным.";
  $("title").textContent = c.seo_title;
  $("counts").textContent =
    `Заголовок: ${c.character_counts.seo_title}/70 · Описание: ${c.character_counts.seo_description} символов`;
  $("description").textContent = c.seo_description;
  $("specs").replaceChildren(
    ...c.key_specs.flatMap((s) => {
      const dt = document.createElement("dt"),
        dd = document.createElement("dd");
      dt.textContent = s.name;
      dd.textContent = s.value + (s.review_required ? " · уточнить" : "");
      return [dt, dd];
    }),
  );
  fillList("queries", c.search_queries);
  $("commercial").textContent =
    `${c.commercial.audience}\n\n${c.commercial.tasks}\n\n${c.commercial.next_step}`;
  fillList(
    "missing",
    c.missing_fields.length
      ? c.missing_fields.map((m) => `${m.label}: данных нет`)
      : ["Пропусков по заданному перечню полей нет."],
  );
}
$("generate").addEventListener("click", async () => {
  $("generate").disabled = true;
  $("sample").disabled = true;
  $("source").disabled = true;
  result = null;
  $("output").hidden = true;
  $("empty").hidden = false;
  $("badge").textContent = "Готовим";
  $("status").textContent =
    "Создаём черновик. Первый запрос может занять несколько минут…";
  try {
    JSON.parse($("source").value);
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: $("source").value,
    });
    const data = await response.json();
    if (!response.ok)
      throw new Error(data.error?.message || "Не удалось создать черновик.");
    result = data;
    show(data);
    $("status").textContent =
      "Черновик готов. Проверьте отмеченные поля перед публикацией.";
  } catch (error) {
    $("badge").textContent = "Нужна правка";
    $("status").textContent =
      error instanceof SyntaxError
        ? "Проверьте JSON: кавычки, скобки и запятые."
        : error.message;
  } finally {
    $("generate").disabled = false;
    $("sample").disabled = false;
    $("source").disabled = false;
  }
});
async function copy(kind) {
  if (!result) return;
  try {
    await navigator.clipboard.writeText(
      kind === "md" ? result.markdown : JSON.stringify(result.card, null, 2),
    );
    $("status").textContent = "Скопировано.";
  } catch {
    $("status").textContent =
      "Буфер обмена недоступен. Используйте «Скачать JSON».";
  }
}
$("copy-md").addEventListener("click", () => copy("md"));
$("copy-json").addEventListener("click", () => copy("json"));
$("download").addEventListener("click", () => {
  if (!result) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(result.card, null, 2)], {
      type: "application/json;charset=utf-8",
    }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = "product-card.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
