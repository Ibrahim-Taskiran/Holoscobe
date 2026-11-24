"""Design tokens, the one stylesheet, and small painting helpers shared by every Holoscobe surface.

Every color, radius, font and duration of the ui package lives here; other ui modules only refer to these names.
"""
from __future__ import annotations

import ctypes
import sys
from functools import lru_cache
from typing import Optional

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QWidget

# ---------- tokens ----------

BG = "#0F1115"
SURFACE = "#16191F"
RAISED = "#1E222A"
HOVER = "#272C36"
PRESSED = "#313743"
HAIRLINE = "#2A2F39"
STROKE = "#3B4250"
CONTROL_STROKE = "#6E7788"       # outline that must be seen on its own (3:1), e.g. an off switch
TEXT = "#ECEEF2"
TEXT_SOFT = "#C9CED8"
MUTED = "#98A0AE"
FAINT = "#646C7B"                # disabled text only
ACCENT = "#FF9F6B"
ACCENT_HOVER = "#FFB488"
ACCENT_PRESSED = "#E98B58"
ACCENT_TEXT = "#FFB58C"          # accent as text on dark
ON_ACCENT = "#20120A"
SUCCESS = "#5BD6A2"
WARNING = "#F5C451"
DANGER = "#FF7A6B"
WHITE = "#FFFFFF"
INK = "#0B0D11"                  # darkest: stage letterbox, halos

# Functional scene colors (camera, skeleton, strings).
HAND_RIGHT = SUCCESS
HAND_LEFT = ACCENT
HAND_UNCERTAIN = WARNING
STRING_COLORS = ("#FFC45C", "#FF8F6B", "#7FE3B8", "#FFDCC2")
STRING_DISABLED = "#858D9B"
SPARK = "#FFD678"
AREA = "#FFC7A6"
CREAM = "#FFE3CF"
CAT_FUR = "#4C4D52"
CAT_EDGE = "#77787C"
CAT_EAR = "#7A6268"
CAT_IRIS = "#C9C763"

RADIUS_S, RADIUS_M, RADIUS_L, RADIUS_XL = 6, 8, 12, 16
SPACE_XS, SPACE_S, SPACE_M, SPACE_L, SPACE_XL = 4, 8, 12, 16, 24
FAST_MS, NORMAL_MS = 120, 180

TEXT_PX = {"caption": 12, "body": 13, "section": 14, "subtitle": 16, "title": 20, "display": 28}

_TEXT_FAMILIES = ("Segoe UI Variable Text", "Segoe UI")
_DISPLAY_FAMILIES = ("Segoe UI Variable Display", "Segoe UI")
EASE = QEasingCurve.Type.OutCubic


def color(value: str, alpha: float = 1.0) -> QColor:
    c = QColor(value)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def rgba(value: str, alpha: float) -> str:
    c = QColor(value)
    return f"rgba({c.red()},{c.green()},{c.blue()},{round(alpha * 255)})"


def mix(a: QColor | str, b: QColor | str, t: float) -> QColor:
    """Linear blend, alpha included."""
    a, b, t = QColor(a), QColor(b), max(0.0, min(1.0, t))
    return QColor.fromRgbF(*(x + (y - x) * t for x, y in zip(a.getRgbF(), b.getRgbF())))


@lru_cache(maxsize=None)
def _family(display: bool) -> str:
    known = set(QFontDatabase.families())
    names = _DISPLAY_FAMILIES if display else _TEXT_FAMILIES
    return next((n for n in names if n in known), names[-1])


def font(px: int = TEXT_PX["body"], weight: QFont.Weight = QFont.Weight.Normal, display: bool = False) -> QFont:
    f = QFont(_family(display))
    f.setPixelSize(int(px))
    f.setWeight(weight)
    return f


def bold(px: int = TEXT_PX["body"], display: bool = False) -> QFont:
    return font(px, QFont.Weight.DemiBold, display)


# ---------- stylesheet ----------

def _qss() -> str:
    text, disp = _family(False), _family(True)
    focus = f"border: 1px solid {ACCENT};"
    return f"""
QMainWindow, QDialog, QMessageBox {{ background: {BG}; }}
QLabel {{ color: {TEXT}; background: transparent; }}
QLabel[role="display"] {{ font-family: "{disp}"; font-size: {TEXT_PX['display']}px; font-weight: 600; }}
QLabel[role="title"] {{ font-family: "{disp}"; font-size: {TEXT_PX['title']}px; font-weight: 600; }}
QLabel[role="section"] {{ font-size: {TEXT_PX['section']}px; font-weight: 600; }}
QLabel[role="lead"] {{ font-size: {TEXT_PX['section']}px; color: {MUTED}; }}
QLabel[role="row"] {{ font-size: {TEXT_PX['body']}px; font-weight: 600; }}
QLabel[role="caption"] {{ font-size: {TEXT_PX['caption']}px; color: {MUTED}; }}
QLabel[role="value"] {{ color: {TEXT_SOFT}; font-weight: 600; }}
QLabel[role="value"]:disabled {{ color: {FAINT}; }}
QLabel[role="accent"] {{ color: {ACCENT_TEXT}; font-weight: 600; }}
QLabel[role="counter"] {{ font-family: "{disp}"; font-size: {TEXT_PX['title']}px; font-weight: 600; color: {ACCENT_TEXT}; }}
QLabel[role="success"] {{ color: {SUCCESS}; font-weight: 600; }}
QLabel[role="keycap"] {{ background: {RAISED}; border: 1px solid {STROKE}; border-bottom: 2px solid {STROKE};
    border-radius: {RADIUS_S}px; padding: 2px 8px; color: {TEXT}; font-size: {TEXT_PX['caption']}px; font-weight: 600; }}

QFrame[role="card"] {{ background: {SURFACE}; border: 1px solid {HAIRLINE}; border-radius: {RADIUS_L}px; }}
QFrame[role="segments"] {{ background: {BG}; border: 1px solid {HAIRLINE}; border-radius: 10px; }}
QLabel[role="banner"] {{ color: {TEXT_SOFT}; font-size: {TEXT_PX['body']}px; }}
QFrame[role="line"] {{ background: {HAIRLINE}; border: none; max-height: 1px; min-height: 1px; }}
QFrame[role="vline"] {{ background: {HAIRLINE}; border: none; max-width: 1px; min-width: 1px; }}
QFrame[role="footer"] {{ background: {SURFACE}; border: none; border-top: 1px solid {HAIRLINE}; }}
QFrame[role="sidebar"] {{ background: {SURFACE}; border: none; border-right: 1px solid {HAIRLINE}; }}

QPushButton {{ color: {TEXT}; background: {RAISED}; border: 1px solid {HAIRLINE}; border-radius: {RADIUS_M}px;
    padding: 0 16px; min-height: 34px; font-size: {TEXT_PX['body']}px; font-weight: 600; }}
QPushButton:hover {{ background: {HOVER}; border-color: {STROKE}; }}
QPushButton:pressed {{ background: {PRESSED}; }}
QPushButton:focus {{ {focus} }}
QPushButton:disabled {{ color: {FAINT}; background: {SURFACE}; border-color: {HAIRLINE}; }}
QPushButton:checked {{ background: {rgba(ACCENT, .16)}; border-color: {rgba(ACCENT, .55)}; color: {ACCENT_TEXT}; }}
QPushButton[seg="true"] {{ background: transparent; border: 1px solid transparent; border-radius: 7px; color: {MUTED};
    padding: 0 12px; min-height: 28px; }}
QPushButton[seg="true"]:hover {{ color: {TEXT}; background: {RAISED}; }}
QPushButton[seg="true"]:checked {{ background: {rgba(ACCENT, .16)}; border-color: transparent; color: {ACCENT_TEXT}; }}
QPushButton[seg="true"]:focus {{ {focus} }}
QPushButton[kind="primary"], QMessageBox QPushButton:default {{ background: {ACCENT}; border: 1px solid {ACCENT};
    color: {ON_ACCENT}; }}
QPushButton[kind="primary"]:hover, QMessageBox QPushButton:default:hover {{ background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER}; }}
QPushButton[kind="primary"]:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
QPushButton[kind="primary"]:focus {{ border: 2px solid {TEXT}; }}
QPushButton[kind="primary"]:disabled {{ background: {RAISED}; border-color: {HAIRLINE}; color: {FAINT}; }}
QPushButton[kind="ghost"] {{ background: transparent; border-color: transparent; color: {MUTED}; padding: 0 12px; }}
QPushButton[kind="ghost"]:hover {{ background: {RAISED}; color: {TEXT}; }}
QPushButton[kind="ghost"]:pressed {{ background: {HOVER}; }}
QPushButton[kind="ghost"]:focus {{ {focus} color: {TEXT}; }}
QPushButton[kind="ghost"]:disabled {{ color: {FAINT}; background: transparent; }}

QToolButton[tool="true"] {{ color: {TEXT_SOFT}; background: transparent; border: 1px solid transparent;
    border-radius: {RADIUS_M}px; padding: 0 12px; min-height: 34px; font-size: {TEXT_PX['body']}px;
    font-weight: 600; }}
QToolButton[tool="true"]:hover {{ background: {RAISED}; color: {TEXT}; }}
QToolButton[tool="true"]:pressed {{ background: {HOVER}; }}
QToolButton[tool="true"]:checked {{ background: {rgba(ACCENT, .14)}; color: {ACCENT_TEXT}; }}
QToolButton[tool="true"]:focus {{ {focus} }}
QToolButton[tool="true"]:disabled {{ color: {FAINT}; }}
QToolButton[compact="true"] {{ padding: 0 7px; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

QCheckBox {{ color: {TEXT_SOFT}; spacing: 8px; font-size: {TEXT_PX['body']}px; }}
QCheckBox:disabled {{ color: {FAINT}; }}

QLineEdit, QComboBox, QAbstractSpinBox {{ color: {TEXT}; background: {RAISED}; border: 1px solid {STROKE};
    border-radius: {RADIUS_M}px; padding: 0 10px; min-height: 32px; font-size: {TEXT_PX['body']}px;
    selection-background-color: {ACCENT}; selection-color: {ON_ACCENT}; }}
QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover {{ background: {HOVER}; }}
QLineEdit:focus, QComboBox:focus, QComboBox:on, QAbstractSpinBox:focus {{ {focus} }}
QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled {{ color: {FAINT}; background: {SURFACE};
    border-color: {HAIRLINE}; }}
QAbstractSpinBox > QLineEdit {{ background: transparent; border: none; padding: 0; min-height: 0; }}
QAbstractSpinBox > QLineEdit:hover, QAbstractSpinBox > QLineEdit:focus, QAbstractSpinBox > QLineEdit:disabled {{
    background: transparent; border: none; }}
QComboBox {{ padding-right: 30px; }}
QComboBox::drop-down {{ border: none; width: 28px; background: transparent; }}
QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
QAbstractSpinBox {{ padding-right: 28px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 26px; border: none;
    background: transparent; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; height: 17px; border-top-right-radius: {RADIUS_M}px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; height: 17px;
    border-bottom-right-radius: {RADIUS_M}px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {PRESSED}; }}
QAbstractSpinBox::up-arrow, QAbstractSpinBox::down-arrow {{ image: none; width: 0; height: 0; }}
QComboBox QAbstractItemView {{ color: {TEXT}; background: {RAISED}; border: 1px solid {STROKE};
    border-radius: {RADIUS_M}px; padding: 4px; outline: none; selection-background-color: {HOVER};
    selection-color: {TEXT}; }}
QComboBox QAbstractItemView::item {{ min-height: 32px; padding: 0 8px; border-radius: {RADIUS_S}px; }}
QComboBox QAbstractItemView::item:hover {{ background: {HOVER}; }}
QComboBox QAbstractItemView::item:selected {{ background: {rgba(ACCENT, .18)}; color: {ACCENT_TEXT}; }}

QSlider {{ min-height: 24px; }}
QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: {STROKE}; }}
QSlider::sub-page:horizontal {{ height: 4px; border-radius: 2px; background: {ACCENT}; }}
QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: {TEXT}; }}
QSlider::handle:horizontal:hover {{ background: {WHITE}; }}
QSlider::handle:horizontal:pressed {{ background: {ACCENT_HOVER}; }}
QSlider::handle:horizontal:focus {{ background: {ACCENT_HOVER}; }}
QSlider::sub-page:horizontal:disabled {{ background: {STROKE}; }}
QSlider::handle:horizontal:disabled {{ background: {FAINT}; }}

QProgressBar {{ background: {HAIRLINE}; border: none; border-radius: 3px; min-height: 6px; max-height: 6px;
    color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

QScrollArea, QScrollArea > QWidget > QWidget[role="page"] {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {STROKE}; border-radius: 4px; min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: {CONTROL_STROKE}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {STROKE}; border-radius: 4px; min-width: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none;
    border: none; width: 0; height: 0; }}

QTabWidget::pane {{ border: none; background: transparent; }}

QMenu {{ background: {RAISED}; color: {TEXT}; border: 1px solid {STROKE}; border-radius: 10px; padding: 6px;
    font-size: {TEXT_PX['body']}px; }}
QMenu::item {{ background: transparent; padding: 8px 28px 8px 12px; border-radius: {RADIUS_S}px; margin: 1px 0; }}
QMenu::item:selected {{ background: {HOVER}; }}
QMenu::item:checked {{ color: {ACCENT_TEXT}; }}
QMenu::item:disabled {{ color: {FAINT}; background: transparent; }}
QMenu::icon {{ padding-left: 10px; }}
QMenu::separator {{ height: 1px; background: {HAIRLINE}; margin: 6px 8px; }}
QMenu::indicator {{ width: 0; height: 0; }}

QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {STROKE}; padding: 6px 8px;
    font-size: {TEXT_PX['caption']}px; font-family: "{text}"; }}
"""


def _palette() -> QPalette:
    p = QPalette()
    R = QPalette.ColorRole
    for role, value in ((R.Window, BG), (R.WindowText, TEXT), (R.Base, SURFACE), (R.AlternateBase, RAISED),
                        (R.Text, TEXT), (R.Button, RAISED), (R.ButtonText, TEXT), (R.ToolTipBase, RAISED),
                        (R.ToolTipText, TEXT), (R.Highlight, ACCENT), (R.HighlightedText, ON_ACCENT),
                        (R.PlaceholderText, MUTED), (R.Link, ACCENT_TEXT), (R.Mid, STROKE), (R.Dark, INK)):
        p.setColor(role, QColor(value))
    for role in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(FAINT))
    return p


def install() -> None:
    """Apply the look to the whole application once (safe to call from every window)."""
    app = QApplication.instance()
    if app is None or app.property("holoscobe_theme"):
        return
    app.setProperty("holoscobe_theme", True)
    app.setStyle("Fusion")
    app.setPalette(_palette())
    app.setFont(font())
    app.setStyleSheet(_qss())


def set_prop(widget: QWidget, name: str, value) -> None:
    """Set a stylesheet property and restyle, only when it changed."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


# ---------- native window ----------

def _dwm(hwnd: int, attribute: int, value: int) -> None:
    v = ctypes.c_int(value)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attribute, ctypes.byref(v), ctypes.sizeof(v))


def _colorref(value: str) -> int:
    c = QColor(value)
    return c.red() | c.green() << 8 | c.blue() << 16


def dark_title_bar(window: QWidget) -> None:
    """Dark native caption matching the window (Windows 10 2004+ / 11). Does nothing anywhere else."""
    if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
        return
    try:
        hwnd = int(window.winId())
        _dwm(hwnd, 20, 1)                        # DWMWA_USE_IMMERSIVE_DARK_MODE
        _dwm(hwnd, 35, _colorref(BG))            # DWMWA_CAPTION_COLOR
        _dwm(hwnd, 36, _colorref(TEXT))          # DWMWA_TEXT_COLOR
        _dwm(hwnd, 34, _colorref(HAIRLINE))      # DWMWA_BORDER_COLOR
    except Exception:                            # cosmetic only: never stop a window from opening
        return


def round_popup(popup: QWidget) -> None:
    """Let a popup (menu, combo list) paint its own rounded corners without the square native frame."""
    popup.setWindowFlags(popup.windowFlags() | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
    popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)


def menu(parent: Optional[QWidget] = None, title: str = "") -> QMenu:
    m = QMenu(title, parent)
    round_popup(m)
    return m


# ---------- painting ----------

_shadows: dict[tuple, QPixmap] = {}


def shadow_pixmap(w: int, h: int, radius: float, blur: int, alpha: float = 0.45, dpr: float = 1.0) -> QPixmap:
    """Cached soft shadow of a w x h rounded rectangle; the picture is `blur` px larger on every side."""
    key = (w, h, round(radius, 1), blur, round(alpha, 2), round(dpr, 2))
    pix = _shadows.get(key)
    if pix is None:
        if len(_shadows) > 48:
            _shadows.clear()
        pix = QPixmap(round((w + 2 * blur) * dpr), round((h + 2 * blur) * dpr))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(blur):
            spread = blur - i
            p.setBrush(QColor(0, 0, 0, max(1, round(255 * alpha * 2.2 * (i + 1) / (blur * blur)))))
            p.drawRoundedRect(QRectF(blur - spread, blur - spread, w + 2 * spread, h + 2 * spread),
                              radius + spread, radius + spread)
        p.end()
        _shadows[key] = pix
    return pix


def paint_shadow(p: QPainter, rect: QRectF, radius: float, blur: int = 12, alpha: float = 0.45, dy: float = 2.0) -> None:
    device = p.device()
    dpr = device.devicePixelRatioF() if device is not None else 1.0
    pix = shadow_pixmap(round(rect.width()), round(rect.height()), radius, blur, alpha, dpr)
    p.drawPixmap(QPointF(rect.left() - blur, rect.top() - blur + dy), pix)


def paint_glass(p: QPainter, rect: QRectF, radius: float = RADIUS_L, *, alpha: float = 0.92, blur: int = 14,
                border: Optional[QColor] = None) -> None:
    """Dark translucent panel with a soft shadow and a light hairline."""
    if blur:
        paint_shadow(p, rect, radius, blur, 0.34)
    p.setPen(QPen(border or color(WHITE, 0.13), 1.0))
    p.setBrush(color(SURFACE, alpha))
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


def paint_bar(p: QPainter, rect: QRectF, ratio: float, fill: QColor | str, track: Optional[QColor] = None) -> None:
    r = rect.height() / 2.0
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(track or color(WHITE, 0.12))
    p.drawRoundedRect(rect, r, r)
    if ratio > 0.0:
        p.setBrush(QColor(fill))
        p.drawRoundedRect(QRectF(rect.left(), rect.top(), max(rect.height(), rect.width() * min(1.0, ratio)),
                                 rect.height()), r, r)


def paint_ring(p: QPainter, center: QPointF, radius: float, ratio: float, fill: QColor | str, width: float = 3.0,
               track: Optional[QColor] = None) -> None:
    """Progress ring starting at 12 o'clock, clockwise."""
    box = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(track or color(WHITE, 0.16), width))
    p.drawEllipse(box)
    if ratio > 0.0:
        pen = QPen(QColor(fill), width + 0.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(box, 90 * 16, -int(min(1.0, ratio) * 360 * 16))
