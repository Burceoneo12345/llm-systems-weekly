import { copyFileSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { marked } from "marked";

const repository = "https://github.com/Burceoneo12345/llm-systems-weekly";
const output = "_site";
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
const topicOrder = ["4-bit RL", "训练", "强化学习", "推理", "低精度", "NVIDIA", "AMD"];
const escape = (value) => String(value).replaceAll("&", "&amp;").replaceAll('"', "&quot;")
  .replaceAll("<", "&lt;").replaceAll(">", "&gt;");

function longDate(date) {
  const [year, month, day] = date.split("-").map(Number);
  return `${year} 年 ${month} 月 ${day} 日`;
}

function writePage(path, html) {
  const destination = join(output, path, "index.html");
  mkdirSync(dirname(destination), { recursive: true });
  writeFileSync(destination, html);
}

const issues = [];
const files = readdirSync("reports").filter(name => /^\d{4}-\d{2}-\d{2}\.md$/.test(name)).sort().reverse();
for (const file of files) {
  const tokens = marked.lexer(readFileSync(join("reports", file), "utf8")).filter(token => token.type !== "space");
  const heading = tokens.shift();
  const coverage = tokens.shift();
  if (heading?.type !== "heading" || heading.depth !== 1 || coverage?.type !== "paragraph") {
    throw new Error(`${file} 需要一级标题和单独一段检索区间`);
  }
  const issue = { date: file.slice(0, -3), coverage: coverage.text, intro: [], stories: [], follow: null };
  let body = issue.intro;
  for (const token of tokens) {
    if (token.type === "heading" && token.depth === 2) {
      body = [];
      if (token.text === "本周跟进") {
        issue.follow = body;
      } else {
        issue.stories.push({ title: token.text, body });
      }
    } else {
      body.push(token);
    }
  }
  for (const story of issue.stories) {
    const meta = story.body.shift();
    const fields = meta?.tokens?.filter(token => token.type === "codespan").map(token => token.text) ?? [];
    const [date, source, status, ...topics] = fields;
    if (!datePattern.test(date) || !source || !status || !topics.length || !story.body.length) {
      throw new Error(`${file}「${story.title}」缺少日期、来源、状态、主题或正文`);
    }
    Object.assign(story, { date, source, status, topics });
  }
  issues.push(issue);
}
if (!issues.length) throw new Error("reports/ 下需要至少一期按截止日期命名的周报");

function page(title, root, active, content) {
  const nav = [["issue", "本期", ""], ["archive", "历史归档", "archive/"], ["prompt", "周报提示词", "prompt/"]];
  return `<!doctype html>
<html lang="zh-CN"><head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#173e56"><meta name="description" content="训练、强化学习、推理与低精度的每周论文和源码。">
  <title>${escape(title)} · 大模型系统周报</title>
  <link rel="icon" href="data:,"><link rel="stylesheet" href="${root}site.css">
  <script src="${root}filter.js" defer></script>
</head><body>
  <a class="skip" href="#main">跳到正文</a>
  <header class="mast"><div class="wrap mast-inner">
    <a class="brand" href="${root}"><span class="mark" aria-hidden="true"><i></i><i></i><i></i></span>大模型系统周报</a>
    <nav aria-label="主导航">${nav.map(([key, label, path]) =>
      `<a href="${root}${path}"${active === key ? ' aria-current="page"' : ""}>${label}</a>`
    ).join("")}<a class="repo" href="${repository}">GitHub</a></nav>
  </div></header>
  <main id="main" class="wrap">${content}</main>
</body></html>`;
}

function issuePage(issue, root, latest) {
  const topics = new Set(issue.stories.flatMap(story => story.topics));
  const ordered = [...new Set([...topicOrder.filter(topic => topics.has(topic)), ...topics])];
  const controls = ordered.length ? `<div class="filter-row" data-filters hidden>
    <div class="filter-buttons" role="group" aria-label="按主题筛选">
    <button type="button" data-topic="" aria-pressed="true">全部</button>
    ${ordered.map(topic => `<button type="button" data-topic="${escape(topic)}" aria-pressed="false">${escape(topic)}</button>`).join("")}
    </div><span class="count" aria-live="polite">${issue.stories.length} 条进展</span></div>` : "";
  const stories = issue.stories.map((story, index) => {
    const featured = index === 0;
    const table = featured ? story.body.find(token => token.type === "table") : undefined;
    const prose = marked.parser(story.body.filter(token => token !== table));
    return `<article class="story${featured ? " lead" : ""}${table ? " with-table" : ""}" data-topics="${escape(JSON.stringify(story.topics))}" id="item-${index + 1}">
      <div class="story-main">
        <div class="story-meta">${featured ? '<strong>本期首读</strong>' : ""}
          <span>${escape(story.source)}</span><span>${escape(story.status)}</span><time datetime="${story.date}">${story.date.slice(5).replace("-", "/")}</time>
        </div>
        <h2>${escape(story.title)}</h2><div class="story-copy">${prose}</div>
      </div>${table ? `<aside class="measure" aria-label="首读实验数据">${marked.parser([table])}</aside>` : ""}
    </article>`;
  }).join("");
  const original = `${repository}/blob/main/reports/${issue.date}.md`;
  return page(longDate(issue.date), root, latest ? "issue" : "archive", `
    <header class="issue-heading"><div>
      <h1><time datetime="${issue.date}">${longDate(issue.date)}</time></h1>
      <p class="coverage">${escape(issue.coverage)}</p>
    </div><div class="issue-links"><a href="${root}weeks/${issue.date}/">本期固定链接</a><a href="${original}">Markdown 原文</a></div></header>
    ${marked.parser(issue.intro)}${controls}<div class="stories">${stories}</div>
    ${issue.follow?.length ? `<section class="follow"><h2>本周跟进</h2>${marked.parser(issue.follow)}</section>` : ""}`);
}

mkdirSync(output, { recursive: true });
for (const asset of ["site.css", "filter.js"]) copyFileSync(asset, join(output, asset));
writePage("", issuePage(issues[0], "./", true));
for (const issue of issues) writePage(`weeks/${issue.date}`, issuePage(issue, "../../", issue === issues[0]));
const archive = issues.map(issue => `<li><a href="../weeks/${issue.date}/">
  <time datetime="${issue.date}">${longDate(issue.date)}</time>
  <strong>${escape(issue.stories[0]?.title ?? "本周检索记录")}</strong>
  <span>${issue.stories.length} 条进展</span></a></li>`).join("");
writePage("archive", page("历史归档", "../", "archive",
  `<div class="subpage"><h1>历史归档</h1><ul class="archive-list">${archive}</ul></div>`));
writePage("prompt", page("周报提示词", "../", "prompt",
  `<article class="subpage prompt">${marked.parse(readFileSync("PROMPT.md", "utf8"))}</article>`));
