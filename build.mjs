import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { marked } from "marked";

const repository = "https://github.com/Burceoneo12345/llm-systems-weekly";
const output = "_site";
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
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
  const tokens = marked.lexer(readFileSync(join("reports", file), "utf8")).filter(
    token => token.type !== "space" && !(token.type === "html" && token.raw.startsWith("<!-- pending-sources "))
  );
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
    const kind = status === "已合并" ? "PR" : status === "未合并" ? "待合并 PR" : source === "arXiv" || status.endsWith("论文") ? "论文" : status.includes("发布") ? "版本发布" : "";
    Object.assign(story, { date, source, status, topics, kind });
  }
  const lead = issue.stories[0];
  if (lead) {
    const source = lead.body.at(-1)?.tokens?.find(token => token.type === "link")?.href ?? "";
    const key = createHash("sha256").update(JSON.stringify([issue.date, lead.title, source])).digest("hex").slice(0, 12);
    issue.cover = { file: `assets/covers/${issue.date}-${key}.webp`, title: lead.title,
      summary: lead.body.find(token => token.type === "paragraph")?.text ?? "" };
  }
  issues.push(issue);
}
if (!issues.length) throw new Error("reports/ 下需要至少一期按截止日期命名的周报");
if (process.argv[2] === "--missing-covers") {
  const pending = issues.map(issue => issue.cover).filter(cover => cover && !existsSync(cover.file));
  writeFileSync(1, JSON.stringify(pending));
  process.exit(0);
}

function page(title, root, active, content) {
  const nav = [["issue", "本期周报", ""], ["archive", "历史归档", "archive/"], ["prompt", "周报提示词", "prompt/"]];
  return `<!doctype html>
<html lang="zh-CN"><head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#faf9f6"><meta name="description" content="每周一和周五，读大模型训练、强化学习、推理和低精度的新论文与源码。">
  <title>${escape(title)} · 大模型系统周报</title>
  <link rel="icon" href="${root}assets/compute-cover.webp"><link rel="stylesheet" href="${root}site.css?v=${assetVersion}">
  <script src="${root}filter.js?v=${assetVersion}" defer></script>
</head><body>
  <a class="skip" href="#main">跳到正文</a>
  <header class="mast"><div class="wrap mast-inner">
    <a class="brand" href="${root}"><span class="mark" aria-hidden="true"><i></i><i></i><i></i></span>大模型系统周报</a>
    <nav aria-label="主导航">${nav.map(([key, label, path]) =>
      `<a href="${root}${path}"${active === key ? ' aria-current="page"' : ""}>${label}</a>`
    ).join("")}<a class="repo" href="${repository}">GitHub</a></nav>
  </div></header>
  <main id="main" class="wrap">${content}</main>
  <footer class="wrap site-foot"><a href="${repository}/actions/workflows/pages.yml">周一、周五 09:00 更新（北京时间）</a><a href="${root}archive/">历期周报</a></footer>
</body></html>`;
}

function issuePage(issue, root, latest) {
  const stories = issue.stories.map((story, index) => {
    const body = [...story.body];
    const last = body.at(-1);
    const links = last?.type === "paragraph" ? last.tokens.filter(token => token.type === "link" && /^https?:\/\//.test(token.href)) : [];
    if (links.length) body.pop();
    const first = body[0]?.type === "paragraph" ? body.shift() : null;
    const lead = first ? marked.parser([first]) : "";
    const detail = body.length ? marked.parser(body) : "";
    const linkHTML = links.map(link => `<a href="${escape(link.href)}">${escape(link.text)}</a>`);
    const date = `<time datetime="${story.date}">${story.date.slice(5).replace("-", ".")}</time>`;
    const attrs = `data-topics="${escape(JSON.stringify([...story.topics, story.kind]))}" id="item-${index + 1}"`;
    const title = marked.parseInline(story.title);
    if (index === 0) {
      const extra = linkHTML.slice(1).join("");
      const evidence = detail || extra ? `<details class="evidence"><summary>展开证据与源码</summary>
        <div class="evidence-body">${detail}${extra ? `<div class="sources">${extra}</div>` : ""}</div></details>` : "";
      return `<article class="cover" ${attrs}>
        <div class="cover-copy"><div class="credit"><b>本期首读</b><span>${escape(story.source)}</span><span>${escape(story.status)}</span></div>
        <h2>${title}</h2><div class="dek">${lead}</div>
        <div class="cover-actions">${linkHTML.length ? `<a class="primary-link" href="${escape(links[0].href)}">${story.kind === "论文" ? "阅读原论文" : story.status === "已合并" ? "阅读合并记录" : story.status === "未合并" ? "阅读待合并 PR" : "阅读原文"}</a>` : ""}${evidence}</div></div>
        <figure class="cover-art"><img src="${root}${issue.cover.file}?v=${issue.cover.version}" width="896" height="704" alt="${escape(story.title)}的主题插画" fetchpriority="high"></figure>
      </article>`;
    }
    const sources = linkHTML.length ? `<div class="sources">${linkHTML.join("")}</div>` : "";
    return `<article class="entry" ${attrs}>
      <div class="entry-byline">${date}<span>${escape(story.source)}</span><small>${escape(story.status)}</small></div>
      <div class="entry-copy"><h3>${title}</h3><div class="entry-dek">${lead}</div>
      ${detail ? `<details class="evidence"><summary>展开技术细节</summary><div class="evidence-body">${detail}</div></details>` : ""}
      ${sources}</div></article>`;
  });
  const original = `${repository}/blob/main/reports/${issue.date}.md`;
  const weekday = new Intl.DateTimeFormat("zh-CN", {weekday: "long", timeZone: "UTC"}).format(new Date(issue.date));
  return page(longDate(issue.date), root, latest ? "issue" : "archive", `
    <header class="folio"><div class="folio-date"><time datetime="${issue.date}">${issue.date.replaceAll("-", ".")}</time>
      <span>${weekday}</span></div><span class="count">${stories.length} 条进展</span></header>
    <h1 class="sr-only">${longDate(issue.date)}大模型系统周报</h1>
    ${issue.intro.length ? `<div class="issue-note">${marked.parser(issue.intro)}</div>` : ""}
    <div class="page-tools" hidden>
      <label class="page-size">每页条数 <span><select id="page-size">
        <option value="5">5 条</option><option value="10" selected>10 条</option><option value="15">15 条</option><option value="all">全部</option>
      </select></span></label>
      <nav class="pager" aria-label="顶部页码"></nav>
    </div>
    ${stories[0] ?? ""}
    ${stories.length > 1 ? `<section class="index-section" aria-label="论文与源码">
      <div class="reading-rail"><h2>论文与源码</h2><p class="coverage">${escape(issue.coverage)}</p>
      <div class="rail-links"><a href="${root}weeks/${issue.date}/">本期固定链接</a><a href="${original}">Markdown 原文</a></div></div>
      <div class="index-list">${stories.slice(1).join("")}</div></section>` :
      `<div class="compact-coverage"><span>${escape(issue.coverage)}</span><a href="${original}">Markdown 原文</a><a href="${root}weeks/${issue.date}/">本期固定链接</a></div>`}
    ${issue.follow?.length ? `<section class="follow"><h2>本周跟进</h2>${marked.parser(issue.follow)}</section>` : ""}
    <nav class="pager pager-bottom" aria-label="底部页码" hidden></nav>`);
}

const assetVersion = createHash("sha256").update(readFileSync("site.css")).update(readFileSync("filter.js")).digest("hex").slice(0, 10);
mkdirSync(join(output, "assets/covers"), { recursive: true });
for (const asset of ["site.css", "filter.js", "assets/compute-cover.webp"]) copyFileSync(asset, join(output, asset));
for (const {cover} of issues) {
  if (cover) {
    const bytes = readFileSync(cover.file);
    cover.version = createHash("sha256").update(bytes).digest("hex").slice(0, 10);
    writeFileSync(join(output, cover.file), bytes);
  }
}
writePage("", issuePage(issues[0], "./", true));
for (const issue of issues) writePage(`weeks/${issue.date}`, issuePage(issue, "../../", issue === issues[0]));
const archive = issues.map(issue => `<li><a href="../weeks/${issue.date}/">
  <time datetime="${issue.date}">${issue.date.replaceAll("-", ".")}</time>
  <strong>${marked.parseInline(issue.stories[0]?.title ?? "本期检索记录")}</strong>
  <span>${issue.stories.length} 条进展</span></a></li>`).join("");
writePage("archive", page("历史归档", "../", "archive",
  `<section class="subpage archive"><header class="subhead"><h1>历史归档</h1><span>${issues.length} 期</span></header><ul class="archive-list">${archive}</ul></section>`));
writePage("prompt", page("周报提示词", "../", "prompt",
  `<article class="subpage prompt">${marked.parse(readFileSync("PROMPT.md", "utf8"))}</article>`));
