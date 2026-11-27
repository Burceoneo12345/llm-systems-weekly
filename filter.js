const items = [...document.querySelectorAll("article[data-topics]")];
const params = new URLSearchParams(location.search);
const topic = params.get("topic");
const matches = topic ? items.filter(item => JSON.parse(item.dataset.topics).includes(topic)) : [];
const follow = document.querySelector(".follow");
if (matches.length) {
  for (const item of items) item.hidden = !matches.includes(item);
  document.querySelector(".count").textContent = `${matches.length} 条进展`;
  const index = document.querySelector(".index-section");
  index?.classList.toggle("only-rail", !index.querySelector(".entry:not([hidden])"));
  if (follow) follow.hidden = true;
}

const sizeSelects = document.querySelectorAll(".page-size select");
if (sizeSelects.length && items.length) {
  const stories = matches.length ? matches : items;
  const sizes = [...sizeSelects[0].options].map(option => option.value);
  const defaultSize = sizeSelects[0].querySelector("[selected]").value;
  const size = sizes.includes(params.get("size")) ? params.get("size") : defaultSize;
  const perPage = size === "all" ? stories.length : Number(size);
  const pages = Math.ceil(stories.length / perPage);
  for (const controls of document.querySelectorAll(".page-tools")) {
    controls.hidden = stories.length <= Number(sizes[0]);
  }

  function pageUrl(page, selectedSize) {
    const url = new URL(location.href);
    url.hash = "";
    if (page === 1) url.searchParams.delete("page");
    else url.searchParams.set("page", page);
    if (selectedSize === defaultSize) url.searchParams.delete("size");
    else url.searchParams.set("size", selectedSize);
    return url;
  }

  function showPage() {
    const anchor = stories.findIndex(item => "#" + item.id === location.hash);
    const requested = Number(params.get("page"));
    const fromQuery = Number.isSafeInteger(requested) ? Math.max(1, Math.min(requested, pages)) : 1;
    const page = anchor < 0 ? fromQuery : Math.floor(anchor / perPage) + 1;
    const start = (page - 1) * perPage;
    const end = Math.min(start + perPage, stories.length);
    stories.forEach((item, i) => item.classList.toggle("off-page", i < start || i >= end));
    document.querySelector(".issue-note")?.classList.toggle("off-page", page > 1);
    follow?.classList.toggle("off-page", page < pages);
    document.querySelector(".count").textContent = pages > 1
      ? `第 ${start + 1}–${end} 条，共 ${stories.length} 条` : `${stories.length} 条进展`;
    const status = document.querySelector(".page-status");
    if (status) status.textContent = `第 ${page} 页，共 ${pages} 页`;

    const links = document.createDocumentFragment();
    const numbers = Array.from({ length: pages }, (_, i) => [i + 1, i + 1]);
    for (const [label, target] of [["上一页", page - 1], ...numbers, ["下一页", page + 1]]) {
      const enabled = target >= 1 && target <= pages;
      const link = document.createElement(enabled ? "a" : "span");
      link.textContent = label;
      if (enabled) link.href = pageUrl(target, size);
      else link.setAttribute("aria-disabled", "true");
      if (typeof label === "number") link.setAttribute("aria-label", `第 ${target} 页`);
      if (target === page) link.setAttribute("aria-current", "page");
      links.append(link);
    }
    for (const nav of document.querySelectorAll(".pager")) {
      nav.hidden = pages === 1;
      nav.replaceChildren(links.cloneNode(true));
    }
    if (anchor >= 0) stories[anchor].scrollIntoView();
  }

  for (const select of sizeSelects) {
    select.value = size;
    select.addEventListener("change", () => location.assign(pageUrl(1, select.value)));
    window.addEventListener("pageshow", () => { select.value = size; });
  }
  window.addEventListener("hashchange", showPage);
  showPage();
}
