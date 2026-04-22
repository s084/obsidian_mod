"""
Clippings フォルダ内の Markdown について、YAML フロントマターに基づき
ファイル名の先頭に識別用プレフィックスを付与する。

設定は config/clip_prefix_rules.csv（--config で変更可）。
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

DEFAULT_VAULT = Path(r"C:\Users\yohm\iCloudDrive\iCloud~md~obsidian\My_vault")
DEFAULT_CLIPPINGS = "Clippings"
DEFAULT_CONFIG = Path(__file__).resolve().parent / "config" / "clip_prefix_rules.csv"

FRONTMATTER_RE = re.compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*(\r?\n|$)",
    re.DOTALL,
)

# https://arxiv.org/abs/... or /pdf/ or /html/
ARXIV_ID_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf|html)/([^/?#]+)(?:\.pdf)?",
    re.IGNORECASE,
)

# Windows でファイル名に使えない文字
WIN_INVALID = r'<>:"/\\|?*'


@dataclass
class SiteRow:
    site_id: str
    url_substring: str
    abbrev: str
    format: str


@dataclass
class AuthorRow:
    site_id: str
    author_match: str
    title_match: str
    abbrev: str


@dataclass
class Rules:
    sites: list[SiteRow] = field(default_factory=list)
    authors: list[AuthorRow] = field(default_factory=list)

    def site_for_url(self, url: str) -> SiteRow | None:
        u = (url or "").lower()
        for s in self.sites:
            if s.url_substring.lower() in u:
                return s
        return None


def load_rules(path: Path) -> Rules:
    rules = Rules()
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            kind = (row.get("kind") or "").strip().lower()
            if kind == "site":
                rules.sites.append(
                    SiteRow(
                        site_id=row["site_id"].strip(),
                        url_substring=row["url_substring"].strip(),
                        abbrev=(row.get("abbrev") or "").strip(),
                        format=(row.get("format") or "").strip(),
                    )
                )
            elif kind == "author":
                rules.authors.append(
                    AuthorRow(
                        site_id=row["site_id"].strip(),
                        author_match=(row.get("author_match") or "").strip(),
                        title_match=(row.get("title_match") or "").strip(),
                        abbrev=(row.get("abbrev") or "").strip(),
                    )
                )
    return rules


def parse_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None, text
    body = m.group(1)
    try:
        data = yaml.safe_load(body) or {}
        if not isinstance(data, dict):
            return None, text
        return data, text[m.end() :]
    except yaml.YAMLError:
        return None, text


def get_source_url(meta: dict[str, Any]) -> str:
    for key in ("source", "url", "link", "canonical"):
        v = meta.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _wikilink_plain(s: str) -> str:
    s = s.strip()
    m = re.match(r"^\[\[([^\]]+)\]\]$", s)
    if m:
        return m.group(1).strip()
    return s


def get_author(meta: dict[str, Any]) -> str:
    for key in ("author", "channel", "by", "uploader", "source_channel"):
        a = meta.get(key)
        if isinstance(a, str) and a.strip():
            return _wikilink_plain(a)
        if isinstance(a, list) and a:
            parts: list[str] = []
            for item in a:
                if isinstance(item, str) and item.strip():
                    parts.append(_wikilink_plain(item))
            if parts:
                return " ".join(parts)
    return ""


def get_title(meta: dict[str, Any]) -> str:
    t = meta.get("title")
    if isinstance(t, str) and t.strip():
        return t.strip()
    return ""


def _eight_digits_to_yyyymmdd(d8: str) -> str | None:
    if len(d8) < 8:
        return None
    y, m, d = int(d8[:4]), int(d8[4:6]), int(d8[6:8])
    if 1990 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
        return f"{y:04d}{m:02d}{d:02d}"
    m, d, y = int(d8[:2]), int(d8[2:4]), int(d8[4:8])
    if 1990 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
        return f"{y:04d}{m:02d}{d:02d}"
    return None


def published_to_yyyymmdd(published: Any) -> str | None:
    if published is None:
        return None
    if isinstance(published, datetime):
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        return published.astimezone(timezone.utc).strftime("%Y%m%d")
    if type(published) is date:
        return published.strftime("%Y%m%d")
    if isinstance(published, (int, float)):
        t = int(published)
        if t > 10_000_000_000:  # unix ms
            t //= 1000
        if t > 1_000_000_000:  # unix s
            return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y%m%d")
        return None
    s = str(published).strip()
    if not s:
        return None
    s_z = s.replace("Z", "+00:00") if s.endswith("Z") else s
    for cand in (s_z, s_z[:19], s_z[:10]):
        if len(cand) < 4:
            continue
        try:
            dt = datetime.fromisoformat(cand)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y%m%d")
    for fmt, ln in (
        ("%Y-%m-%d", 10),
        ("%Y/%m/%d", 10),
        ("%m/%d/%Y", 10),
        ("%d/%m/%Y", 10),
        ("%Y-%m-%dT%H:%M:%S", 19),
    ):
        try:
            return datetime.strptime(s[:ln], fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    # 8 桁（YYYYMMDD / MMDDYYYY の曖昧さをヒューリスティック解決 — 年が四桁目側にあるかで判定）
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 8:
        return _eight_digits_to_yyyymmdd(digits[:8])
    return None


def extract_arxiv_id(text: str) -> str | None:
    m = ARXIV_ID_RE.search(text)
    if m:
        return m.group(1)
    m = re.search(
        r"\b(\d{4}\.\d{4,5}(?:v\d+)?)\b",
        text,
    )
    if m:
        return m.group(1)
    return None


def arxiv_id_from_stem(stem: str) -> str | None:
    """ファイル名先頭例: 2603.03555v1_ タイトル / 2603.03555v1 タイトル"""
    m = re.match(
        r"^(\d{4}\.\d{4,5}(?:v\d+)?)(?:_|\s+|$)",
        stem.strip(),
    )
    if m:
        return m.group(1)
    return None


def resolve_youtube_abbrev(rules: Rules, author: str, title: str = "") -> str | None:
    """author の最長一致で層（tier）を決め、同一層では CSV 順に title_match を評価する。"""
    if not author:
        return None
    low = author.lower()
    cands: list[AuthorRow] = []
    for a in rules.authors:
        if a.site_id != "youtube" or not a.author_match:
            continue
        if a.author_match.lower() in low:
            cands.append(a)
    if not cands:
        return None
    best_len = max(len(x.author_match) for x in cands)
    tier = [a for a in cands if len(a.author_match) == best_len]
    tlow = (title or "").lower()
    for a in rules.authors:
        if a not in tier:
            continue
        if a.title_match and tlow and a.title_match.lower() in tlow:
            return a.abbrev or None
    for a in rules.authors:
        if a in tier and not a.title_match:
            return a.abbrev or None
    return None


def build_prefix(
    rules: Rules,
    site: SiteRow,
    meta: dict[str, Any],
    source_url: str,
    file_stem: str = "",
) -> str | None:
    fmt = site.format
    if fmt == "code_date":
        d = published_to_yyyymmdd(meta.get("published") or meta.get("date") or meta.get("created"))
        if not d or not site.abbrev:
            return None
        return f"{site.abbrev} {d}_ "

    if fmt == "arxiv_id":
        cands: list[str] = []
        for t in (source_url, str(meta.get("title", ""))):
            a = extract_arxiv_id(t)
            if a:
                cands.append(a)
        if isinstance(meta.get("arxiv"), str):
            a = extract_arxiv_id(meta["arxiv"])
            if a:
                cands.append(a)
        a = arxiv_id_from_stem(file_stem) if file_stem else None
        if a:
            cands.append(a)
        if not cands:
            return None
        # 同一論文の v 付き ID を v なしより優先
        def _arxiv_rank(x: str) -> tuple[int, int]:
            has_v = 1 if re.search(r"v\d", x) else 0
            return (has_v, len(x))

        aid = max(set(cands), key=_arxiv_rank)
        return f"{aid}_ "

    if fmt == "author_date":
        auth = get_author(meta)
        ab = resolve_youtube_abbrev(rules, auth, get_title(meta))
        if not ab:
            return None
        d = published_to_yyyymmdd(meta.get("published") or meta.get("date") or meta.get("uploadDate"))
        if not d:
            return None
        return f"{ab} {d}_ "

    return None


def already_has_identification_prefix(
    stem: str,
    site: SiteRow,
    rules: Rules,
    prefix: str,
    meta: dict[str, Any],
) -> bool:
    """同じ種類の識別接頭辞が先頭に付いていれば True（重複付与を避ける）。"""
    if stem.startswith(prefix):
        return True
    if site.format == "arxiv_id" and arxiv_id_from_stem(stem):
        return True
    if site.format == "code_date" and site.abbrev and re.match(
        rf"^{re.escape(site.abbrev)} \d{{8}}_ +",
        stem,
        re.IGNORECASE,
    ):
        return True
    if site.format == "author_date":
        ab = resolve_youtube_abbrev(rules, get_author(meta), get_title(meta))
        if ab and re.match(rf"^{re.escape(ab)} \d{{8}}_ +", stem, re.IGNORECASE):
            return True
    return False


def build_strip_prefixes_pattern(rules: Rules) -> re.Pattern[str]:
    """既に付いた識別プレフィックス（ code_date / author_date / arxiv ）を 1 段ずつ取り除く。"""
    code_parts: list[str] = []
    for s in rules.sites:
        if s.format == "code_date" and s.abbrev:
            a = re.escape(s.abbrev)
            code_parts.append(rf"(?:{a} \d{{8}}_ +)")
    for a in {x.abbrev for x in rules.authors if x.abbrev}:
        code_parts.append(rf"(?:{re.escape(a)} \d{{8}}_ +)")
    # arXiv: 2603.03555v1_ のような形式
    code_parts.append(r"(?:\d{4}\.\d{4,5}(?:v\d+)?_ +)")
    if not code_parts:
        return re.compile(r"^()")
    return re.compile("^(" + "|".join(code_parts) + ")+", re.IGNORECASE)


def strip_stacked_prefixes(name: str, pat: re.Pattern[str]) -> str:
    s = name
    while True:
        nxt = pat.sub("", s, count=1)
        if nxt == s:
            break
        s = nxt
    return s.lstrip()


def sanitize_stem(s: str) -> str:
    for ch in WIN_INVALID:
        s = s.replace(ch, " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def run(
    clippings: Path,
    config: Path,
    dry_run: bool,
) -> int:
    if not config.is_file():
        print(f"設定が見つかりません: {config}", file=sys.stderr)
        return 1
    if not clippings.is_dir():
        print(f"Clippings フォルダが見つかりません: {clippings}", file=sys.stderr)
        return 1

    rules = load_rules(config)
    strip_pat = build_strip_prefixes_pattern(rules)

    md_files = sorted(clippings.glob("*.md"))
    n_ok = 0
    n_skip = 0

    for path in md_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        meta, _ = parse_frontmatter(text)
        if not meta:
            print(f"[skip] フロントマターなし: {path.name}")
            n_skip += 1
            continue

        url = get_source_url(meta)
        site = rules.site_for_url(url)
        if not site:
            u = (url[:80] if url else "")
            print(f"[skip] 対象サイトではない: {path.name} source={u!r}")
            n_skip += 1
            continue

        prefix = build_prefix(rules, site, meta, url, path.stem)
        if not prefix:
            print(f"[skip] プレフィックス未決定: {path.name} (site={site.site_id})")
            n_skip += 1
            continue

        if already_has_identification_prefix(path.stem, site, rules, prefix, meta):
            print(f"[ok] 接頭辞済み（再付与なし）: {path.name}")
            n_ok += 1
            continue

        base = path.stem
        ext = path.suffix
        if base.startswith(prefix):
            rest = base[len(prefix) :]
        else:
            rest = strip_stacked_prefixes(base, strip_pat)
        while rest and rest[0] in " _":
            rest = rest[1:].lstrip()

        new_stem = prefix + (rest or sanitize_stem(base) or "untitled")
        new_stem = sanitize_stem(new_stem)
        new_name = new_stem + ext

        if new_name == path.name:
            print(f"[ok] 変更なし: {path.name}")
            n_ok += 1
            continue

        dest = path.with_name(new_name)
        if dest.exists() and dest.resolve() != path.resolve():
            print(f"[skip] 先が既に存在: {path.name} -> {new_name}")
            n_skip += 1
            continue

        if dry_run:
            print(f"[dry-run] {path.name!r} -> {new_name!r}")
        else:
            path.rename(dest)
            print(f"[重命名] {path.name!r} -> {new_name!r}")
        n_ok += 1

    print(f"完了: 処理 {n_ok} / スキップ {n_skip} / 合計 {len(md_files)}")
    return 0


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if reconf is not None:
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main() -> int:
    _configure_stdout()
    p = argparse.ArgumentParser(description="Clippings の Markdown に YAML 基準のプレフィックスを付与")
    p.add_argument(
        "--vault",
        type=Path,
        default=DEFAULT_VAULT,
        help=f"Obsidian ボールト (既定: {DEFAULT_VAULT})",
    )
    p.add_argument(
        "--clippings",
        type=str,
        default=DEFAULT_CLIPPINGS,
        help="ボールト内の Clippings 相対パス",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="clip_prefix_rules.csv",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="リネームせず表示のみ",
    )
    args = p.parse_args()
    clippings = (args.vault / args.clippings).resolve()
    return run(clippings, args.config.resolve(), args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
