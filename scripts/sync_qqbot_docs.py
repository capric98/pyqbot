#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "beautifulsoup4==4.15.0",
#     "markdownify==1.2.3",
# ]
# ///
"""Archive the deployed QQ Bot API v2 docs as Markdown (Python 3.9+)."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urldefrag, urljoin, urlsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter


PROJECT = Path(__file__).resolve().parents[1]
BASE = "https://bot.q.qq.com/wiki/develop/api-v2/"
PREFIX = "/wiki/develop/api-v2/"
OUTPUT = PROJECT / "docs/upstream/qqbot-api-v2"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def local_path(url):
    path = unquote(urlsplit(url).path)
    if not path.startswith(PREFIX):
        raise ValueError(f"Outside API v2: {url}")
    relative = path[len(PREFIX):]
    if ".." in PurePosixPath(relative).parts:
        raise ValueError(f"Unsafe path: {url}")
    if not relative or relative.endswith("/"):
        relative += "index.html"
    if relative.endswith(".md"):
        return PurePosixPath(relative)
    if not relative.endswith(".html"):
        raise ValueError(f"Unexpected document URL: {url}")
    return PurePosixPath(relative[:-5] + ".md")


class Downloader:
    def __init__(self, cache, offline):
        self.cache = cache
        self.offline = offline
        cache.mkdir(parents=True, exist_ok=True)

    def fetch(self, url):
        key = digest(url.encode("utf-8"))
        body = self.cache / (key + ".bin")
        meta = self.cache / (key + ".json")
        if self.offline:
            return body.read_bytes(), json.loads(meta.read_text())["content_type"]
        for attempt in range(3):
            try:
                request = Request(url, headers={"User-Agent": "pyqbot-docs-archive/1.0"})
                with urlopen(request, timeout=45) as response:
                    data = response.read()
                    content_type = response.headers.get_content_type()
                body.write_bytes(data)
                meta.write_text(json.dumps({"url": url, "content_type": content_type}))
                return data, content_type
            except (OSError, URLError) as error:
                if isinstance(error, HTTPError) and error.code not in (429, 500, 502, 503, 504):
                    raise
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)


class Converter(MarkdownConverter):
    def process_text(self, el, parent_tags=None):
        text = super().process_text(el, parent_tags)
        if "_noformat" not in (parent_tags or set()):
            # Literal entities in the source must remain literal after Markdown
            # rendering (e.g. the documented replacement string "&amp;").
            text = html.escape(text, quote=False)
        return text

    def convert_a(self, el, text, parent_tags):
        if el.get("id") and not el.get("href"):
            return '\n\n<a id="' + html.escape(el["id"], quote=True) + '"></a>\n\n'
        return super().convert_a(el, text, parent_tags)

    def convert_pre(self, el, text, parent_tags):
        # Read the code directly: syntax highlighting and Markdown escaping must
        # not change JSON, whitespace, URLs, or backticks inside examples.
        code = el.code if el.code is not None else el
        content = code.get_text().rstrip("\n")
        classes = el.get("class", []) + code.get("class", [])
        language = next((c[9:] for c in classes if c.startswith("language-")), "")
        longest = max((len(m) for m in re.findall(r"`+", content)), default=0)
        fence = "`" * max(3, longest + 1)
        return f"\n\n{fence}{language}\n{content}\n{fence}\n\n"

    def convert_br(self, el, text, parent_tags):
        if el.find_parent(["td", "th"]):
            return "<br>"
        return super().convert_br(el, text, parent_tags)

    def convert_div(self, el, text, parent_tags):
        if "custom-block" in el.get("class", []):
            return "\n\n" + "\n".join(("> " + line).rstrip() for line in text.strip().splitlines()) + "\n\n"
        return super().convert_div(el, text, parent_tags)

    def convert_summary(self, el, text, parent_tags):
        return "\n\n**" + text.strip() + "**\n\n"


def parse_page(data, url):
    soup = BeautifulSoup(data.decode("utf-8"), "html.parser")
    content = soup.select_one("main .theme-default-content")
    if content is None or content.find("h1") is None:
        raise ValueError(f"Missing document body: {url}")
    title = content.h1.get_text(" ", strip=True).removeprefix("#").strip()
    updated = soup.select_one(".last-updated .time")
    return {
        "url": url,
        "path": str(local_path(url)),
        "title": title,
        "upstream_last_updated": updated.get_text(strip=True) if updated else None,
        "html_sha256": digest(data),
        "content": content,
    }


def document_links(content, url):
    for link in content.select("a[href]"):
        target = urldefrag(urljoin(url, link["href"]))[0]
        parsed = urlsplit(target)
        if parsed.netloc == urlsplit(BASE).netloc and parsed.path.startswith(PREFIX):
            if parsed.path.endswith(("/", ".html")):
                yield target


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def normalize_anchor(value):
    return re.sub(r"[\W_]+", "", unquote(value).casefold())


def prepare_images(page, image_references, inline_images):
    for image in page["content"].select("img[src]"):
        if image["src"].startswith("data:"):
            # The official site embeds its feedback QR code instead of serving
            # it at a standalone image URL. Link to the original page rather
            # than inventing a URL or embedding image bytes in Markdown.
            alt = image.get("alt") or "内嵌图片"
            link = BeautifulSoup("", "html.parser").new_tag("a", href=page["url"])
            link["data-upstream-image"] = "true"
            link.string = f"{alt}（图片见官方原文）"
            image.replace_with(link)
            inline_images.append({"page": page["path"], "alt": alt, "source_page": page["url"]})
        else:
            url = urljoin(page["url"], image["src"])
            image["src"] = quote(url, safe="/#%:@?=&+,$;~!*'{}")
            image_references.setdefault(url, set()).add(page["path"])


def render_page(page, known_paths, known_ids, captured_at, link_changes, unresolved):
    content = page["content"]
    for node in content.select(".header-anchor, .line-numbers-wrapper, .sr-only, svg, script, style"):
        node.decompose()
    # Preserve VuePress's original IDs, including slugs that differ from GitHub's.
    seen_ids = set()
    for element in list(content.select("[id]")):
        if element["id"] in seen_ids:
            del element["id"]
            continue
        seen_ids.add(element["id"])
        if element.name == "a" and not element.get("href"):
            continue
        anchor = BeautifulSoup("", "html.parser").new_tag("a", id=element["id"])
        element.insert_before(anchor)
    current = PurePosixPath(page["path"])
    for link in content.select("a[href]"):
        if link.get("data-upstream-image"):
            continue
        absolute = urljoin(page["url"], link["href"])
        target, fragment = urldefrag(absolute)
        if target in known_paths:
            resolved = unquote(fragment)
            target_ids = known_ids[known_paths[target]]
            if fragment and resolved not in target_ids:
                matches = [anchor for anchor in target_ids
                           if normalize_anchor(anchor) == normalize_anchor(fragment)]
                if len(matches) == 1:
                    resolved = matches[0]
                    link_changes.append({"page": page["path"], "original": absolute,
                                         "local_target": known_paths[target] + "#" + resolved})
                else:
                    unresolved.append({"page": page["path"], "url": absolute,
                                       "reason": "Anchor not found in the upstream document"})
                    link["href"] = quote(absolute, safe="/#%:@?=&+,$;~!*'{}")
                    continue
            relative = os.path.relpath(known_paths[target], str(current.parent))
            link["href"] = quote(relative + ("#" + resolved if fragment else ""),
                                 safe="/#%:@?=&+,$;~!*'{}")
        elif not link["href"].startswith("#"):
            link["href"] = quote(absolute, safe="/#%:@?=&+,$;~!*'{}")
    body = Converter(
        heading_style="ATX", bullets="-", wrap=False, autolinks=False,
        escape_underscores=False, keep_inline_images_in=["td", "th", "p", "a"],
    ).convert_soup(content).strip()
    header = (
        "<!-- Generated by scripts/sync_qqbot_docs.py; edit the sync script, not this snapshot. -->\n\n"
        f"> 来源：[{page['title']}]({page['url']})<br>\n"
        f"> 抓取时间（UTC）：{captured_at}<br>\n"
        f"> 官网标注的上次更新时间：{page['upstream_last_updated'] or '未提供'}（原样保留）\n\n"
    )
    return header + body + "\n"


def write_catalog(pages, captured_at, unavailable, unresolved):
    groups = [
        ("入口与变更记录", lambda p: "/" not in p or p == "autogen/index.md"),
        ("起步指南、鉴权与事件连接", lambda p: p.startswith("dev-prepare/")),
        ("接口参考", lambda p: p.startswith("autogen/api/")),
        ("事件参考", lambda p: p.startswith("autogen/event/")),
        ("消息收发、类型与交互", lambda p: p.startswith("server-inter/message/")),
        ("机器人与用户", lambda p: p.startswith("server-inter/user/")),
        ("群聊管理", lambda p: p.startswith("server-inter/group/")),
        ("菜单与面板", lambda p: p.startswith("server-inter/menu-panel/")),
        ("频道管理", lambda p: p.startswith("server-inter/channel/")),
        ("补充接口、模型与错误码", lambda p: p.startswith(("openapi/", "gateway/"))),
    ]
    lines = [
        "# QQ 机器人 API v2 官方文档快照", "",
        f"来源：[QQ 机器人官方文档]({BASE})。抓取时间：{captured_at}（UTC）。共 {len(pages)} 页。", "",
        "本目录保存官网已部署页面的正文，保留原文、表格、代码示例和原始标题锚点；"
        "站内 API v2 链接已改为本地 Markdown 链接，正文图片直接使用官网提供的 URL，加载图片需要联网。"
        "官网内嵌且没有独立 URL 的图片改为查看官方原文的链接。", "",
        "目录沿用官方 URL 的层级，目录入口保存为 `index.md`。`autogen/api/` 和 `autogen/event/` "
        "分别是官网的接口、事件参考；`server-inter/` 保存场景说明和频道接口；"
        "`openapi/`、`gateway/` 保留官网仍部署的补充页面。部分官方目录页只有标题，按原样保存。", "",
        "`manifest.json` 记录每页来源、官网更新时间、内容哈希、站点配置来源、官方图片 URL 与链接校正记录。"
        "官网的更新时间未注明时区，保持原始显示值。", "",
        "这是外部官方资料归档，内容权利归原作者所有，不属于本项目原创 SDK 文档，"
        "不适用项目代码的 MIT 许可证。开发时请结合来源页确认最新规则。", "",
        "## 更新方式", "", "在项目根目录执行（需安装 uv，Python 3.9+）：", "", "```sh",
        "uv run --locked scripts/sync_qqbot_docs.py", "```", "",
        "文档工具依赖使用 [uv 脚本依赖管理](https://docs.astral.sh/uv/guides/scripts/#declaring-script-dependencies)："
        "声明保存在脚本开头的 PEP 723 元数据中，直接与间接依赖版本锁定在 "
        "`scripts/sync_qqbot_docs.py.lock`，运行时由 uv 自动准备环境。", "",
        "同步脚本从官方 VuePress 路由配置提取所有 API v2 页面，并补充正文中发现的同目录链接。"
        "原始 HTML 和路由配置缓存在已忽略的 `.cache/qqbot-docs/`，图片不下载到项目。"
        "已有缓存时可离线重新生成 Markdown：", "", "```sh",
        "uv run --locked scripts/sync_qqbot_docs.py --offline", "```", "",
        "这里的 `--offline` 是脚本参数，仅控制文档抓取；正文图片仍使用在线 URL。"
        "管理脚本依赖可用 `uv add --script scripts/sync_qqbot_docs.py <包名>`；"
        "更新锁文件可用 `uv lock --script scripts/sync_qqbot_docs.py`。", "",
        "## 文档目录", "",
    ]
    if unavailable or unresolved:
        lines += [f"> 官网正文中有 {len(unavailable)} 个链接目标不可用，另有 {len(unresolved)} 处锚点无法匹配；"
                  "这些链接保留官网地址，未生成替代内容。能唯一匹配的大小写或分隔符差异已校正。"
                  "详情见 `manifest.json` 的 `unavailable_pages`、`unresolved_anchors` 和 `normalized_links`。", ""]
    listed = set()
    for title, belongs in groups:
        selected = [p for p in pages if p["path"] not in listed and belongs(p["path"])]
        if not selected:
            continue
        lines += [f"### {title}", ""]
        for page in selected:
            lines.append(f"- [{page['title']}]({page['path']}) — `{page['path']}`")
            listed.add(page["path"])
        lines.append("")
    if len(listed) != len(pages):
        raise ValueError("Uncategorized pages in catalog")
    write_text(OUTPUT / "README.md", "\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Rebuild from cached HTTP responses; images retain online URLs")
    parser.add_argument("--cache-dir", type=Path, default=PROJECT / ".cache/qqbot-docs")
    args = parser.parse_args()
    downloader = Downloader(args.cache_dir, args.offline)
    previous = {}
    if (OUTPUT / "manifest.json").exists():
        previous = json.loads((OUTPUT / "manifest.json").read_text())
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if args.offline and (OUTPUT / "manifest.json").exists():
        captured_at = previous["captured_at"]
    root, _ = downloader.fetch(BASE)
    root_soup = BeautifulSoup(root.decode("utf-8"), "html.parser")
    app_url = next(urljoin(BASE, s["src"]) for s in root_soup.select("script[src]")
                   if re.search(r"/app\.[^/]+\.js$", s["src"]))
    app, _ = downloader.fetch(app_url)
    routes = set(re.findall(r'path:"(/develop/api-v2/[^"\n]*)",component:', app.decode("utf-8")))
    if not routes:
        raise ValueError("No API v2 routes found; the upstream site structure may have changed")
    route_urls = {urljoin(BASE, "/wiki" + route) for route in routes}
    pending = set(route_urls)
    pages = {}
    unavailable = {}
    print(f"Discovered {len(pending)} API v2 routes", flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        while pending:
            batch = {pool.submit(downloader.fetch, url): url for url in sorted(pending)}
            pending = set()
            for future in as_completed(batch):
                url = batch[future]
                try:
                    data, _ = future.result()
                except (OSError, URLError) as error:
                    if url in route_urls:
                        raise
                    unavailable[url] = str(error)
                    continue
                if url not in route_urls and digest(data) == digest(root):
                    unavailable[url] = "The server returns the API landing page for this missing document"
                    continue
                pages[url] = parse_page(data, url)
                if len(pages) % 25 == 0:
                    print(f"Fetched {len(pages)} pages", flush=True)
            for page in pages.values():
                pending.update(link for link in document_links(page["content"], page["url"])
                               if link not in pages and link not in unavailable)
    ordered = sorted(pages.values(), key=lambda p: p["path"])
    known_paths = {p["url"]: p["path"] for p in ordered}
    known_ids = {p["path"]: {el["id"] for el in p["content"].select("[id]")}
                 for p in ordered}
    for page in ordered:
        if page["url"].endswith("/"):
            known_paths[page["url"] + "index.html"] = page["path"]
        known_paths[page["url"].removesuffix(".html") + ".md"] = page["path"]
    image_references, inline_images = {}, []
    link_changes, unresolved = [], []
    for page in ordered:
        prepare_images(page, image_references, inline_images)
        text = render_page(page, known_paths, known_ids, captured_at, link_changes, unresolved)
        write_text(OUTPUT / page["path"], text)
        page["markdown_sha256"] = digest(text.encode("utf-8"))
    write_catalog(ordered, captured_at, unavailable, unresolved)
    manifest = {
        "source": BASE, "captured_at": captured_at,
        "route_bundle": {"url": app_url, "sha256": digest(app)},
        "route_count": len(routes), "page_count": len(ordered),
        "pages": [{k: v for k, v in p.items() if k != "content"} for p in ordered],
        "image_mode": "remote",
        "images": [{"url": url, "pages": sorted(refs)} for url, refs in sorted(image_references.items())],
        "inline_images": inline_images,
        "unavailable_pages": [{"url": url, "reason": reason} for url, reason in sorted(unavailable.items())],
        "normalized_links": link_changes, "unresolved_anchors": unresolved,
    }
    write_text(OUTPUT / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    # Remove only files managed by the preceding successful snapshot. In
    # particular, missing URLs must not keep obsolete landing-page copies.
    current_files = {p["path"] for p in ordered}
    previous_files = {p["path"] for p in previous.get("pages", [])}
    previous_files.update(a["path"] for a in previous.get("assets", []))
    for relative in previous_files - current_files:
        stale = (OUTPUT / relative).resolve()
        if OUTPUT.resolve() in stale.parents and stale.is_file():
            stale.unlink()
    assets_dir = OUTPUT / "assets"
    if assets_dir.is_dir() and not any(assets_dir.iterdir()):
        assets_dir.rmdir()
    print(f"Saved {len(ordered)} Markdown pages with {len(image_references)} official image URLs; "
          f"{len(inline_images)} inline image references link to source pages. Output: {OUTPUT}", flush=True)


if __name__ == "__main__":
    main()
