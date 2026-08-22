#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_translation_coverage.py

index.html 内にある「日本語を含む多言語配列」を全て洗い出し、
LANGS(現在5言語: 日本語/英語/インドネシア語/タガログ語/タイ語)の要素数と
一致していないものを検出するツール。

check_ruby_coverage.py が「ふりがな・読み上げ」の抜けを見るのに対し、
このツールは「翻訳そのものが特定言語だけ抜けている」バグを見る。
(例: CATやSUBJECTのようなUI用オブジェクトにタイ語だけ追加し忘れる、等)

対象となるパターン:
  1. 平坦な配列: ["日本語","English",...]  (T{}, CAT, SUBJECT 等)
  2. ネスト配列: "o":[["日本語",...],["日本語",...]] (問題データの選択肢)
  3. q/p/e フィールド: "q":["日本語",...]

対象外:
  - シングルクォート配列(現状のindex.htmlでは未使用だが、一応チェックする)
  - 言語コードをキーにしたオブジェクト形式 { ja:"...", en:"..." } は
    LANG_LABEL 等ごく一部にしか使われていないため、個別に目視確認すること
    (このツールは自動検出しない)

【使い方】
    python3 check_translation_coverage.py index.html

【N3以降への拡張時の運用】
    check_ruby_coverage.py とあわせて、新しい問題データやUI文言を
    追加するたびに実行する。1件でも指摘があれば、該当言語の翻訳を追記する。
"""

import re
import sys


def get_langs_count(html_text: str) -> int:
    """LANGS配列の要素数を取得する(現状5言語)。"""
    m = re.search(r'const LANGS = \[(.*?)\]', html_text)
    if not m:
        raise ValueError("LANGS 配列が見つかりませんでした。index.html の構造が変わっていないか確認してください。")
    return len(re.findall(r'"[^"]*"', m.group(1)))


def find_flat_arrays(js_text: str, expected_len: int):
    """日本語を含む平坦な配列(ダブルクォート/シングルクォート)を検出する。"""
    bad = []

    dq_pattern = re.compile(r'\[\s*((?:"(?:[^"\\]|\\.)*"\s*,\s*){1,19}"(?:[^"\\]|\\.)*")\s*\]')
    for m in dq_pattern.finditer(js_text):
        items = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
        if items and re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', items[0]):
            if len(items) != expected_len:
                bad.append(("flat(\")", len(items), items[0][:40]))

    sq_pattern = re.compile(r"\[\s*((?:'(?:[^'\\]|\\.)*'\s*,\s*){1,19}'(?:[^'\\]|\\.)*')\s*\]")
    for m in sq_pattern.finditer(js_text):
        items = re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(1))
        if items and re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', items[0]):
            if len(items) != expected_len:
                bad.append(("flat(')", len(items), items[0][:40]))

    return bad


def split_items(block: str):
    """{ ... } 単位でトップレベルのアイテムに分割する(簡易な深さカウント方式)。"""
    items = []
    depth = 0
    buf = ""
    started = False
    for ch in block:
        if ch == "{":
            depth += 1
            started = True
        if started:
            buf += ch
        if ch == "}":
            depth -= 1
            if depth == 0 and started:
                items.append(buf)
                buf = ""
                started = False
    return items


def find_data_block(html_text: str) -> str:
    start_marker = "const DATA_MOJI = ["
    end_marker = "function tr(arr)"
    if start_marker not in html_text or end_marker not in html_text:
        return ""
    start = html_text.index(start_marker)
    end = html_text.index(end_marker)
    return html_text[start:end]


def find_question_data_issues(data_block: str, expected_len: int):
    """q/p/e フィールドと o(ネスト選択肢)の要素数をチェックする。"""
    bad = []
    items = split_items(data_block)
    for it in items:
        for field in ("q", "p", "e"):
            fm = re.search(rf'"{field}"\s*:\s*\[((?:"(?:[^"\\]|\\.)*",?\s*){{1,19}})\]', it)
            if fm:
                n = len(re.findall(r'"(?:[^"\\]|\\.)*"', fm.group(1)))
                if n != expected_len:
                    bad.append((field, n, it[:50]))

        om = re.search(
            r'"o"\s*:\s*\[((?:\[(?:"(?:[^"\\]|\\.)*",?\s*){1,19}\],?\s*){1,19})\]', it
        )
        if om:
            for opt in re.finditer(r'\[((?:"(?:[^"\\]|\\.)*",?\s*){1,19})\]', om.group(1)):
                n = len(re.findall(r'"(?:[^"\\]|\\.)*"', opt.group(1)))
                if n != expected_len:
                    bad.append(("o-option", n, it[:50]))
    return bad


def main():
    if len(sys.argv) != 2:
        print("使い方: python3 check_translation_coverage.py <index.htmlのパス>")
        sys.exit(1)

    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        html_text = f.read()

    expected_len = get_langs_count(html_text)
    print(f"LANGS 要素数(想定言語数): {expected_len}")
    print()

    scripts = re.findall(r"<script>(.*?)</script>", html_text, re.S)
    js_text = "\n".join(scripts)

    flat_issues = find_flat_arrays(js_text, expected_len)
    print(f"[平坦な配列(T{{}}/CAT/SUBJECT等)] 検査結果")
    if not flat_issues:
        print("  OK: 想定言語数と異なる配列はありません。")
    else:
        print(f"  NG: {len(flat_issues)}件")
        for kind, n, sample in flat_issues:
            print(f"    [{kind}] 要素数{n} (期待値{expected_len})  例: {sample}")
    print()

    data_block = find_data_block(html_text)
    qpe_issues = find_question_data_issues(data_block, expected_len) if data_block else []
    print(f"[問題データ(q/p/e/o)] 検査結果")
    if not qpe_issues:
        print("  OK: 想定言語数と異なるフィールドはありません。")
    else:
        print(f"  NG: {len(qpe_issues)}件")
        for field, n, sample in qpe_issues[:30]:
            print(f"    [{field}] 要素数{n} (期待値{expected_len})  例: {sample}")
    print()

    total_bad = len(flat_issues) + len(qpe_issues)
    if total_bad == 0:
        print("OK: 全体OK。全ての多言語配列がLANGSの言語数と一致しています。")
        print()
        print("注記: { ja:\"...\", en:\"...\" } のようなオブジェクト形式の言語マッピングは")
        print("      自動検出の対象外です(現状 LANG_LABEL のみ使用、目視確認済み)。")
        sys.exit(0)
    else:
        print("-> 上記の配列に不足している言語の翻訳を追記してください。")
        sys.exit(1)


if __name__ == "__main__":
    main()
