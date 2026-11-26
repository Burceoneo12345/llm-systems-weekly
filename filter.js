const controls = document.querySelector("[data-filters]");
if (controls) {
  const buttons = [...controls.querySelectorAll("button[data-topic]")];
  const cards = [...document.querySelectorAll("article[data-topics]")];
  const follow = document.querySelector(".follow");
  function selectTopic(value) {
    const selected = buttons.some(button => button.dataset.topic === value) ? value : "";
    let count = 0;
    for (const card of cards) {
      card.hidden = Boolean(selected) && !JSON.parse(card.dataset.topics).includes(selected);
      if (!card.hidden) count++;
    }
    for (const button of buttons) button.setAttribute("aria-pressed", String(button.dataset.topic === selected));
    controls.querySelector(".count").textContent = `${count} 条进展`;
    if (follow) follow.hidden = Boolean(selected);
  }
  controls.addEventListener("click", event => {
    const button = event.target.closest("button[data-topic]");
    if (!button) return;
    const url = new URL(location.href);
    const topic = button.dataset.topic;
    if (topic) url.searchParams.set("topic", topic);
    else url.searchParams.delete("topic");
    history.replaceState(null, "", url);
    selectTopic(topic);
  });
  selectTopic(new URLSearchParams(location.search).get("topic"));
  controls.hidden = false;
}
