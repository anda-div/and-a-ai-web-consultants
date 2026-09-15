# -*- coding: utf-8 -*-
"""Ptengineの期間指定まわりの、画面に触らない部分。

ブラウザ操作から切り離してある。**ここだけはテストで固定できる**ためである。
実際に、ここの判断を間違えて画面に嘘の理由を出したことがある
（1年以上前の月を指定したら「未来の日付です」と表示された）。

`ptengine_heatmap_capture.py` から読み込む。Playwright は要らない。
"""
from __future__ import annotations

import re
from datetime import date, timedelta

# Ptengineで遡れる範囲。実測（2026-09-15 時点）では
# 2025-10-01 は選べ、2025-09-01 は選べなかった。約365日の移動窓。
# 契約内容で変わる可能性があるため、判定には使わず**説明にだけ**使う。
LOOKBACK_NOTE = "Ptengineで遡れるのは実測で約12か月です。"


def month_span(value: str):
    """期間の指定を (開始日, 終了日) に直す。読めなければ None。

    **月次レポートでプリセット（今月・先月・過去7日間）を使ってはいけない。**
    実行した日から決まるため、意図した月とずれる。暦月を渡す。

        2026-08                  … その月の1日〜末日
        2026-08-01..2026-08-31   … 指定した範囲
    """
    m = re.fullmatch(r"(\d{4})-(\d{2})", value)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        first = date(y, mo, 1)
        nxt = date(y + (mo == 12), (mo % 12) + 1, 1)
        return first, nxt - timedelta(days=1)
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", value)
    if m:
        return date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
    return None


def disabled_reason(want: date, today: date | None = None) -> str:
    """押せない日セルに当たったときの理由を、日付から決める。

    **セル側には理由が書かれていない。** 未来の日も、遡れる範囲より古い日も、
    同じ `disabled` になる。区別する情報が無いからといって決め打ちすると、
    片方で嘘をつく。実際に、1年以上前の月を指定して
    「未来の日付です。対象月が終わってから撮ってください」と表示した。

    日付と今日を比べれば、どちらなのかは確実に分かる。
    """
    today = today or date.today()
    if want > today:
        return (f"{want} は選べません（未来の日付）。"
                "対象月が終わってから撮ってください。")
    return (f"{want} は選べません（遡れる範囲の外）。{LOOKBACK_NOTE}"
            "それより古い期間は、この方法では取得できません。")


def months_to_move(shown, want: date):
    """出ている月から、目的の月まで何か月動かすかを返す。

    パネルは2か月ぶん並ぶ。**どちらかに出ていれば動かさなくてよい。**
    そうでなければ、左のパネルを基準に差を測る。

    返り値は (動かす向きが戻るかどうか, 年送りを使うか, 差の月数)。
    差が0なら動かす必要はない。
    """
    target = (want.year, want.month)
    if target in shown:
        return None
    base = shown[0]
    diff = (target[0] - base[0]) * 12 + (target[1] - base[1])
    if diff == 0:
        return None
    # 1か月ずつでは古い月で何十回も押すことになる。
    # 12か月以上離れていれば年送りでまとめて詰める。
    return diff < 0, abs(diff) >= 12, diff
