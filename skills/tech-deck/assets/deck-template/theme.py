"""簡報主題：色票、字型、版心與卡片樣式。只放常數，不放排版邏輯。"""
from pptx.dml.color import RGBColor


def rgb(hex_str: str) -> RGBColor:
    hex_str = hex_str.lstrip("#")
    return RGBColor(*(int(hex_str[i : i + 2], 16) for i in (0, 2, 4)))


FONT = "PingFang TC"  # Windows 改 "Microsoft JhengHei"

# 基礎黑白灰
INK = rgb("111111")        # 標題、主要內文、表頭底色
GRAY = rgb("555555")       # 次要文字
MUTED = rgb("8A8A8A")      # 頁尾、一般連線、虛線框
RULE = rgb("DDDDDD")       # 細分隔線
WHITE = rgb("FFFFFF")
ROW_ALT = rgb("F6F6F6")    # 表格交錯列
GRAY_FILL = rgb("F3F3F3")  # 灰底卡片

# 語義強調色
ACCENT = rgb("76B900")       # 強調綠：框線與重點細線
ACCENT_TEXT = rgb("5A8F00")  # 白底上的綠字（對比度足夠）
ALERT = rgb("B91C1C")        # 防錯攔截、核心問題、違規
CAUTION = rgb("B45309")      # 待定判斷

# 卡片樣式：fill 底色、line 框色、ink 內文色、head 標題色、dash 是否虛線
CARDS = {
    "gray":  {"fill": GRAY_FILL, "line": GRAY_FILL, "ink": INK, "head": INK, "dash": False},
    "green": {"fill": WHITE, "line": ACCENT, "ink": INK, "head": ACCENT_TEXT, "dash": False},
    "amber": {"fill": WHITE, "line": MUTED, "ink": INK, "head": GRAY, "dash": True},
    "red":   {"fill": WHITE, "line": ALERT, "ink": INK, "head": ALERT, "dash": False},
    "dark":  {"fill": WHITE, "line": INK, "ink": INK, "head": INK, "dash": False},
}

# 16:9 版心（英吋）：全寬 13.333、全高 7.50
SLIDE_W, SLIDE_H = 13.333, 7.50
LM, RM = 0.80, 12.53
TOP, BOTTOM = 1.70, 6.60  # 內容區上緣與安全底線；頁尾線在 7.00
W = RM - LM               # 內容寬 11.73
