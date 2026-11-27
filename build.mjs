import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { marked } from "marked";

const repository = "https://github.com/Burceoneo12345/llm-systems-weekly";
const site = "https://burceoneo12345.github.io/llm-systems-weekly/";
const output = "_site";
const tagline = "每周一和周五，读大模型训练、强化学习、推理和低精度的新论文与源码。";
const staticAssets = ["site.css", "filter.js", "assets/favicon.svg", "assets/apple-touch-icon.png"];
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
const escape = (value) => String(value).replaceAll("&", "&amp;").replaceAll('"', "&quot;")
  .replaceAll("<", "&lt;").replaceAll(">", "&gt;");
// Wide tables scroll inside their own wrapper instead of overflowing the column.
const rich = (tokens) => marked.parser(tokens).replace(/<table>[\s\S]*?<\/table>/g, '<div class="table-wrap">$&</div>');

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
  issue.note = issue.intro.find(token => token.type === "paragraph")?.text ?? "";
  issues.push(issue);
}
if (!issues.length) throw new Error("reports/ 下需要至少一期按截止日期命名的周报");
if (process.argv[2] === "--missing-covers") {
  const pending = issues.map(issue => issue.cover).filter(cover => cover && !existsSync(cover.file));
  writeFileSync(1, JSON.stringify(pending));
  process.exit(0);
}

function page({ title, root, active, content, path = "", description = tagline, image, type = "website", script = false }) {
  const nav = [["issue", "本期周报", ""], ["archive", "历史归档", "archive/"], ["prompt", "周报提示词", "prompt/"]];
  const url = `${site}${path}`;
  const fullTitle = `${title} · 大模型系统周报`;
  const graphic = image ? `<meta property="og:image" content="${image}"><meta property="og:image:width" content="896"><meta property="og:image:height" content="704">` : "";
  return `<!doctype html>
<html lang="zh-CN"><head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="${escape(description)}">
  <title>${escape(fullTitle)}</title>
  <link rel="canonical" href="${url}">
  <meta property="og:type" content="${type}"><meta property="og:site_name" content="大模型系统周报">
  <meta property="og:title" content="${escape(fullTitle)}"><meta property="og:description" content="${escape(description)}">
  <meta property="og:url" content="${url}">${graphic}
  <meta name="twitter:card" content="summary_large_image">
  <meta name="theme-color" content="#faf9f6">
  <link rel="icon" href="${root}assets/favicon.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="${root}assets/apple-touch-icon.png">
  <link rel="alternate" type="application/atom+xml" title="大模型系统周报" href="${root}feed.xml">
  <link rel="stylesheet" href="${root}site.css?v=${assetVersion}">
  ${script ? `<script src="${root}filter.js?v=${assetVersion}" defer></script>` : ""}
</head><body>
  <a class="skip" href="#main">跳到正文</a>
  <header class="mast"><div class="wrap mast-inner">
    <a class="brand" href="${root}"><span class="mark" aria-hidden="true"><i></i><i></i><i></i></span>大模型系统周报</a>
    <nav aria-label="主导航">${nav.map(([key, label, href]) =>
      `<a href="${root}${href}"${active === key ? ' aria-current="page"' : ""}>${label}</a>`
    ).join("")}<a class="repo" href="${repository}">GitHub</a></nav>
  </div></header>
  <main id="main" class="wrap">${content}</main>
  <footer class="wrap site-foot"><a href="${repository}/actions/workflows/pages.yml">周一、周五 09:00 更新（北京时间）</a><a href="${root}archive/">历期周报</a></footer>
</body></html>`;
}

function pageControls(position) {
  const bottom = position === "bottom";
  return `<nav class="page-tools" id="pagination-${position}" aria-label="${bottom ? "底部翻页" : "翻页与每页条数"}" hidden>
    <label class="page-size">每页条数 <span><select id="${bottom ? "page-size-bottom" : "page-size"}">
      <option value="5">5 条</option><option value="10" selected>10 条</option><option value="15">15 条</option><option value="all">全部</option>
    </select></span></label>
    ${bottom ? '<span class="page-status" aria-live="polite"></span>' : ""}
    <div class="pager"></div>
  </nav>`;
}

function disclosure(label, body, extra = "") {
  return `<details class="evidence"><summary data-expand="${label}" data-collapse="${label.replace(/^展开/, "收起")}">${label}</summary>
        <div class="evidence-body">${body}${extra ? `<div class="sources">${extra}</div>` : ""}</div></details>`;
}

function issuePage(issue, root, latest, path) {
  const stories = issue.stories.map((story, index) => {
    const body = [...story.body];
    const last = body.at(-1);
    const links = last?.type === "paragraph" ? last.tokens.filter(token => token.type === "link" && /^https?:\/\//.test(token.href)) : [];
    if (links.length) body.pop();
    const first = body[0]?.type === "paragraph" ? body.shift() : null;
    const lead = first ? rich([first]) : "";
    const detail = body.length ? rich(body) : "";
    const linkHTML = links.map(link => `<a href="${escape(link.href)}">${escape(link.text)}</a>`);
    const date = `<time datetime="${story.date}">${story.date.slice(5).replace("-", ".")}</time>`;
    const attrs = `data-topics="${escape(JSON.stringify([...story.topics, story.kind].filter(Boolean)))}" id="item-${index + 1}"`;
    const title = marked.parseInline(story.title);
    if (index === 0) {
      const extra = linkHTML.slice(1).join("");
      const evidence = detail || extra ? disclosure("展开证据与源码", detail, extra) : "";
      return `<article class="cover" ${attrs}>
        <div class="cover-copy"><div class="credit"><b>本期首读</b><span>${escape(story.source)}</span><span>${escape(story.status)}</span></div>
        <h2>${title}</h2><div class="dek">${lead}</div>
        <div class="cover-actions">${linkHTML.length ? `<a class="primary-link" href="${escape(links[0].href)}">${story.kind === "论文" ? "阅读原论文" : story.status === "已合并" ? "阅读合并记录" : story.status === "未合并" ? "阅读待合并 PR" : "阅读原文"}</a>` : ""}${evidence}</div></div>
        <figure class="cover-art"><img src="${root}${issue.cover.file}?v=${issue.cover.version}" width="896" height="704" alt="" fetchpriority="high"></figure>
      </article>`;
    }
    const sources = linkHTML.length ? `<div class="sources">${linkHTML.join("")}</div>` : "";
    return `<article class="entry" ${attrs}>
      <div class="entry-byline">${date}<span>${escape(story.source)}</span><small>${escape(story.status)}</small></div>
      <div class="entry-copy"><h3>${title}</h3><div class="entry-dek">${lead}</div>
      ${detail ? disclosure("展开技术细节", detail) : ""}
      ${sources}</div></article>`;
  });
  const original = `${repository}/blob/main/reports/${issue.date}.md`;
  const weekday = new Intl.DateTimeFormat("zh-CN", {weekday: "long", timeZone: "UTC"}).format(new Date(issue.date));
  const toc = issue.stories.slice(1).map((story, index) =>
    `<li data-for="item-${index + 2}"><a href="#item-${index + 2}">${marked.parseInline(story.title)}</a></li>`).join("");
  const description = (issue.note || issue.coverage || tagline).slice(0, 160);
  return page({ title: longDate(issue.date), root, active: latest ? "issue" : "archive", path, description,
    image: issue.cover ? `${site}${issue.cover.file}` : undefined, type: "article", script: true, content: `
    <header class="folio"><div class="folio-date"><time datetime="${issue.date}">${issue.date.replaceAll("-", ".")}</time>
      <span>${weekday}</span></div><span class="count">${stories.length} 条进展</span></header>
    <h1 class="sr-only">${longDate(issue.date)}大模型系统周报</h1>
    ${issue.intro.length ? `<div class="issue-note">${rich(issue.intro)}</div>` : ""}
    ${stories[0] ?? ""}
    ${pageControls("top")}
    ${stories.length > 1 ? `<section class="index-section" aria-label="论文与源码">
      <div class="reading-rail"><h2>论文与源码</h2>
      <details class="toc" open><summary>本期目录</summary><ol>${toc}</ol></details>
      <p class="coverage">${escape(issue.coverage)}</p>
      <div class="rail-links"><a href="${site}weeks/${issue.date}/">本期固定链接</a><a href="${original}">Markdown 原文</a></div></div>
      <div class="index-list">${stories.slice(1).join("")}</div></section>` :
      `<div class="compact-coverage"><span>${escape(issue.coverage)}</span><a href="${original}">Markdown 原文</a><a href="${root}weeks/${issue.date}/">本期固定链接</a></div>`}
    ${issue.follow?.length ? `<section class="follow"><h2>本周跟进</h2>${rich(issue.follow)}</section>` : ""}
    ${pageControls("bottom")}` });
}

const assetVersion = createHash("sha256").update(readFileSync("site.css")).update(readFileSync("filter.js")).digest("hex").slice(0, 10);
mkdirSync(join(output, "assets/covers"), { recursive: true });
for (const asset of staticAssets) copyFileSync(asset, join(output, asset));
for (const {cover} of issues) {
  if (cover) {
    const bytes = readFileSync(cover.file);
    cover.version = createHash("sha256").update(bytes).digest("hex").slice(0, 10);
    writeFileSync(join(output, cover.file), bytes);
  }
}
writePage("", issuePage(issues[0], "./", true, `weeks/${issues[0].date}/`));
for (const issue of issues) writePage(`weeks/${issue.date}`, issuePage(issue, "../../", issue === issues[0], `weeks/${issue.date}/`));
const archive = issues.map(issue => `<li><a href="../weeks/${issue.date}/">
  <time datetime="${issue.date}">${issue.date.replaceAll("-", ".")}</time>
  <strong>${marked.parseInline(issue.stories[0]?.title ?? "本期检索记录")}</strong>
  <span>${issue.stories.length} 条进展</span></a></li>`).join("");
const hero = issues.find(issue => issue.cover)?.cover;
const shared = { image: hero && `${site}${hero.file}`, root: "../", script: false };
writePage("archive", page({ ...shared, title: "历史归档", active: "archive", path: "archive/", description: "历期大模型系统周报归档，每期收录大模型训练、强化学习、推理与低精度的论文与源码进展。",
  content: `<section class="subpage archive"><header class="subhead"><h1>历史归档</h1><span>${issues.length} 期</span></header><ul class="archive-list">${archive}</ul></section>` }));
writePage("prompt", page({ ...shared, title: "周报提示词", active: "prompt", path: "prompt/", description: "大模型系统周报的检索范围、来源与撰写规则。",
  content: `<article class="subpage prompt">${marked.parse(readFileSync("PROMPT.md", "utf8")).replace(/<table>[\s\S]*?<\/table>/g, '<div class="table-wrap">$&</div>')}</article>` }));

const published = (date) => `${date}T09:00:00+08:00`;
writeFileSync(join(output, "feed.xml"), `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>大模型系统周报</title>
  <subtitle>${escape(tagline)}</subtitle>
  <id>${site}</id>
  <link rel="self" href="${site}feed.xml"/><link rel="alternate" href="${site}"/>
  <updated>${published(issues[0].date)}</updated>
  <author><name>大模型系统周报</name></author>
${issues.map(issue => `  <entry>
    <id>${site}weeks/${issue.date}/</id>
    <title>${escape(`${longDate(issue.date)}大模型系统周报`)}</title>
    <link rel="alternate" href="${site}weeks/${issue.date}/"/>
    <published>${published(issue.date)}</published><updated>${published(issue.date)}</updated>
    <summary type="text">${escape([issue.note, issue.stories[0] && `本期首读：${issue.stories[0].title}`].filter(Boolean).join(" "))}</summary>
  </entry>`).join("\n")}
</feed>
`);
console.log(`已生成 ${issues.length} 期周报、归档、提示词与 feed.xml`);
