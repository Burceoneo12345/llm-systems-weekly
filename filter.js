const filters = document.querySelector("[data-filters]");
if (filters) {
  const picker = filters.querySelector("select");
  const items = [...document.querySelectorAll("article[data-topics]")];
  const index = document.querySelector(".index-section");
  const follow = document.querySelector(".follow");

  function applyTopic(value) {
    picker.value = [...picker.options].some(option => option.value === value) ? value : "";
    let visible = 0;
    for (const item of items) {
      item.hidden = Boolean(picker.value) && !JSON.parse(item.dataset.topics).includes(picker.value);
      if (!item.hidden) visible++;
    }
    document.querySelector(".count").textContent = `${visible} 条进展`;
    index?.classList.toggle("only-rail", !index.querySelector(".entry:not([hidden])"));
    if (follow) follow.hidden = Boolean(picker.value);
  }

  picker.addEventListener("change", () => {
    const url = new URL(location.href);
    if (picker.value) url.searchParams.set("topic", picker.value);
    else url.searchParams.delete("topic");
    history.replaceState(null, "", url);
    applyTopic(picker.value);
  });
  applyTopic(new URLSearchParams(location.search).get("topic"));
  filters.hidden = false;
}
