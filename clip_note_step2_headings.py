"""
Clippings 等のメモ内で、### ステップ2（または ### N) ステップ2：…）から
### ステップ3（同様）までの区間について、
見出し行と判断した行を **...** から ### ... に置き換える。

判定の考え方（意図）:
- 1 行が ** だけの「強調」に見えても、本当の見出しは note 記事案側で**共通フォーマット**
  になっている想定。フォーマットと合わない行は見出しにしない（強調のまま残す）。
- サンプル未確定の間は、太字1行（BOLD_ONLY_LINE 一致）を見出し候補とし、
  _inner_matches_note_heading_format では何も弾かない。フォーマットが分かり次第ここに追記。

ファイルはパス、または Clippings フォルダ内のファイル名で指定。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_VAULT = Path(r"C:\Users\yohm\iCloudDrive\iCloud~md~obsidian\My_vault")
DEFAULT_CLIPPINGS = "Clippings"

BOLD_ONLY_LINE = re.compile(r"^\s*\*\*(.+?)\*\*\s*$")
# 「### ステップ2」だけでなく「### 2) ステップ2：…」のような番号付き見出しも対象にする
STEP2 = re.compile(r"^###\s*(?:\d+\)\s*)?ステップ2")
STEP3 = re.compile(r"^###\s*(?:\d+\)\s*)?ステップ3")


def _inner_matches_note_heading_format(inner: str) -> bool:
    """BOLD_ONLY_LINE のグループ1（** の内側）が、note 記事案の「見出し行」用フォーマットに合致するか。

    合致しなければ False（行は ### にしない）。強調1行の誤爆を減らす用。
    現状: 候補は全通過。具体例（プレフィックス、長さ、禁止パターン等）が揃い次第、ここで絞る。
    """
    return True


def resolve_file(arg: str) -> Path:
    p = Path(arg)
    if p.is_file():
        return p.resolve()
    alt = DEFAULT_VAULT / DEFAULT_CLIPPINGS / arg
    if alt.is_file():
        return alt.resolve()
    print(f"error: not found: {arg}", file=sys.stderr)
    if not p.exists():
        print(f"  (also tried: {alt})", file=sys.stderr)
    sys.exit(1)


def format_step2_block(lines: list[str]) -> tuple[list[str], int]:
    step2 = step3 = None
    for i, line in enumerate(lines):
        core = line.rstrip("\r\n")
        if step2 is None and STEP2.match(core):
            step2 = i
        elif step2 is not None and step3 is None and STEP3.match(core):
            step3 = i
            break
    if step2 is None or step3 is None:
        return lines, 0

    out = list(lines)
    changed = 0
    for i in range(step2 + 1, step3):
        core = out[i].rstrip("\r\n")
        m = BOLD_ONLY_LINE.match(core)
        if not m or not _inner_matches_note_heading_format(m.group(1)):
            continue
        if out[i].endswith("\r\n"):
            nl = "\r\n"
        elif out[i].endswith("\n"):
            nl = "\n"
        else:
            nl = ""
        out[i] = f"### {m.group(1)}{nl}"
        changed += 1
    return out, changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "ステップ2〜3区間: 太字1行のうち note 記事案の見出し形式に合う行を "
            "### に直す（形式チェックは _inner_matches_note_heading_format）。"
        ),
    )
    parser.add_argument(
        "file",
        help="対象 .md へのパス、または My_vault/Clippings 内のファイル名",
    )
    args = parser.parse_args()

    path = resolve_file(args.file)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    new_lines, n = format_step2_block(lines)

    if n == 0:
        print("no changes (no step2/step3 block or no **...** only lines).")
        return 0

    path.write_text("".join(new_lines), encoding="utf-8")
    print(f"ok: {n} line(s) -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
