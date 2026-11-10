"""例外クラス。

公式サイトのHTML構造が変わった場合に誤った結果を返さないため、
解析不能・構造変化は検出可能なエラーとして外へ出す。
"""

from __future__ import annotations


class KindaiSyllabusError(Exception):
    """このMCPの基底例外。"""


class InvalidSyllabusNoError(KindaiSyllabusError):
    """シラバス番号の形式が不正。

    実測ではシラバス番号は 2611N00215 / 2611100030 / 26Z1100070 のように
    「年度2桁 + 学部等2桁 + 6文字の英数字」の10文字。
    形式の推測はしないが、明らかに形式外の入力はリクエスト前に弾く。
    """


class CourseNotFoundError(KindaiSyllabusError):
    """存在しないシラバス番号、または公開側のエラーページ応答。

    実測: 不正IDは HTTP 302 -> /customer/include/error.html (共通エラー)。
    """


class SearchLayoutError(KindaiSyllabusError):
    """検索結果ページの構造が解析時と異なる(HTML構造変化を検出)。"""


class DetailLayoutError(KindaiSyllabusError):
    """詳細ページの構造が解析時と異なる(HTML構造変化を検出)。"""


class UpstreamResponseError(KindaiSyllabusError):
    """通信または応答自体の問題(タイムアウト、想定外ステータス等)。"""
