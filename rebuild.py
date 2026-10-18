# -*- coding: utf-8 -*-
"""一条命令重建 notes 的全部索引页。

    python rebuild.py            # 重建
    python rebuild.py --check    # 只检查是否过期（过期退出码 1，可用于 CI / 提交前检查）

三张索引页，各自的处理方式：

    lectures/index.html         整页生成 —— 每场讲座一张卡片
    getting-started/index.html  只替换 <!-- INDEX:LIST:START --> 区块，页面其余部分保持手写
    index.html（根入口）         只更新两张卡片的「N 场讲座 / N 篇笔记」与「最近更新」

约定
----
1. 讲座文章可在 <head> 里写一行元数据，索引优先读它：

       <!-- lecture-date: 2026-10-16 | lecture-title: 中文标题 | lecture-title-en: English Title -->

   缺失时依次回退到 <title>、文件名、git 提交日期。
2. 标题与摘要都以文章自己的头部为准 —— 想让索引里那一条好看，改文章即可。
3. 两种布局都支持：lectures/*.html（当前扁平结构）或 lectures/<某场讲座>/*.html（历史结构，
   目录里取最大的那个 HTML 当正文）。
4. 以 _ 开头的目录不参与扫描。
5. 三张页面的输出都是确定性的（只写「最近更新」的日期，不写生成时刻），
   所以内容没变时重复运行不会产生任何 diff。
"""
import argparse
import html as html_mod
import os
import re
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
LECTURES = os.path.join(ROOT, "lectures")
GETTING_STARTED = os.path.join(ROOT, "getting-started")

LIST_START = "<!-- INDEX:LIST:START -->"
LIST_END = "<!-- INDEX:LIST:END -->"
DESC_LIMIT = 112
SITE_SUFFIX = re.compile(r"\s*·\s*笔记库\s*$")
ARTICLE_EXT = (".html", ".htm")


# ---------------------------------------------------------------- 基础工具
def read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def clean(text):
    return re.sub(r"\s+", " ", html_mod.unescape(text or "")).strip()


def clip(text, limit=DESC_LIMIT):
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def human_size(n):
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.0f KB" % (n / 1024)
    return "%.1f MB" % (n / 1024 / 1024)


def git_date(path):
    """最后一次提交日期；未跟踪文件或没有 git 时回退到修改时间。"""
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    try:
        r = subprocess.run(
            ["git", "-C", ROOT, "log", "-1", "--format=%cd", "--date=short", "--", rel],
            capture_output=True, text=True, timeout=15,
        )
        stamp = r.stdout.strip()
        if r.returncode == 0 and re.match(r"^\d{4}-\d{2}-\d{2}$", stamp):
            return stamp
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")
    except OSError:
        return ""


def newest(paths):
    dates = [git_date(p) for p in paths if os.path.isfile(p)]
    return max(dates) if dates else ""


def files_under(folder):
    """递归列文件，跳过 _ 开头的目录。"""
    out = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith("_")]
        for n in names:
            out.append(os.path.join(root, n))
    return out


def article_files(folder):
    """集合根目录下的文章（排除 index.html），按文件名排序。"""
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, n) for n in sorted(os.listdir(folder))
            if n.lower().endswith(ARTICLE_EXT)
            and n.lower() != "index.html"
            and os.path.isfile(os.path.join(folder, n))]


# ---------------------------------------------------------------- 元数据
def read_meta(path):
    """返回 {title, title_en, date, desc, tag_title}，读不到的为空。"""
    meta = {"title": "", "title_en": "", "date": "", "desc": "", "tag_title": ""}
    try:
        head = read(path)[:9000]
    except OSError:
        return meta

    m = re.search(r"lecture-date:\s*(\d{4}-\d{2}-\d{2})", head)
    if m:
        meta["date"] = m.group(1)
    m = re.search(r"lecture-title:\s*([^|]+?)\s*(?:\||-->)", head)
    if m:
        meta["title"] = clean(m.group(1))
    m = re.search(r"lecture-title-en:\s*([^|]+?)\s*(?:\||-->)", head)
    if m:
        meta["title_en"] = clean(m.group(1))
    m = re.search(r"<title>(.*?)</title>", head, re.S | re.I)
    if m:
        tag_title = SITE_SUFFIX.sub("", clean(m.group(1)))
        meta["tag_title"] = tag_title
        if not meta["title"]:
            meta["title"] = tag_title
    m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', head, re.S | re.I)
    if m:
        meta["desc"] = clean(m.group(1))
    return meta


def strip_title_prefix(desc, title):
    """摘要常写成「标题：正文」，标题已在卡片里出现过，去掉重复前缀。"""
    if title and desc.startswith(title):
        rest = desc[len(title):].lstrip("：:，, 、-—")
        return rest or desc
    return desc


# ---------------------------------------------------------------- 收集条目
def make_lecture(path):
    href = os.path.relpath(path, LECTURES).replace("\\", "/")
    meta = read_meta(path)
    title = meta["title"] or os.path.splitext(os.path.basename(path))[0]
    return {
        "href": href,
        "tag": href,
        "title": title,
        "title_en": meta["title_en"],
        "date": meta["date"] or git_date(path),
        "desc": clip(strip_title_prefix(meta["desc"], title)),
        "size": human_size(os.path.getsize(path)),
        "mtime": git_date(path),
    }


def lecture_items():
    """讲座条目：支持 lectures/*.html 与 lectures/<dir>/*.html 两种布局。"""
    if not os.path.isdir(LECTURES):
        return []
    items = []
    for name in sorted(os.listdir(LECTURES)):
        path = os.path.join(LECTURES, name)
        if os.path.isdir(path):
            if name.startswith("_"):
                continue
            htmls = [p for p in files_under(path) if p.lower().endswith(ARTICLE_EXT)]
            if htmls:
                # 与旧脚本一致：目录里没有明显「正式版」时，取最大的那个 HTML
                items.append(make_lecture(max(htmls, key=os.path.getsize)))
        elif name.lower().endswith(ARTICLE_EXT) and name.lower() != "index.html":
            items.append(make_lecture(path))
    items.sort(key=lambda it: (it["mtime"], it["date"]), reverse=True)
    return items


def collection_items(folder):
    """入门指南等扁平集合。"""
    items = []
    for path in article_files(folder):
        meta = read_meta(path)
        name = os.path.basename(path)
        title = meta["title"] or os.path.splitext(name)[0]
        items.append({
            "href": name,
            "title": title,
            "desc": clip(strip_title_prefix(meta["desc"], title)),
            "date": meta["date"] or git_date(path),
        })
    return items


# ---------------------------------------------------------------- 讲座索引（整页生成）
LECTURES_CSS = """
  :root{
    --ink:#141a22;--ink-2:#3d4753;--muted:#69737f;--faint:#8d96a1;
    --line:#dfe4ea;--line-2:#c8d0d9;--bg:#eef0f3;--paper:#fff;
    --navy:#1f4e79;--navy-pale:#eef3f9;--teal:#176f68;--teal-pale:#eaf4f2;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font-family:"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif;
       font-size:15px;line-height:1.7;}
  .page{max-width:980px;margin:0 auto;padding:0 20px 72px;}
  .crumbs{font-size:13px;color:var(--faint);margin:22px 0 10px;}
  .crumbs a{color:var(--navy);text-decoration:none;}
  .crumbs a:hover{text-decoration:underline;}
  header.top{background:var(--paper);border:1px solid var(--line);border-radius:12px;
             padding:28px 30px;margin:0 0 18px;box-shadow:0 1px 2px rgba(20,25,40,.05);}
  .kicker{font-family:"Cascadia Mono",Consolas,monospace;font-size:11.5px;letter-spacing:.08em;
          text-transform:uppercase;color:var(--navy);background:var(--navy-pale);
          border-radius:5px;padding:2px 8px;display:inline-block;}
  h1{font-size:26px;margin:12px 0 8px;letter-spacing:-.01em;}
  h1 .en{color:var(--faint);font-size:15px;font-weight:400;margin-left:8px;}
  .sub{color:var(--faint);font-size:13.5px;margin:0;}
  .sub b{color:var(--ink-2);}
  .panel{background:var(--paper);border:1px solid var(--line);border-radius:12px;
         padding:24px 28px;box-shadow:0 1px 2px rgba(20,25,40,.05);}
  .list{margin:0;display:grid;gap:10px;}
  a.item{display:block;background:var(--paper);border:1px solid var(--line);border-radius:10px;
         padding:16px 20px;text-decoration:none;color:inherit;
         transition:border-color .15s,box-shadow .15s;}
  a.item:hover{border-color:var(--navy);box-shadow:0 2px 8px rgba(31,78,121,.10);}
  a.item:focus-visible{outline:2px solid var(--navy);outline-offset:2px;}
  a.item h3{font-size:16px;margin:6px 0 5px;color:var(--navy);line-height:1.45;}
  a.item p{margin:0;font-size:13.4px;color:var(--ink-2);line-height:1.65;}
  .row{margin:0 0 2px;}
  .date{font-family:"Cascadia Mono",Consolas,monospace;font-size:12px;color:var(--navy);
        background:var(--navy-pale);border-radius:5px;padding:1px 8px;letter-spacing:.03em;}
  .foot{margin-top:10px;padding-top:8px;border-top:1px dashed var(--line);
        display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;}
  .foot .tag{font-family:"Cascadia Mono",Consolas,monospace;font-size:11.2px;color:var(--faint);
             word-break:break-all;}
  .foot .size{font-size:11.5px;color:var(--faint);white-space:nowrap;}
  .empty{background:var(--paper);border:1px dashed var(--line-2);border-radius:12px;
         padding:30px;text-align:center;color:var(--muted);font-size:13.5px;}
  footer{margin-top:26px;color:var(--faint);font-size:12.5px;text-align:center;line-height:1.9;}
  footer code{font-family:"Cascadia Mono",Consolas,monospace;font-size:11.8px;
              background:#f4f6f8;border-radius:3px;padding:1px 5px;}
  @media (max-width:720px){header.top,.panel{padding:20px 18px;}h1{font-size:21px;}}
  @media print{
    @page{margin:16mm}
    body{background:#fff;font-size:11pt}
    .page{max-width:none;padding:0}
    a.item,header.top{box-shadow:none;break-inside:avoid}
    .crumbs,footer{display:none}
  }
"""

LECTURES_TMPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="讲座笔记总索引：按场次整理，含日期、主题与原文入口。">
<title>讲座笔记 · 笔记库</title>
<style>__CSS__</style>
</head>
<body>
<div class="page">

  <div class="crumbs"><a href="../index.html">笔记库</a> › 讲座笔记</div>

  <header class="top">
    <span class="kicker">Lectures</span>
    <h1>讲座笔记<span class="en">听课与讲座整理</span></h1>
    <p class="sub">共 <b>__N__</b> 场讲座 · 最近一场 __DATE__</p>
  </header>

  <div class="panel">
    <div class="list">
__ITEMS__
    </div>
  </div>

  <footer>
    本页由 <code>rebuild.py</code> 生成，不要手改；新增或改动讲座后重新运行即可<br>
    文章的日期与标题取自页头 <code>&lt;!-- lecture-date: … | lecture-title: … --&gt;</code> 注释
  </footer>

</div>
</body>
</html>
"""


def render_lecture_card(it):
    title = html_mod.escape(it["title"])
    if it["title_en"]:
        title = "%s　·　%s" % (html_mod.escape(it["title_en"]), title)
    desc = ("\n        <p>%s</p>" % html_mod.escape(it["desc"])) if it["desc"] else ""
    return (
        '      <a class="item" href="%s">\n'
        '        <div class="row"><span class="date">%s</span></div>\n'
        "        <h3>%s</h3>%s\n"
        '        <div class="foot"><span class="tag">%s</span>'
        '<span class="size">%s</span></div>\n'
        "      </a>"
        % (html_mod.escape(it["href"]), html_mod.escape(it["date"] or "未标日期"),
           title, desc, html_mod.escape(it["tag"]), html_mod.escape(it["size"]))
    )


def render_lectures(items):
    if items:
        body = "\n".join(render_lecture_card(it) for it in items)
        date = max(it["date"] for it in items)
    else:
        body = ('      <div class="empty">还没有讲座资料。'
                "在 <code>lectures/</code> 下放一篇 HTML 后重新运行本脚本。</div>")
        date = ""
    return (LECTURES_TMPL
            .replace("__CSS__", LECTURES_CSS)
            .replace("__N__", str(len(items)))
            .replace("__DATE__", date or "—")
            .replace("__ITEMS__", body))


# ---------------------------------------------------------------- 入门指南索引（区块替换）
def render_doc_items(items):
    out = []
    for it in items:
        para = ('\n        <p>%s</p>' % html_mod.escape(it["desc"])) if it["desc"] else ""
        out.append(
            '      <a class="item" href="%s">\n'
            '        <h3>%s<span class="tag">%s</span></h3>%s\n'
            "      </a>"
            % (html_mod.escape(it["href"]), html_mod.escape(it["title"]),
               html_mod.escape(it["href"]), para)
        )
    return "\n".join(out)


def replace_region(text, start, end, body, where):
    if start not in text or end not in text:
        raise SystemExit(
            "%s 里找不到标记：\n  %s\n  %s\n"
            "（第一次使用请手动在「已收录的笔记」列表首尾各放一个标记）" % (where, start, end)
        )
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    return head + start + "\n" + body + "\n    " + end + tail


# ---------------------------------------------------------------- 根入口（计数与日期）
def patch_root(text, n_lec, n_gs, lec_date, gs_date):
    new = re.sub(r"<b>\d+</b> 场讲座", "<b>%d</b> 场讲座" % n_lec, text)
    new = re.sub(r"<b>\d+</b> 篇笔记", "<b>%d</b> 篇笔记" % n_gs, new)

    marker = 'href="getting-started/index.html"'
    if marker in new:
        i = new.index(marker)
        head, tail = new[:i], new[i:]
        if lec_date:
            head = re.sub(r"最近更新 \d{4}-\d{2}-\d{2}", "最近更新 " + lec_date, head)
        if gs_date:
            tail = re.sub(r"最近更新 \d{4}-\d{2}-\d{2}", "最近更新 " + gs_date, tail)
        new = head + tail
    return new


# ---------------------------------------------------------------- 入口
def plans():
    """算出三张页面的目标内容（只在内存里，不落盘）。"""
    items = lecture_items()
    gs_items = collection_items(GETTING_STARTED)

    lec_path = os.path.join(LECTURES, "index.html")
    gs_path = os.path.join(GETTING_STARTED, "index.html")
    root_path = os.path.join(ROOT, "index.html")

    lec_text = render_lectures(items)

    gs_old = read(gs_path) if os.path.isfile(gs_path) else ""
    gs_text = replace_region(gs_old, LIST_START, LIST_END,
                             render_doc_items(gs_items), gs_path) if gs_old else ""

    lec_date = newest([os.path.join(LECTURES, it["href"]) for it in items])
    gs_date = newest([os.path.join(GETTING_STARTED, it["href"]) for it in gs_items])

    root_old = read(root_path) if os.path.isfile(root_path) else ""
    root_text = patch_root(root_old, len(items), len(gs_items),
                           lec_date, gs_date) if root_old else ""

    return [("讲座索引", lec_path, lec_text),
            ("入门指南索引", gs_path, gs_text),
            ("根入口", root_path, root_text)]


def main(argv=None):
    parser = argparse.ArgumentParser(description="重建 notes 的全部索引页")
    parser.add_argument("--check", action="store_true", help="只检查，不写文件；过期时退出码 1")
    args = parser.parse_args(argv)

    targets = plans()
    stale = [label for label, path, text in targets
             if (read(path) if os.path.isfile(path) else None) != text]

    if args.check:
        for label, _, _ in targets:
            print("  %s %s" % ("✗ 需要重建" if label in stale else "✓ 最新    ", label))
        if stale:
            print("\n索引已过期，运行：python rebuild.py")
            return 1
        print("\n三张索引都是最新的。")
        return 0

    print("重建索引：")
    for label, path, text in targets:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        if label in stale:
            write(path, text)
            print("  ✓ 已更新 %s  %s" % (label, rel))
        else:
            print("  – 无变化 %s  %s" % (label, rel))
    n_lec = len(lecture_items())
    n_gs = len(collection_items(GETTING_STARTED))
    print("  统计：%d 场讲座 · %d 篇入门笔记" % (n_lec, n_gs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
