#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_ruby_coverage.py (v2)

index.html 内の RUBY_DICT を使って、実際にアプリ内で「ふりがな表示」または
「音声読み上げ」の対象になる日本語テキストが、変換後も漢字が残っていないか
(=誤読・ふりがな抜けの可能性がないか) を機械的に洗い出すツール。

対象は2系統:
  1. 音声(TTS)対象: 聴解問題の "script" フィールド(常に日本語のみの単一文字列)
  2. 画面表示(ふりがな)対象: 全カテゴリの "q"(問題文) / "p"(長文) / "o"(選択肢)
     の日本語(0番目要素)
     ただし、カテゴリが "hyoki"(漢字書き取り問題)の選択肢は、
     アプリ側の実装で最初からふりがな表示自体を行わない(noFurigana)ため、
     意図的な誤答の当て字であっても対象外とする。

【使い方】
    python3 check_ruby_coverage.py index.html

【N3以降への拡張時の運用】
    新しい問題データを追加するたびに、ビルド後の index.html に対して
    このスクリプトを実行する。「未カバー漢字」が1件でも出たら、
    その漢字を含む単語(活用形も含む)を RUBY_DICT に追記してから公開する。
"""

import re
import sys


def load_ruby_dict(html_text: str) -> dict:
    m = re.search(r'const RUBY_DICT = \{(.*?)\n\};', html_text, re.S)
    if not m:
        raise ValueError("RUBY_DICT が見つかりませんでした。index.html の構造が変わっていないか確認してください。")
    pairs = re.findall(r'"([^"]+)":"([^"]+)"', m.group(1))
    return dict(pairs)


def make_converter(ruby_dict: dict, exclude_substr: str = None):
    ruby_keys = sorted(ruby_dict.keys(), key=lambda k: -len(k))
    if exclude_substr:
        ruby_keys = [k for k in ruby_keys if exclude_substr not in k]

    def convert(text: str) -> str:
        out = []
        i, n = 0, len(text)
        while i < n:
            matched = False
            for key in ruby_keys:
                if text.startswith(key, i):
                    out.append(ruby_dict[key])
                    i += len(key)
                    matched = True
                    break
            if not matched:
                out.append(text[i])
                i += 1
        return "".join(out)

    return convert


def is_kanji(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


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


def extract_script_texts(html_text: str):
    """聴解問題の "script" フィールド(単一文字列)を抽出する。"""
    raws = re.findall(r'"script"\s*:\s*"((?:[^"\\]|\\.)*)"', html_text)
    texts = []
    for raw in raws:
        text = raw.encode().decode("unicode_escape") if "\\" in raw else raw
        texts.append(text)
    return texts


def extract_display_texts(data_block: str):
    """
    q/p/o (画面表示・ふりがな対象)の日本語(0番目要素)を、カテゴリ情報付きで抽出する。
    hyoki カテゴリの選択肢(o)はアプリ側でふりがな非表示のため対象外とする。
    """
    items = split_items(data_block)
    results = []  # (category, field, text)

    for it in items:
        c_m = re.search(r'"c"\s*:\s*"([^"]*)"', it)
        category = c_m.group(1) if c_m else ""

        for field in ("q", "p"):
            fm = re.search(rf'"{field}"\s*:\s*\[\s*"((?:[^"\\]|\\.)*)"', it)
            if fm:
                results.append((category, field, fm.group(1)))

        if category != "hyoki":
            om = re.search(
                r'"o"\s*:\s*\[((?:\[(?:"(?:[^"\\]|\\.)*",?\s*){1,10}\],?\s*){1,10})\]',
                it,
            )
            if om:
                for opt in re.finditer(r'\[\s*"((?:[^"\\]|\\.)*)"', om.group(1)):
                    results.append((category, "o", opt.group(1)))

    return results


def find_data_block(html_text: str) -> str:
    """
    全問題データ(DATA_MOJI 〜 DATA_CHOUKAI_4)を含む範囲を切り出す。
    index.html の構造が変わった場合は、ここの目印文字列を調整すること。
    """
    start_marker = "const DATA_MOJI = ["
    end_marker = "function tr(arr)"
    if start_marker not in html_text or end_marker not in html_text:
        raise ValueError(
            "問題データのブロックが見つかりませんでした。"
            "index.html の構造が変わっていないか確認してください。"
        )
    start = html_text.index(start_marker)
    end = html_text.index(end_marker)
    return html_text[start:end]


def main():
    if len(sys.argv) != 2:
        print("使い方: python3 check_ruby_coverage.py <index.htmlのパス>")
        sys.exit(1)

    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        html_text = f.read()

    ruby_dict = load_ruby_dict(html_text)
    convert_display = make_converter(ruby_dict)
    # 音声(TTS)は「話」を含む単語をあえて漢字のまま渡す仕様(index.html の
    # SPEECH_RUBY_KEYS と同じ例外)。ブラウザの音声エンジンが「が+は」を
    # 主語+助詞(「わ」)と誤認識し「はなす」が「わなす」に聞こえる不具合の対策。
    convert_speech = make_converter(ruby_dict, exclude_substr="話")
    SPEECH_INTENTIONAL_KANJI = {"話", "電"}  # 音声側で意図的に漢字のまま残す文字("話"を含む語の除外に伴い、「電話」の「電」も連動して残る)

    print(f"RUBY_DICT 登録数: {len(ruby_dict)}")
    print()

    script_texts = extract_script_texts(html_text)
    script_leftover = {}
    script_examples = {}
    for text in script_texts:
        converted = convert_speech(text)
        for ch in converted:
            if is_kanji(ch) and ch not in SPEECH_INTENTIONAL_KANJI:
                script_leftover[ch] = script_leftover.get(ch, 0) + 1
                script_examples.setdefault(ch, text[:60])

    print(f"[音声/script] 対象件数: {len(script_texts)}件")
    if not script_leftover:
        print("  OK: 未カバーの漢字はありません。")
    else:
        print(f"  NG: 未カバーの漢字 {len(script_leftover)}種類")
        for ch, cnt in sorted(script_leftover.items(), key=lambda x: -x[1]):
            print(f"    「{ch}」 x{cnt}件  例: {script_examples[ch]}")
    print()

    data_block = find_data_block(html_text)
    display_items = extract_display_texts(data_block)

    display_leftover = {}
    display_examples = {}
    for category, field, text in display_items:
        converted = convert_display(text)
        for ch in converted:
            if is_kanji(ch):
                display_leftover[ch] = display_leftover.get(ch, 0) + 1
                display_examples.setdefault(ch, (text[:50], category, field))

    print(f"[画面表示/q・p・o] 対象件数: {len(display_items)}件 (hyokiカテゴリの選択肢は除外)")
    if not display_leftover:
        print("  OK: 未カバーの漢字はありません。")
    else:
        print(f"  NG: 未カバーの漢字 {len(display_leftover)}種類")
        for ch, cnt in sorted(display_leftover.items(), key=lambda x: -x[1]):
            ex, cat, field = display_examples[ch]
            print(f"    「{ch}」 x{cnt}件  [{cat}/{field}]  例: {ex}")
    print()

    total_bad = len(script_leftover) + len(display_leftover)
    if total_bad == 0:
        print("OK: 全体OK。音声・画面表示ともに未カバーの漢字はありません。")
        sys.exit(0)
    else:
        print("-> 上記の漢字を含む単語(活用形も)を RUBY_DICT に追記してください。")
        sys.exit(1)


if __name__ == "__main__":
    main()
