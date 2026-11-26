const topic = new URLSearchParams(location.search).get("topic");
if (topic) {
  const items = [...document.querySelectorAll("article[data-topics]")];
  const matches = items.filter(item => JSON.parse(item.dataset.topics).includes(topic));
  if (matches.length) {
    for (const item of items) item.hidden = !matches.includes(item);
    document.querySelector(".count").textContent = `${matches.length} 条进展`;
    const index = document.querySelector(".index-section");
    index?.classList.toggle("only-rail", !index.querySelector(".entry:not([hidden])"));
    const follow = document.querySelector(".follow");
    if (follow) follow.hidden = true;
  }
}
