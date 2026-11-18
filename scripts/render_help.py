"""Embed the offline manual and release history in the desktop shell."""

import argparse
from datetime import datetime
from html import escape
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "src/meetingkit/webui/index.html"
START = "<!-- BEGIN offline help -->"
END = "<!-- END offline help -->"


def chapters(path):
    content = path.read_text(encoding="utf-8")
    for part in re.split(r"^## ", content, flags=re.MULTILINE)[1:]:
        title, body = part.split("\n", 1)
        yield title.strip(), body


def paragraphs(body, topic_ids=None):
    html = []
    listing = False
    for line in map(str.strip, body.splitlines()):
        bullet = line.startswith("- ")
        choice = re.fullmatch(r"- \[([^\]]+)\]\(#([^)]+)\) — (.+)", line) if topic_ids else None
        if listing and not bullet:
            html.append("</ul>")
        if not listing and bullet:
            html.append('<ul class="guide-choices">' if choice else "<ul>")
        listing = bullet
        if not line:
            continue
        if choice:
            label, target, description = choice.groups()
            html.append(f'<li><button type="button" data-guide-target="{topic_ids[target]}">'
                        f'<strong>{escape(label)}</strong><span>{escape(description)}</span></button></li>')
            continue
        if bullet:
            tag, line = "li", line[2:]
        elif line.startswith("### "):
            tag, line = "h4", line[4:]
        else:
            tag = "p"
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", escape(line))
        html.append(f"<{tag}>{text}</{tag}>")
    if listing:
        html.append("</ul>")
    return "\n".join(html)


def overlay(name, title, content, subtitle):
    return f'''  <div class="overlay hidden" id="{name}Overlay" role="dialog" aria-modal="true" aria-labelledby="{name}Title">
    <section class="modal help-modal">
      <header class="modal-head"><div><h2 id="{name}Title">{title}</h2><p>{subtitle}</p></div>
        <button class="modal-close" data-close="{name}Overlay" type="button" aria-label="关闭{title}">×</button></header>
      {content}
    </section>
  </div>'''


def render():
    topics, pages = [], []
    manual_chapters = list(chapters(ROOT / "docs/使用说明.md"))
    topic_ids = {title: f"helpTopic{i}" for i, (title, _) in enumerate(manual_chapters)}
    for i, (title, body) in enumerate(manual_chapters):
        name = escape(title)
        current = ' aria-current="true"' if i == 0 else ""
        hidden = "" if i == 0 else " hidden"
        topics.append(f'<button type="button" aria-controls="helpTopic{i}"{current}>{name}</button>')
        pages.append(f'<article id="helpTopic{i}" tabindex="0"{hidden}><h3>{name}</h3>\n{paragraphs(body, topic_ids)}</article>')
    manual = ('<div class="guide-search"><input type="search" id="guideQuery" aria-label="搜索使用说明" '
              'placeholder="搜索功能或问题，例如「粘贴」「麦克风」"></div>\n'
              '<div class="guide-layout"><nav id="guideTopics" aria-label="使用说明目录">\n' +
              "\n".join(topics) + '\n</nav><div class="guide-reading">\n' + "\n".join(pages) +
              '\n<p id="guideNoResults" role="status" hidden>没有匹配的主题，请换一个关键词。</p></div></div>')

    entries = []
    for version_title, body in chapters(ROOT / "CHANGELOG.md"):
        version, status, stamp, title = version_title.split(" · ", 3)
        when = datetime.strptime(stamp, "%Y-%m-%d %H:%M %z")
        entries.append(f'''<details class="release-entry"{"" if entries else " open"}>
<summary><b>{escape(version)}</b><strong>{escape(title)}</strong><span>{escape(status)} <time datetime="{when.isoformat()}">{when:%Y-%m-%d %H:%M}</time></span></summary>
<div>{paragraphs(body)}</div></details>''')
    timeline = '<div class="release-timeline">\n' + "\n".join(entries) + '\n</div>'
    return "\n" + overlay("guide", "使用说明", manual, "选择主题，或搜索操作名称。") + "\n\n" + overlay(
        "changelog", "更新日志", timeline, "所有时间均为北京时间（UTC+8）。展开版本可查看详细改动。") + "\n  "


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    before = SHELL.read_text(encoding="utf-8")
    pre, rest = before.split(START)
    _, post = rest.split(END)
    after = pre + START + render() + END + post
    if args.check and after != before:
        raise SystemExit("Run python scripts/render_help.py to sync the offline help.")
    if after != before:
        SHELL.write_text(after, encoding="utf-8")
