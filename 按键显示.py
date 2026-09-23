# -*- coding: utf-8 -*-
"""
按键显示 —— 键位 / CPS 叠加层

一个常驻屏幕最上层的轻量级键位指示器：显示 W/A/S/D、空格、鼠标左右键的
按下状态，以及左右键的 CPS（每秒点击次数）。可直接盖在游戏画面上。

窗口用**分层窗口 + 逐像素 Alpha**（UpdateLayeredWindow）实现，所以
「未按下的键半透明、按下的键不透明」可以在同一帧里共存 —— 这是整窗
透明度的做法做不到的。

配色与尺寸来自对参考 HUD 的屏幕实测反推，视觉参数全部列在 DEFAULT_CONFIG 里。

功能
----
* 按键高亮：未按下半透明深色底 + 浅色字；按下为实心填充 + 深色字
* CPS 统计：左右键独立统计，1 秒滑动窗口 + EMA 平滑
* 移动：托盘或设置面板切到「移动模式」后，按住窗口左键即可拖动，
        边框会变成提示色；位置会被夹在显示器工作区内，拖不出屏幕
* 穿透：常驻模式下鼠标点击会穿透到后面的窗口（不影响游戏操作）
* 托盘：设置面板 / 移动模式 / 重置位置 / 打开配置 / 退出
* 设置面板：27 项参数，全部用滑条、勾选、下拉、系统取色器，改完即时生效

系统要求：Windows 10 及以上，Python 3.8+（依赖 Pillow、pystray）。

素材说明
--------
字体一律运行时从系统字体目录读取，不捆绑任何字体文件；
托盘图标以 base64 内嵌在 TRAY_ICON_PNG（为了保持单文件分发），
发布前请确认你有权使用该图标，或替换成自己的。
"""

import base64
import ctypes
import io
import json
import os
import sys
import threading
import time
import traceback
from collections import deque
from ctypes import wintypes

import pystray
from PIL import Image, ImageChops, ImageDraw, ImageFont

# ============================================================ 应用标识

APP_NAME = "按键显示"
CONFIG_FILE = "按键显示_配置.json"
LOG_FILE = "按键显示_运行日志.log"

# 以下三处必须是 ASCII（Win32 窗口类名 / 托盘 ID），所以用拼音
OVERLAY_CLASS = "AnJianXianShi"            # 叠加窗的窗口类名
SETTINGS_CLASS = "AnJianXianShiSheZhi"     # 设置窗的窗口类名
TRAY_ID = "anjianxianshi"

# 设成 1 会在控制台打印启动信息，排查问题时用
DEBUG = os.environ.get("ANJIANXIANSHI_DEBUG") == "1"


def debug(*args):
    if DEBUG:
        print("[按键显示]", *args, flush=True)


SUPERSAMPLE = 3        # 圆角抗锯齿的超采样倍数（直角时不缩放，见 render）
BORDER_ALPHA = 0.45    # 边框不透明度。界面上只给「显示边框」开关，不给数值
MOVE_MODE_BORDER = "#45A3FF"   # 移动模式下边框换成这个提示色

# 托盘图标：64x64 PNG 的 base64。
# 内嵌而不是放外部文件，是为了 exe 保持单文件、拷贝到哪都能用。
TRAY_ICON_PNG = (
    "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"
)


def exe_icon():
    """取本程序 exe 里嵌的图标（用于窗口标题栏）。

    开发时跑的是 python.exe，取到的会是 Python 的图标，所以只在打包后取。
    """
    if not getattr(sys, "frozen", False):
        return None
    global _EXE_ICON
    if _EXE_ICON is None:
        try:
            large, small = wintypes.HANDLE(), wintypes.HANDLE()
            shell32.ExtractIconExW(sys.executable, 0, ctypes.byref(large),
                                   ctypes.byref(small), 1)
            _EXE_ICON = large.value or small.value or 0
        except Exception as e:
            log_error("读取自身图标失败: %r" % (e,))
            _EXE_ICON = 0
    return _EXE_ICON or None


def tray_image():
    """托盘图标。优先用内嵌 PNG，解码失败就退回现画一个。"""
    global _TRAY_IMAGE
    if _TRAY_IMAGE is None:
        try:
            blob = base64.b64decode(TRAY_ICON_PNG)
            _TRAY_IMAGE = Image.open(io.BytesIO(blob)).convert("RGBA")
        except Exception as e:
            log_error("托盘图标解码失败，改用内置图形: %r" % (e,))
            _TRAY_IMAGE = fallback_tray_image()
    return _TRAY_IMAGE


# ============================================================ 默认配置
#
# 布局数值是对参考 HUD 做屏幕实测后反推出来的：本机 125% 缩放下实测
#   按键 61x61（正方形）、间距 6、空格条 196x31、CPS 条 129x48、
#   CPS 条上方额外 5px、圆角 3px、整体 195x290
# 换算回 96 DPI 基准就除以 1.25。
#
DEFAULT_CONFIG = {
    "position_x": 100,
    "position_y": 100,
    "scale": 0.0,                 # 0 = 跟随系统 DPI 自动缩放

    # ---- 布局 ----
    "key_unit": 48.8,             # -> 61
    "key_height": 48.8,           # -> 61，与 key_unit 相等才是正方形
    "gap": 4.8,                   # -> 6
    "radius": 2.4,                # -> 3px 圆角
    "space_height_ratio": 0.508,  # 空格条高 31 / 键高 61
    "cps_height_ratio": 0.787,    # CPS 条高 48 / 键高 61
    "cps_width_ratio": 0.662,     # CPS 条宽 129 / 整体宽 195
    "cps_gap_extra": 4,           # CPS 条上方比其他行多留 5px

    # ---- 配色 ----
    "key_bg": "#121212",
    "key_bg_alpha": 0.20,
    # 边框是深灰而不是浅灰：在浅色背景上参考 HUD 的描边比底色本身还暗
    # （背景 186 / 底色 154 / 描边 135），反解出来约 112 灰 @ 45%。
    "key_border": "#707070",
    "show_border": True,
    "key_normal_fg": "#F4F7FB",
    "key_normal_fg_alpha": 0.95,
    "key_active_bg": "#FFFFFF",
    "key_active_bg_alpha": 1.0,
    "key_active_fg": "#06080F",
    "key_active_fg_alpha": 1.0,

    # ---- 字体 ----
    # 参考 HUD 里所有按键文字都是同一个字号（W 和 LMB 字高都是 18px），
    # 所以 font_small_size 必须跟着 font_key_size 走。
    "font_name": "Arial",
    "font_bold": True,
    "font_key_size": 20,
    "font_small_size": 20,
    "font_cps_size": 18,

    # ---- CPS 统计 ----
    "cps_text": "[CPS: {0:.0f} | {1:.0f}]",
    "cps_fg": "#F4F7FB",
    "cps_alpha": 0.9,
    "cps_time_window": 1.0,       # 1 秒滑动窗口＝CPS 的标准定义
    "cps_smoothing": 0.35,        # 太小会跟不上而低估，太大会抖

    # ---- 行为 ----
    "move_mode": False,           # 常驻 = 固定位置 + 鼠标穿透
}

# 按键：键名 -> 虚拟键码
VK = {
    "W": 0x57, "A": 0x41, "S": 0x53, "D": 0x44,
    "SPACE": 0x20,
    "LMB": 0x01, "RMB": 0x02, "MMB": 0x04,
}
VK_CONTROL, VK_MENU, VK_Q = 0x11, 0x12, 0x51

VK_TO_NAME = {vk: name for name, vk in VK.items()}
MONITORED_VKS = tuple(VK.values()) + (VK_CONTROL, VK_MENU, VK_Q)


# ============================================================ Win32 声明

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
comdlg32 = ctypes.WinDLL("comdlg32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)


def sig(func, restype, argtypes=None):
    """统一声明签名。

    64 位下句柄类参数必须显式声明，否则 ctypes 会把指针当 32 位整数传，
    轻则 OverflowError，重则句柄被截断后随机崩溃（而且往往第一次跑正常、
    第二次才炸，很难查）。
    """
    func.restype = restype
    if argtypes is not None:
        func.argtypes = argtypes
    return func


# ---- 结构体 ----
class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt", POINT),
                ("lPrivate", wintypes.DWORD)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", ctypes.c_void_p), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HANDLE),
                ("hIcon", wintypes.HANDLE), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HANDLE)]


class DRAWITEMSTRUCT(ctypes.Structure):
    _fields_ = [("CtlType", wintypes.UINT), ("CtlID", wintypes.UINT),
                ("itemID", wintypes.UINT), ("itemAction", wintypes.UINT),
                ("itemState", wintypes.UINT), ("hwndItem", wintypes.HWND),
                ("hDC", wintypes.HDC), ("rcItem", wintypes.RECT),
                ("itemData", ctypes.c_void_p)]


class CHOOSECOLORW(ctypes.Structure):
    _fields_ = [("lStructSize", wintypes.DWORD), ("hwndOwner", wintypes.HWND),
                ("hInstance", wintypes.HANDLE), ("rgbResult", wintypes.DWORD),
                ("lpCustColors", ctypes.POINTER(wintypes.DWORD)),
                ("Flags", wintypes.DWORD), ("lCustData", wintypes.LPARAM),
                ("lpfnHook", ctypes.c_void_p),
                ("lpTemplateName", wintypes.LPCWSTR)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

# ---- 常量 ----
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
MONITOR_DEFAULTTONEAREST = 2
WS_POPUP = 0x80000000
GWL_EXSTYLE = -20
GW_HWNDPREV = 3

WS_CHILD, WS_VISIBLE, WS_TABSTOP = 0x40000000, 0x10000000, 0x00010000
WS_CAPTION, WS_SYSMENU = 0x00C00000, 0x00080000
SW_SHOW, SW_RESTORE = 5, 9

ULW_ALPHA = 0x00000002
AC_SRC_OVER, AC_SRC_ALPHA = 0x00, 0x01
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
HWND_TOP = 0
DIB_RGB_COLORS, BI_RGB = 0, 0
HWND_TOPMOST = -1
DEFAULT_CHARSET, FW_NORMAL = 1, 400

WM_COMMAND = 0x0111
WM_HSCROLL = 0x0114
WM_DRAWITEM = 0x002B
WM_SETFONT = 0x0030
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_ERASEBKGND = 0x0014
WM_APP_OPEN = 0x8000 + 1      # 自定义消息：让设置窗口显示出来
WM_APP_SYNC = 0x8000 + 2      # 自定义消息：把控件状态同步回当前配置

BS_AUTOCHECKBOX, BS_PUSHBUTTON, BS_OWNERDRAW = 0x00000003, 0x00000000, 0x0000000B
CBS_DROPDOWNLIST, CBS_HASSTRINGS = 0x0003, 0x0200
TBS_HORZ, TBS_NOTICKS = 0x0000, 0x0010
SS_LEFT = 0x00000000

TBM_SETRANGE = 0x0400 + 6
TBM_SETPOS = 0x0400 + 5
TBM_GETPOS = 0x0400
CB_ADDSTRING = 0x0143
CB_SETCURSEL = 0x014E
CB_GETCURSEL = 0x0147
BM_GETCHECK, BM_SETCHECK = 0x00F0, 0x00F1
BST_CHECKED = 1
CBN_SELCHANGE = 1
DT_CENTER, DT_VCENTER, DT_SINGLELINE = 0x0001, 0x0004, 0x0020
TRANSPARENT = 1
CC_RGBINIT, CC_FULLOPEN = 0x0001, 0x0002
PM_REMOVE = 1
IDC_ARROW = 32512

# 这些系统窗口长期占据 topmost 最上层，判断「上方是否有窗口压着我」时要跳过，
# 否则会误判成被压住，每 0.5 秒无意义地重排一次 Z 顺序。
SYSTEM_WINDOW_CLASSES = {
    "Default IME", "IME", "MSCTFIME UI", "SysShadow",
    "tooltips_class32", "Windows.UI.Core.CoreWindow",
    "ApplicationFrameWindow", "Shell_TrayWnd",
    # shell 的内部辅助窗口：它们也带 WS_EX_TOPMOST 而且永远压在最上面，
    # 但不画任何东西。不排除掉的话，「上方还有窗口吗」这个判断会一直为真，
    # 程序就会每 0.5 秒白忙一次。
    "ForegroundStaging", "ThumbnailDeviceHelperWnd", "TaskListThumbnailWnd",
    "Windows.UI.Composition.DesktopWindowContentBridge",
    "XamlExplorerHostIslandWindow", "Windows.UI.Input.InputSite.WindowClass",
}

# ---- 通用 ----
sig(user32.CreateWindowExW, wintypes.HWND,
    [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
     ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
     wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID])
sig(user32.DestroyWindow, wintypes.BOOL, [wintypes.HWND])
sig(user32.ShowWindow, wintypes.BOOL, [wintypes.HWND, ctypes.c_int])
sig(user32.SetWindowPos, wintypes.BOOL,
    [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
     ctypes.c_int, ctypes.c_int, wintypes.UINT])
sig(user32.GetWindow, wintypes.HWND, [wintypes.HWND, wintypes.UINT])
sig(user32.GetClassNameW, ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int])
sig(user32.GetWindowLongPtrW, ctypes.c_ssize_t, [wintypes.HWND, ctypes.c_int])
sig(user32.SetWindowLongPtrW, ctypes.c_ssize_t,
    [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t])
sig(user32.GetSystemMetrics, ctypes.c_int, [ctypes.c_int])
# MonitorFromPoint 的第二个参数传 POINT **值**（不是指针）
sig(user32.MonitorFromPoint, wintypes.HANDLE, [POINT, wintypes.DWORD])
sig(user32.GetMonitorInfoW, wintypes.BOOL,
    [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)])
sig(user32.GetCursorPos, wintypes.BOOL, [ctypes.POINTER(POINT)])
sig(user32.IsWindowVisible, wintypes.BOOL, [wintypes.HWND])
sig(user32.GetForegroundWindow, wintypes.HWND, [])
sig(user32.GetAsyncKeyState, ctypes.c_short, [ctypes.c_int])
sig(user32.SetForegroundWindow, wintypes.BOOL, [wintypes.HWND])
sig(user32.UpdateLayeredWindow, wintypes.BOOL,
    [wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
     wintypes.HDC, ctypes.POINTER(POINT), wintypes.DWORD,
     ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD])

# ---- 设置窗口 ----
sig(user32.RegisterClassExW, wintypes.WORD, [ctypes.POINTER(WNDCLASSEXW)])
sig(user32.DefWindowProcW, ctypes.c_ssize_t,
    [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM])
sig(user32.SendMessageW, ctypes.c_ssize_t,
    [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p])
sig(user32.PostMessageW, wintypes.BOOL,
    [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM])
sig(user32.SetWindowTextW, wintypes.BOOL, [wintypes.HWND, wintypes.LPCWSTR])
sig(user32.InvalidateRect, wintypes.BOOL,
    [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL])
sig(user32.GetMessageW, ctypes.c_int,
    [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT])
sig(user32.PeekMessageW, wintypes.BOOL,
    [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT])
sig(user32.TranslateMessage, wintypes.BOOL, [ctypes.POINTER(MSG)])
sig(user32.DispatchMessageW, ctypes.c_ssize_t, [ctypes.POINTER(MSG)])
sig(user32.PostQuitMessage, None, [ctypes.c_int])
sig(user32.AdjustWindowRect, wintypes.BOOL,
    [ctypes.POINTER(wintypes.RECT), wintypes.DWORD, wintypes.BOOL])
sig(user32.LoadCursorW, wintypes.HANDLE, [wintypes.HINSTANCE, ctypes.c_void_p])
sig(user32.FillRect, ctypes.c_int,
    [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HANDLE])
sig(user32.DrawTextW, ctypes.c_int,
    [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
     ctypes.POINTER(wintypes.RECT), wintypes.UINT])
# 第二参必须是 c_void_p：IDC_ARROW 是 MAKEINTRESOURCE(32512)，
# 声明成 LPCWSTR 的话 ctypes 会拒绝把整数当字符串传。

# ---- GDI ----
sig(gdi32.SelectObject, wintypes.HANDLE, [wintypes.HDC, wintypes.HANDLE])
sig(gdi32.CreateCompatibleDC, wintypes.HDC, [wintypes.HDC])
sig(gdi32.DeleteObject, wintypes.BOOL, [wintypes.HANDLE])
sig(gdi32.DeleteDC, wintypes.BOOL, [wintypes.HDC])
sig(gdi32.GetDeviceCaps, ctypes.c_int, [wintypes.HDC, ctypes.c_int])
sig(gdi32.CreateDIBSection, wintypes.HANDLE,
    [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
     ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD])
sig(gdi32.CreateSolidBrush, wintypes.HANDLE, [wintypes.DWORD])
sig(gdi32.SetBkMode, ctypes.c_int, [wintypes.HDC, ctypes.c_int])
sig(gdi32.SetTextColor, wintypes.DWORD, [wintypes.HDC, wintypes.DWORD])
# CreateFontW 是 14 个参数：nHeight/nWidth/nEscapement/nOrientation/fnWeight
# + 8 个 DWORD(fdwItalic..fdwPitchAndFamily) + 字体名
sig(gdi32.CreateFontW, wintypes.HANDLE,
    [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR])

sig(user32.GetDC, wintypes.HDC, [wintypes.HWND])
sig(user32.ReleaseDC, ctypes.c_int, [wintypes.HWND, wintypes.HDC])

# ---- 取色器 ----
sig(comdlg32.ChooseColorW, wintypes.BOOL, [ctypes.POINTER(CHOOSECOLORW)])
sig(shell32.ExtractIconExW, wintypes.UINT,
    [wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.HANDLE),
     ctypes.POINTER(wintypes.HANDLE), wintypes.UINT])


# ============================================================ 通用工具

def app_dir():
    """exe 打包后取 exe 所在目录，否则取脚本所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def log_note(msg):
    """写一条运行痕迹（启动、退出原因等）。"""
    try:
        with open(os.path.join(app_dir(), LOG_FILE), "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def log_error(msg):
    log_note("错误: %s" % msg)


def hex_to_rgb(text):
    s = str(text).lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def rgb_to_colorref(hexstr):
    """#RRGGBB -> COLORREF(0x00BBGGRR)。注意 Win32 里是 BGR 顺序。"""
    r, g, b = hex_to_rgb(hexstr)
    return (b << 16) | (g << 8) | r


def colorref_to_hex(ref):
    return "#%02X%02X%02X" % (ref & 0xFF, (ref >> 8) & 0xFF, (ref >> 16) & 0xFF)


def rgba(hexstr, alpha):
    """(颜色, 不透明度) -> (r, g, b, a)。a 一律夹到 0~255。"""
    r, g, b = hex_to_rgb(hexstr)
    try:
        a = int(round(255.0 * float(alpha)))
    except (TypeError, ValueError):
        a = 255
    return (r, g, b, max(0, min(255, a)))


def clamp(value, low, high):
    return low if value < low else (high if value > high else value)


def make_long(low, high):
    """Win32 的 MAKELONG：把两个 16 位值打进一个 32 位整数。

    两段都必须先掩到 16 位 —— 直接写 (high << 16) | low 的话，low 为负数时
    整个结果会变成负数，传进 lParam 后区间完全错乱。
    """
    return ((int(high) & 0xFFFF) << 16) | (int(low) & 0xFFFF)


def window_class(hwnd):
    buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, buf, 128)
    return buf.value


def premultiply(img):
    """把 RGB 乘上 alpha —— UpdateLayeredWindow 要求位图是**预乘 alpha** 的。

    Windows 合成分层窗口时，是把位图的 RGB 直接当「已预乘」的值来用：
        屏幕 = 位图RGB + (1 - alpha/255) x 背景

    所以传直通 alpha 的位图会出两类毛病：

      1. **边缘亮线**：抗锯齿残留像素常常是「高 RGB + 低 alpha」，
         例如 (255,255,255, a=16)，会被算成 255 + 0.94 x 背景，直接饱和成
         纯白 —— 就是按下的白块四周那圈白/灰细线。
      2. **半透明色整体偏淡**：配了 0.20 的不透明度，实际只有 0.10 的观感
         （实测：背景 165 时本该出 136，实际出 150）。

    预乘之后两者都对了：颜色按配置生效，低 alpha 像素的 RGB 自动趋近 0。
    """
    if img.mode != "RGBA":
        return img
    r, g, b, a = img.split()
    # ImageChops.multiply 就是 (c * a) / 255，正是预乘要的算法
    return Image.merge("RGBA", (ImageChops.multiply(r, a),
                                ImageChops.multiply(g, a),
                                ImageChops.multiply(b, a), a))


# ============================================================ 配置读写

CONFIG_PATH = None


def load_config():
    global CONFIG_PATH
    CONFIG_PATH = os.path.join(app_dir(), CONFIG_FILE)
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update(data)
        except Exception as e:
            log_error("读取配置失败，改用默认值: %r" % (e,))
    save_config(cfg)
    return cfg


def save_config(cfg):
    """整份写出（cfg 里已含全部默认键）。

    不能 merge 旧文件：废弃键必须真正从磁盘消失，否则下次启动又被读回来
    覆盖新默认值。顺便按 DEFAULT_CONFIG 的顺序输出，方便用户对照。
    """
    path = CONFIG_PATH or os.path.join(app_dir(), CONFIG_FILE)
    try:
        ordered = {k: cfg[k] for k in DEFAULT_CONFIG if k in cfg}
        for k in cfg:                      # 保留用户自己加的额外键
            if k not in ordered:
                ordered[k] = cfg[k]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ordered, f, indent=4, ensure_ascii=False)
    except Exception as e:
        log_error("保存配置失败: %r" % (e,))


def system_scale(cfg):
    """0 = 跟随系统 DPI；否则用配置里的固定倍率。"""
    try:
        fixed = float(cfg.get("scale") or 0)
    except (TypeError, ValueError):
        fixed = 0.0
    if fixed > 0:
        return fixed
    try:
        return user32.GetDpiForSystem() / 96.0
    except Exception:
        hdc = user32.GetDC(0)
        dpi = gdi32.GetDeviceCaps(hdc, 88)
        user32.ReleaseDC(0, hdc)
        return dpi / 96.0 if dpi else 1.0


# ============================================================ 字体

# 字体族 -> 真实文件名。必须写真实文件名，不能按「族名.ttf」猜：
# Consolas 的文件叫 consola.ttf / consolab.ttf（不是 consolas.ttf），
# 猜错会静默回退到别的字体，用户完全看不出来。
FONT_FILES = [
    ("Arial",         "arial.ttf",        "arialbd.ttf"),
    ("Consolas",      "consola.ttf",      "consolab.ttf"),
    ("Cascadia Mono", "CascadiaMono.ttf", "CascadiaMono.ttf"),
    ("Segoe UI",      "segoeui.ttf",      "segoeuib.ttf"),
    ("Tahoma",        "tahoma.ttf",       "tahomabd.ttf"),
    ("Verdana",       "verdana.ttf",      "verdanab.ttf"),
    ("微软雅黑",       "msyh.ttc",         "msyhbd.ttc"),
    ("等线",           "deng.ttf",         "dengb.ttf"),
    ("黑体",           "simhei.ttf",       "simhei.ttf"),
]

_FONT_CACHE = {}

_TRAY_IMAGE = None    # 托盘图标缓存
_EXE_ICON = None      # 本程序 exe 的图标句柄缓存


def font_file_path(name, bold=True):
    """按族名找字体文件；找不到返回 None。"""
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for fam, regular, bold_file in FONT_FILES:
        if fam.lower() == str(name).lower():
            for fn in ((bold_file, regular) if bold else (regular, bold_file)):
                path = os.path.join(fonts_dir, fn)
                if os.path.isfile(path):
                    return path
            return None
    # 也允许直接把文件名写进配置
    path = os.path.join(fonts_dir, str(name))
    return path if os.path.isfile(path) else None


def load_font(name, size, bold=True):
    """加载字体。必须带缓存 —— 拖设置窗口滑条时会每帧调用。"""
    key = (name, int(size), bool(bold))
    font = _FONT_CACHE.get(key)
    if font is not None:
        return font
    path = None
    try:
        path = font_file_path(name, bold)
    except Exception:
        path = None
    if path:
        try:
            font = ImageFont.truetype(path, size)
        except Exception as e:
            log_error("加载字体 %s 失败: %r" % (path, e))
    if font is None:
        try:
            font = ImageFont.truetype("arialbd.ttf", size)
        except Exception:
            font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


# 设置窗口的字体下拉：只列出本机真实存在的字体
FONT_CHOICES = [fam for fam, _r, _b in FONT_FILES if font_file_path(fam)] or ["Arial"]


# ============================================================ 布局

def build_layout(cfg, scale):
    """算出每个按键的位置和整窗尺寸。

    空格条和 CPS 条都比普通键矮，行高并不统一，所以 Y 坐标必须**逐行累加**。
    用「行数 x 行高」硬算的话底部会凭空多出一块空白（整体被撑高）。
    """
    s = scale
    unit = max(1, int(round(cfg["key_unit"] * s)))
    kh = max(1, int(round(cfg["key_height"] * s)))
    gap = max(0, int(round(cfg["gap"] * s)))
    space_kh = max(1, int(round(kh * clamp(float(cfg["space_height_ratio"]), 0.05, 2.0))))
    cps_kh = max(1, int(round(kh * clamp(float(cfg["cps_height_ratio"]), 0.05, 2.0))))
    cps_extra = max(0, int(round(float(cfg["cps_gap_extra"]) * s)))

    inner_w = 3 * unit + 2 * gap
    col = [i * (unit + gap) for i in range(3)]

    r0 = 0
    r1 = r0 + kh + gap
    r2 = r1 + kh + gap
    r3 = r2 + space_kh + gap
    r4 = r3 + kh + gap + cps_extra

    keys = [
        {"id": "W", "rect": (col[1], r0, col[1] + unit, r0 + kh), "label": "W"},
        {"id": "A", "rect": (col[0], r1, col[0] + unit, r1 + kh), "label": "A"},
        {"id": "S", "rect": (col[1], r1, col[1] + unit, r1 + kh), "label": "S"},
        {"id": "D", "rect": (col[2], r1, col[2] + unit, r1 + kh), "label": "D"},
        # label 为 None = 画一条横线，不显示 "SPACE" 字样
        {"id": "SPACE", "rect": (0, r2, inner_w, r2 + space_kh), "label": None},
    ]
    half = (inner_w - gap) // 2
    keys.append({"id": "LMB", "rect": (0, r3, half, r3 + kh), "label": "LMB"})
    keys.append({"id": "RMB", "rect": (half + gap, r3, inner_w, r3 + kh),
                 "label": "RMB"})

    cps_w = max(1, int(round(inner_w * clamp(float(cfg["cps_width_ratio"]), 0.05, 1.0))))
    cps_x = (inner_w - cps_w) // 2
    cps_rect = (cps_x, r4, cps_x + cps_w, r4 + cps_kh)

    return keys, cps_rect, inner_w, r4 + cps_kh


# ============================================================ 渲染

def render(keys, cps_rect, cps_text, win_w, win_h, active, cfg, scale,
           move_mode=False):
    """把当前状态画成一张 RGBA 位图。

    超采样只在**需要抗锯齿**时启用，也就是 radius > 0 的圆角。全直角时所有
    图形都是整数坐标的轴对齐矩形，没有斜边，不缩放反而最干净。

    为什么直角不能走超采样：缩放时各通道是**独立**重采样的。白块周围那圈
    「垫底」像素 RGB=255 而 alpha=0，alpha 衰减到 0 后 RGB 仍留在 255，
    只要有一丝残留 alpha，合成出来就是一圈比背景更亮的细线。不缩放就没有插值。
    """
    s = scale
    radius_px = max(0, int(round(cfg["radius"] * s)))
    ss = SUPERSAMPLE if radius_px > 0 else 1

    img = Image.new("RGBA", (win_w * ss, win_h * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg_normal = rgba(cfg["key_bg"], cfg["key_bg_alpha"])
    fg_normal = rgba(cfg["key_normal_fg"], cfg["key_normal_fg_alpha"])
    bg_active = rgba(cfg["key_active_bg"], cfg["key_active_bg_alpha"])
    fg_active = rgba(cfg["key_active_fg"], cfg["key_active_fg_alpha"])

    # 移动模式下边框换成提示色，一眼看出「现在可以拖」；这时不受「显示边框」影响
    if move_mode:
        border = hex_to_rgb(MOVE_MODE_BORDER) + (240,)
    elif cfg.get("show_border", True):
        border = hex_to_rgb(cfg["key_border"]) + (int(round(255 * BORDER_ALPHA)),)
    else:
        border = None

    radius = radius_px * ss
    border_w = max(1, int(round(1 * s))) * ss
    bleed = 2 * ss if ss > 1 else 0     # 透明垫底只在缩小采样时才有意义

    def to_device(rect):
        """物理坐标 -> 绘制坐标。

        右/下边界要减 1：物理区间是 [x1, x2) 共 x2-x1 像素，而 Pillow 的
        rectangle 两端**都包含** —— 直接乘倍数会多画一列/一行，缩小后那一列
        被平均成半透明，就在按键边缘形成一条灰线。
        """
        x1, y1, x2, y2 = rect
        return [x1 * ss, y1 * ss, x2 * ss - 1, y2 * ss - 1]

    items = [(to_device(k["rect"]), bool(active.get(k["id"]))) for k in keys]
    items.append((to_device(cps_rect), False))

    # 第一步：铺透明垫底（仅超采样路径需要；必须先全部铺完再填充，
    #         否则后一个矩形的垫底会擦掉前一个已经画好的边缘）
    if bleed:
        for (x1, y1, x2, y2), is_active in items:
            color = bg_active if is_active else bg_normal
            draw.rectangle((x1 - bleed, y1 - bleed, x2 + bleed, y2 + bleed),
                           fill=color[:3] + (0,))

    # 第二步：填色。描边只画在**未按下**的键上 —— Pillow 的 outline 是
    #         「覆盖」而不是「混合」，画在按下的实心块上会把边缘像素替换成
    #         半透明灰，又形成一圈灰环。
    for (x1, y1, x2, y2), is_active in items:
        color = bg_active if is_active else bg_normal
        use_border = border is not None and not is_active
        if radius > 0:
            draw.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=color)
            if use_border:
                draw.rounded_rectangle((x1, y1, x2, y2), radius=radius,
                                       outline=border, width=border_w)
        else:
            draw.rectangle((x1, y1, x2, y2), fill=color)
            if use_border:
                draw.rectangle((x1, y1, x2, y2), outline=border, width=border_w)

    # 第三步：文字（最后画，避免被垫底或边框覆盖）
    bold = bool(cfg.get("font_bold", True))
    font_key = load_font(cfg["font_name"], int(cfg["font_key_size"] * s) * ss, bold)
    font_small = load_font(cfg["font_name"],
                           int(cfg["font_small_size"] * s) * ss, bold)
    font_cps = load_font(cfg["font_name"], int(cfg["font_cps_size"] * s) * ss, bold)

    for key, ((x1, y1, x2, y2), is_active) in zip(keys, items):
        fg = fg_active if is_active else fg_normal
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        if key["label"]:
            font = font_small if len(key["label"]) > 1 else font_key
            draw.text((cx, cy), key["label"], font=font, fill=fg, anchor="mm")
        else:
            # 空格键：画一条居中的横线
            half = int((x2 - x1) * 0.30)
            th = max(1, int(round(1.5 * s)) * ss)
            draw.rectangle((cx - half, cy - th, cx + half, cy + th), fill=fg)

    cx1, cy1, cx2, cy2 = items[-1][0]
    draw.text(((cx1 + cx2) // 2, (cy1 + cy2) // 2), cps_text,
              font=font_cps, fill=rgba(cfg["cps_fg"], cfg["cps_alpha"]),
              anchor="mm")

    if ss == 1:
        return img
    return img.resize((win_w, win_h),
                      getattr(Image, "Resampling", Image).LANCZOS)


def fallback_tray_image(size=64):
    """内嵌图标解不出来时的兜底：深色圆角底 + 亮色 CPS 字样。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = max(1, size // 16)
    draw.rounded_rectangle((pad, pad, size - pad - 1, size - pad - 1),
                           radius=int(size * 0.22), fill=(11, 17, 29, 255),
                           outline=(139, 183, 255, 110), width=max(1, size // 48))
    draw.text((size / 2, size / 2 + 1), "CPS",
              font=load_font("Consolas", int(size * 0.34), bold=True),
              fill=(57, 246, 211, 255), anchor="mm")
    return img


# ============================================================ 设置面板
class SettingsWindow:
    """托盘「设置…」打开的参数面板。

    Windows 自带的 Python 是精简构建，没有 tcl/tk（tkinter 不可用），所以界面
    直接用 **Win32 原生控件**：Trackbar(滑条) / Button(勾选、按钮) / ComboBox
    (下拉) / Static(文字)，配 comdlg32 的系统取色器。零额外依赖、外观原生，
    打包出来的体积也不涨。

    设计原则是**所有参数都用受控控件**，不给自由文本框 ——
    避免手敲出会破坏布局的值（比如把按键高度填成 1）。

    窗口跑在独立线程里（Win32 窗口只能由创建它的线程处理消息），托盘线程通过
    PostMessage 让它显示出来。
    """

    # ---- 三列布局。每项：(控件类型, 显示名, 配置键, 参数) ----
    #
    # slider 的参数：
    #     lo / hi  取值区间（写实际值，不是滑条位置）
    #     mul      精度。滑条位置 = 值 x mul，所以 mul=10 是 0.1 挡、mul=100 是
    #              0.01 挡。尺寸类默认值是 125% DPI 的换算结果（48.8 / 4.8 / 2.4），
    #              用整数挡会一碰就丢掉小数。
    #     pct      true = 按百分比显示
    #     extra    联动规则：square 让键高跟随键宽；fontsize 让副字号跟随主字号；
    #              posx/posy 直接改窗口坐标
    #     indent   缩进一级（视觉上从属于上一项）
    #
    # 取值区间刻意留得比较宽，方便按自己的口味调。凡是能对称的就让默认值
    # 落在中点；像「按下透明度 = 1.0」这种默认值本身就是上限的，只能靠右端。
    COLS = [
        ("大小与布局", [
            ("slider", "按键尺寸", "key_unit",
             {"lo": 20, "hi": 100, "mul": 5, "extra": "square"}),
            ("slider", "按键间距", "gap", {"lo": 0, "hi": 40, "mul": 10}),
            ("slider", "圆角", "radius", {"lo": 0, "hi": 40, "mul": 10}),
            ("slider", "空格条高度", "space_height_ratio",
             {"lo": 0.26, "hi": 0.76, "mul": 100, "pct": True}),
            ("slider", "CPS 条高度", "cps_height_ratio",
             {"lo": 0.54, "hi": 1.04, "mul": 100, "pct": True}),
            ("slider", "CPS 条宽度", "cps_width_ratio",
             {"lo": 0.36, "hi": 0.96, "mul": 100, "pct": True}),
            ("slider", "CPS 上方间距", "cps_gap_extra",
             {"lo": 0, "hi": 60, "mul": 5}),
            ("combo", "整体缩放", "scale",
             {"items": ["跟随系统 DPI", "75%", "100%", "125%", "150%", "200%"],
              "vals": [0.0, 0.75, 1.0, 1.25, 1.5, 2.0]}),
            ("slider", "水平位置", "position_x",
             {"lo": -400, "hi": None, "mul": 1, "extra": "posx"}),
            ("slider", "垂直位置", "position_y",
             {"lo": -400, "hi": None, "mul": 1, "extra": "posy"}),
        ]),
        ("颜色与透明度", [
            ("color", "按键背景色", "key_bg", {}),
            ("slider", "按键背景透明度", "key_bg_alpha",
             {"lo": 0.00, "hi": 0.40, "mul": 100, "pct": True, "indent": True}),
            ("color", "边框颜色", "key_border", {}),
            ("check", "显示边框", "show_border", {}),
            ("color", "按键文字色", "key_normal_fg", {}),
            ("slider", "按键文字透明度", "key_normal_fg_alpha",
             {"lo": 0.30, "hi": 1.00, "mul": 100, "pct": True, "indent": True}),
            ("color", "按下底色", "key_active_bg", {}),
            ("slider", "按下透明度", "key_active_bg_alpha",
             {"lo": 0.30, "hi": 1.00, "mul": 100, "pct": True, "indent": True}),
            ("color", "按下文字色", "key_active_fg", {}),
            ("slider", "按下文字透明度", "key_active_fg_alpha",
             {"lo": 0.30, "hi": 1.00, "mul": 100, "pct": True, "indent": True}),
            ("color", "CPS 文字色", "cps_fg", {}),
            ("slider", "CPS 透明度", "cps_alpha",
             {"lo": 0.30, "hi": 1.00, "mul": 100, "pct": True, "indent": True}),
        ]),
        ("字体与行为", [
            ("combo", "字体", "font_name", {"items": None}),
            ("check", "加粗", "font_bold", {}),
            ("slider", "按键字号", "font_key_size",
             {"lo": 6, "hi": 72, "mul": 1, "extra": "fontsize"}),
            ("slider", "CPS 字号", "font_cps_size", {"lo": 6, "hi": 72, "mul": 1}),
            # CPS 统计时长与平滑程度刻意不放进界面：这两个参数调不好会让读数
            # 显得不准，已固定在实测过的 1.0 秒 + 0.35。
            ("check", "移动模式（按住窗口左键拖动）", "move_mode",
             {"side_effect": "move_mode"}),
        ]),
    ]

    # 布局尺寸（96 DPI 基准，实际按 DPI 缩放）
    LBL_W, SLD_W, VAL_W = 112, 140, 46
    ROW_H, COL_GAP, MARGIN, HEAD_H = 26, 20, 14, 30
    BTN_H = 30

    def __init__(self, overlay):
        self.ov = overlay
        self.hwnd = None
        self.pending_open = False
        self.ctrl_by_id = {}
        self.ctrl_by_hwnd = {}
        self.font = None
        self.wndproc_ref = None      # 必须持引用，否则回调会被回收
        threading.Thread(target=self._thread_main, daemon=True).start()

    # ---------------- 外部接口（托盘线程调用） ----------------
    def open(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_APP_OPEN, 0, 0)
        else:
            self.pending_open = True

    def sync_from_config(self):
        """请求把控件状态同步成当前配置（可从任意线程调用）。

        跨线程直接 SendMessage 到子控件容易踩坑，统一走 PostMessage，
        交给窗口自己的消息循环去更新。
        """
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_APP_SYNC, 0, 0)

    # ---------------- 参数读写 ----------------
    def _apply(self, changes, extra=None):
        cfg = self.ov.cfg
        cfg.update(changes)
        if extra == "square":                 # 按键保持正方形
            cfg["key_height"] = cfg["key_unit"]
        elif extra == "fontsize":             # 键位文字与副文字同号
            cfg["font_small_size"] = cfg["font_key_size"]
        elif extra == "posx":
            self.ov.x = int(cfg["position_x"])
        elif extra == "posy":
            self.ov.y = int(cfg["position_y"])
        self.ov.dirty = True
        self.ov.cfg_dirty = True

    def _pos_of(self, d, value=None):
        """配置值 -> 滑条位置（夹到区间内）。"""
        if value is None:
            value = self.ov.cfg.get(d["key"], d["lo"])
        try:
            pos = int(round(float(value) * d["mul"]))
        except (TypeError, ValueError):
            pos = d["pos_lo"]
        return int(clamp(pos, d["pos_lo"], d["pos_hi"]))

    def _val_of(self, d, pos):
        """滑条位置 -> 配置值。"""
        v = pos / float(d["mul"])
        return int(round(v)) if d["mul"] == 1 else round(v, 2)

    def _value_text(self, d, val):
        if d.get("pct"):
            return "%d%%" % round(val * 100)
        unit = d.get("unit", "")
        if d["mul"] == 1:
            return "%d%s" % (round(val), unit)
        if d["mul"] <= 10:
            return "%.1f%s" % (val, unit)
        return "%.2f%s" % (val, unit)

    def _sync(self, d):
        """把配置值夹进滑条区间，并同步滑条位置与数值标签。"""
        pos = self._pos_of(d)
        val = self._val_of(d, pos)
        if self.ov.cfg.get(d["key"]) != val:
            self.ov.cfg[d["key"]] = val
        user32.SendMessageW(d["hwnd"], TBM_SETPOS, True, pos)
        user32.SetWindowTextW(d["val_hwnd"], self._value_text(d, val))

    # ---------------- 窗口线程 ----------------
    def _thread_main(self):
        try:
            self._build()
        except Exception as e:
            log_error("设置窗口创建失败: %r\n%s" % (e, traceback.format_exc()))

    def _dpi(self):
        hdc = user32.GetDC(0)
        dpi = gdi32.GetDeviceCaps(hdc, 88) or 96
        user32.ReleaseDC(0, hdc)
        return dpi

    def _build(self):
        dpi = self._dpi()
        sc = dpi / 96.0

        def S(v):
            return int(round(v * sc))

        self.font = gdi32.CreateFontW(
            -S(9), 0, 0, 0, FW_NORMAL, 0, 0, 0,
            DEFAULT_CHARSET, 0, 0, 0, 0, "Segoe UI")

        # ---- 先算布局 ----
        col_w = S(self.LBL_W + self.SLD_W + self.VAL_W)
        head_h, row_h = S(self.HEAD_H), S(self.ROW_H)
        margin, col_gap = S(self.MARGIN), S(self.COL_GAP)
        max_rows = max(len(rows) for _t, rows in self.COLS)
        client_w = margin * 2 + col_w * 3 + col_gap * 2
        client_h = (margin + head_h + max_rows * row_h + S(10)
                    + S(self.BTN_H) + S(12))

        # ---- 注册窗口类并创建窗口 ----
        self.wndproc_ref = WNDPROC(self._wndproc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = 0x0008 | 0x0002            # CS_DBLCLKS | CS_HREDRAW
        wc.lpfnWndProc = ctypes.cast(self.wndproc_ref, ctypes.c_void_p)
        wc.hInstance = None
        wc.hCursor = user32.LoadCursorW(None, IDC_ARROW)
        wc.hIcon = wc.hIconSm = exe_icon()    # 标题栏/任务栏图标
        wc.hbrBackground = 16                 # COLOR_BTNFACE + 1
        wc.lpszClassName = SETTINGS_CLASS
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:                   # 1410 = 类已存在
                raise OSError("RegisterClassExW 失败: %d" % err)

        style = WS_CAPTION | WS_SYSMENU
        rect = wintypes.RECT(0, 0, client_w, client_h)
        user32.AdjustWindowRect(ctypes.byref(rect), style, False)
        win_w = rect.right - rect.left
        win_h = rect.bottom - rect.top
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        self.hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST, SETTINGS_CLASS, APP_NAME + " - 设置", style,
            max(0, (sw - win_w) // 2), max(0, (sh - win_h) // 3),
            win_w, win_h, None, None, None, None)
        if not self.hwnd:
            raise OSError("设置窗口创建失败")

        # ---- 创建控件 ----
        cid = 1000
        for ci, (title, rows) in enumerate(self.COLS):
            cx = margin + ci * (col_w + col_gap)
            self._static(title, cx, margin, col_w, head_h)
            ry = margin + head_h
            for kind, label, key, opt in rows:
                cid += 1
                if kind == "slider":
                    self._mk_slider(cid, key, opt, cx, ry, S, label)
                elif kind == "check":
                    self._mk_check(cid, key, opt, cx, ry, S, label)
                elif kind == "combo":
                    self._mk_combo(cid, key, opt, cx, ry, S, label)
                else:
                    self._mk_color(cid, key, cx, ry, S, label)
                ry += row_h

        # ---- 底部按钮 ----
        by = client_h - margin - S(self.BTN_H) + S(4)
        cid += 1
        self._button(cid, "关闭", client_w - margin - S(76), by,
                     S(76), S(self.BTN_H), S, action="close")
        cid += 1
        self._button(cid, "恢复默认值", client_w - margin - S(76) * 2 - S(8), by,
                     S(90), S(self.BTN_H), S, action="reset")
        self._static("改动即时生效，自动保存",
                     margin, by + S(7), S(220), S(20), S)

        # 默认不显示，只在托盘菜单点「设置…」时弹出；如果启动时已经有人在等它
        # （pending_open），那就直接显示。
        if self.pending_open:
            self.pending_open = False
            self._show()

        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _show(self):
        self.ov.settings_open = True
        user32.ShowWindow(self.hwnd, SW_RESTORE)
        user32.SetForegroundWindow(self.hwnd)

    # ---------------- 控件构造 ----------------
    def _static(self, text, x, y, w, h, S=lambda v: v):
        hwnd = user32.CreateWindowExW(0, "Static", text,
                                      WS_CHILD | WS_VISIBLE | SS_LEFT,
                                      x, y, w, h, self.hwnd, None, None, None)
        user32.SendMessageW(hwnd, WM_SETFONT, self.font, True)
        return hwnd

    def _mk_slider(self, cid, key, opt, x, y, S, label):
        mul = opt["mul"]
        vlo = opt["lo"]
        vhi = opt["hi"] if opt.get("hi") else max(
            vlo + 100, user32.GetSystemMetrics(0))
        pos_lo, pos_hi = int(round(vlo * mul)), int(round(vhi * mul))
        d = {"kind": "slider", "key": key, "cid": cid, "mul": mul,
             "lo": vlo, "hi": vhi, "pos_lo": pos_lo, "pos_hi": pos_hi,
             "pct": opt.get("pct"), "unit": opt.get("unit", ""),
             "extra": opt.get("extra")}

        lw, slw, vw = S(self.LBL_W), S(self.SLD_W), S(self.VAL_W)
        ix = S(12) if opt.get("indent") else 0
        self._static(label, x + ix, y + S(4), lw - ix, S(18), S)

        hwnd = user32.CreateWindowExW(
            0, "msctls_trackbar32", "",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | TBS_HORZ | TBS_NOTICKS,
            x + lw, y, slw, S(22), self.hwnd, cid, None, None)
        # TBM_SETRANGE 的 lParam 是 MAKELONG(最小值, 最大值)
        user32.SendMessageW(hwnd, TBM_SETRANGE, True, make_long(pos_lo, pos_hi))
        d["hwnd"] = hwnd
        d["val_hwnd"] = self._static("", x + lw + slw, y + S(4), vw, S(18), S)
        self.ctrl_by_id[cid] = d
        self.ctrl_by_hwnd[hwnd] = d
        self._sync(d)

    def _mk_check(self, cid, key, opt, x, y, S, label):
        hwnd = user32.CreateWindowExW(
            0, "Button", label, WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_AUTOCHECKBOX,
            x, y + S(2), S(self.LBL_W + self.SLD_W + self.VAL_W), S(20),
            self.hwnd, cid, None, None)
        user32.SendMessageW(hwnd, WM_SETFONT, self.font, True)
        if self.ov.cfg.get(key):
            user32.SendMessageW(hwnd, BM_SETCHECK, BST_CHECKED, 0)
        self.ctrl_by_id[cid] = {"kind": "check", "key": key, "cid": cid,
                                "hwnd": hwnd, "side_effect": opt.get("side_effect")}

    def _selection(self, items, vals, current):
        for i, item in enumerate(items):
            if vals is not None:
                try:
                    if abs(float(vals[i]) - float(current or 0)) < 1e-6:
                        return i
                except (TypeError, ValueError):
                    pass
            elif str(item) == str(current):
                return i
        return 0

    def _mk_combo(self, cid, key, opt, x, y, S, label):
        items = opt.get("items") or FONT_CHOICES
        vals = opt.get("vals")
        lw = S(self.LBL_W)
        self._static(label, x, y + S(4), lw, S(18), S)
        hwnd = user32.CreateWindowExW(
            0, "ComboBox", "",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | CBS_DROPDOWNLIST | CBS_HASSTRINGS,
            x + lw, y, S(self.SLD_W + self.VAL_W), S(200), self.hwnd, cid,
            None, None)
        user32.SendMessageW(hwnd, WM_SETFONT, self.font, True)
        for item in items:
            user32.SendMessageW(hwnd, CB_ADDSTRING, 0, str(item))
        user32.SendMessageW(hwnd, CB_SETCURSEL,
                            self._selection(items, vals, self.ov.cfg.get(key)), 0)
        self.ctrl_by_id[cid] = {"kind": "combo", "key": key, "cid": cid,
                                "hwnd": hwnd, "items": items, "vals": vals}

    def _mk_color(self, cid, key, x, y, S, label):
        lw = S(self.LBL_W)
        self._static(label, x, y + S(4), lw, S(18), S)
        hwnd = user32.CreateWindowExW(
            0, "Button", "", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
            x + lw, y + S(1), S(self.SLD_W - 40), S(20), self.hwnd, cid,
            None, None)
        self.ctrl_by_id[cid] = {"kind": "color", "key": key, "cid": cid,
                                "hwnd": hwnd}

    def _button(self, cid, text, x, y, w, h, S, action=None):
        hwnd = user32.CreateWindowExW(
            0, "Button", text, WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
            x, y, w, h, self.hwnd, cid, None, None)
        user32.SendMessageW(hwnd, WM_SETFONT, self.font, True)
        self.ctrl_by_id[cid] = {"kind": "button", "cid": cid, "hwnd": hwnd,
                                "action": action}

    # ---------------- 消息处理 ----------------
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_HSCROLL:
                d = self.ctrl_by_hwnd.get(lparam)      # lParam = 滑条句柄
                if d:
                    pos = user32.SendMessageW(d["hwnd"], TBM_GETPOS, 0, None)
                    val = self._val_of(d, pos)
                    self._apply({d["key"]: val}, d.get("extra"))
                    user32.SetWindowTextW(d["val_hwnd"],
                                          self._value_text(d, val))
                return 0

            if msg == WM_COMMAND:
                cid = wparam & 0xFFFF
                code = (wparam >> 16) & 0xFFFF
                d = self.ctrl_by_id.get(cid)
                if d:
                    kind = d["kind"]
                    if kind == "check":
                        value = bool(user32.SendMessageW(d["hwnd"], BM_GETCHECK,
                                                         0, None))
                        if d.get("side_effect") == "move_mode":
                            # 移动模式只有一个状态源：交给 Overlay 统一改，
                            # 它会顺手把托盘勾选和这里的勾选一起对齐
                            self.ov.set_move_mode(value)
                        else:
                            self._apply({d["key"]: value})
                    elif kind == "combo" and code == CBN_SELCHANGE:
                        i = user32.SendMessageW(d["hwnd"], CB_GETCURSEL, 0, None)
                        if i is not None and i >= 0:
                            value = d["vals"][i] if d["vals"] else d["items"][i]
                            self._apply({d["key"]: value})
                    elif kind == "color":
                        self._pick_color(d)
                    elif d.get("action") == "close":
                        user32.ShowWindow(hwnd, 0)
                        self.ov.settings_open = False
                    elif d.get("action") == "reset":
                        self._reset_all()
                return 0

            if msg == WM_DRAWITEM:
                ds = ctypes.cast(lparam, ctypes.POINTER(DRAWITEMSTRUCT)).contents
                d = self.ctrl_by_id.get(ds.CtlID)
                if d and d["kind"] == "color":
                    self._draw_swatch(ds, self.ov.cfg.get(d["key"], "#FFFFFF"))
                    return True
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            if msg == WM_APP_SYNC:
                self._refresh_controls()
                return 0

            if msg == WM_APP_OPEN:
                self._show()
                return 0

            if msg == WM_CLOSE:            # 只隐藏，不销毁
                user32.ShowWindow(hwnd, 0)
                self.ov.settings_open = False
                return 0

            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0

            if msg == WM_ERASEBKGND:
                return 1                   # 交给系统绘制，避免闪

            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        except Exception as e:
            log_error("设置窗口消息异常: %r" % (e,))
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _draw_swatch(self, ds, hexcolor):
        """给取色按钮画色块：底色 + 对比色的十六进制值。"""
        rect = ds.rcItem
        brush = gdi32.CreateSolidBrush(rgb_to_colorref(hexcolor))
        user32.FillRect(ds.hDC, ctypes.byref(rect), brush)
        gdi32.DeleteObject(brush)
        r, g, b = hex_to_rgb(hexcolor)
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        gdi32.SetBkMode(ds.hDC, TRANSPARENT)
        gdi32.SetTextColor(ds.hDC, 0x000000 if lum > 140 else 0xFFFFFF)
        user32.DrawTextW(ds.hDC, str(hexcolor).upper(), -1,
                         ctypes.byref(rect), DT_CENTER | DT_VCENTER | DT_SINGLELINE)
        return True

    def _pick_color(self, d):
        custom = (wintypes.DWORD * 16)()
        cc = CHOOSECOLORW()
        cc.lStructSize = ctypes.sizeof(CHOOSECOLORW)
        cc.hwndOwner = self.hwnd
        cc.rgbResult = rgb_to_colorref(self.ov.cfg.get(d["key"], "#FFFFFF"))
        cc.lpCustColors = custom
        cc.Flags = CC_RGBINIT | CC_FULLOPEN
        if comdlg32.ChooseColorW(ctypes.byref(cc)):
            self._apply({d["key"]: colorref_to_hex(cc.rgbResult)})
            user32.InvalidateRect(d["hwnd"], None, True)

    def _reset_all(self):
        """所有参数拉回默认值。位置不重置，免得窗口跳出屏幕。"""
        for key, value in DEFAULT_CONFIG.items():
            if key in ("position_x", "position_y"):
                continue
            self.ov.cfg[key] = value
        self.ov.cfg["key_height"] = self.ov.cfg["key_unit"]
        self.ov.cfg["font_small_size"] = self.ov.cfg["font_key_size"]
        self._refresh_controls()
        self.ov.dirty = True
        self.ov.cfg_dirty = True

    def _refresh_controls(self):
        """把每个控件的显示状态对齐到配置（只读配置，不回写）。"""
        for d in self.ctrl_by_id.values():
            kind = d.get("kind")
            if kind == "slider":
                self._sync(d)
            elif kind == "check":
                user32.SendMessageW(
                    d["hwnd"], BM_SETCHECK,
                    BST_CHECKED if self.ov.cfg.get(d["key"]) else 0, 0)
            elif kind == "combo":
                user32.SendMessageW(
                    d["hwnd"], CB_SETCURSEL,
                    self._selection(d["items"], d["vals"],
                                    self.ov.cfg.get(d["key"])), 0)
            elif kind == "color":
                user32.InvalidateRect(d["hwnd"], None, True)


# ============================================================ CPS 统计
class ClickRateCounter:
    """滑动窗口 + EMA 平滑的点击速率统计。

    窗口默认 1 秒 —— 这是 CPS 的标准定义（和常见的 CPS 测试网站一致）。
    EMA 系数不能太小，否则跟不上真实速率而低估（实测 0.05 会把 15 CPS 读成 13.9）。
    """

    def __init__(self, window, smoothing):
        self.window = max(0.05, float(window))
        self.smoothing = clamp(float(smoothing), 0.01, 1.0)
        self.times = deque()
        self.smooth = 0.0

    def click(self, t):
        self.times.append(t)

    def drop_since(self, t):
        """丢掉 t 之后记录的点击。

        用在「这次按下其实是拖窗口」的场景。旧写法是「按住左键就不计数」，
        结果移动模式下左键永远统计不到；现在先照常计数，等确认窗口真的被
        拖动了再把那一下扣掉。
        """
        while self.times and self.times[-1] >= t:
            self.times.pop()

    def update(self, t):
        cutoff = t - self.window
        while self.times and self.times[0] < cutoff:
            self.times.popleft()
        raw = len(self.times) / self.window
        self.smooth += (raw - self.smooth) * self.smoothing
        return self.smooth


# ============================================================ 输入采样
class InputMonitor(threading.Thread):
    """独立的按键采样线程。

    为什么要单独开线程：主循环渲染一帧要 7~15ms（超采样 + 缩放 + 分层窗口
    推送），如果在主循环里轮询按键，**按下时长比一帧还短的点击会被整个跳过**。
    实测固定 15 CPS、只改按下时长：

        按下 40ms -> 显示 15      按下 10ms -> 显示 15
        按下  6ms -> 显示 11      按下  3ms -> 显示  6

    点得越快、按得越短，读数越低 —— 这就是「速率一高就不准」的原因。

    这里用 1ms 周期只读 GetAsyncKeyState，完全不碰渲染。注意必须先
    timeBeginPeriod(1) 把系统定时器精度提上来，否则 time.sleep(0.001) 在
    Windows 上实际会睡 15.6ms，比原来的主循环还慢。

    主线程通过 state 快照（当前是否按下）+ events 队列（点击事件）取结果。
    """

    def __init__(self, vks, interval=0.001):
        super().__init__(daemon=True)
        self.vks = tuple(vks)
        self.interval = interval
        self.state = {vk: False for vk in self.vks}
        self.events = deque()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            winmm = ctypes.WinDLL("winmm")
            winmm.timeBeginPeriod(1)
        except Exception:
            winmm = None
        try:
            while not self._stop:
                t = time.perf_counter()
                for vk in self.vks:
                    v = user32.GetAsyncKeyState(vk)
                    is_down = bool(v & 0x8000)
                    # 最低位 = 「自上次调用以来按下过」。即使按下和抬起都发生在
                    # 两次采样之间，这一位也会置起来，给短按多一层保险。
                    edge = bool(v & 0x0001)
                    if (is_down or edge) and not self.state[vk]:
                        self.events.append((vk, t))
                    self.state[vk] = is_down
                time.sleep(self.interval)
        finally:
            if winmm:
                try:
                    winmm.timeEndPeriod(1)
                except Exception:
                    pass


# ============================================================ 叠加窗口
class Overlay:
    """按键显示窗本体。"""

    def __init__(self, cfg):
        self.cfg = cfg
        user32.SetProcessDPIAware()
        self.scale = system_scale(cfg)
        self.keys, self.cps_rect, self.win_w, self.win_h = build_layout(
            cfg, self.scale)
        self.x = int(cfg["position_x"])
        self.y = int(cfg["position_y"])
        self.x, self.y = self.clamp_to_screen(self.x, self.y)

        self.running = True
        self.dirty = False           # 参数变了，要重算布局并重绘
        self.cfg_dirty = False       # 配置需要落盘（拖滑条会高频触发，节流写）
        self.settings_open = False   # 设置窗开着时别去抢它的置顶
        self.last_cfg_save = 0.0
        self.last_topmost_tick = 0.0
        self.last_foreground = None

        self.prev = {}               # 上一帧的按下状态，用来判断「有变化」
        self.flash = {}              # 键名 -> 高亮到什么时候（给超短点击留帧）
        self.press_t = {}            # 键名 -> 最近一次按下的时间
        self.drag_prev = None
        self.drag_session = None
        self.drag_blocked = False
        self.hotkey_since = 0.0
        self.exit_reason = "未知（主循环结束）"

        self.move_mode = bool(cfg.get("move_mode", False))
        self.locked = not self.move_mode     # 常驻 = 固定位置 + 鼠标穿透

        self._register_class()
        ex = (WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
              | WS_EX_TOPMOST)
        self.hwnd = user32.CreateWindowExW(
            ex, OVERLAY_CLASS, APP_NAME, WS_POPUP,
            self.x, self.y, self.win_w, self.win_h, None, None, None, None)
        if not self.hwnd:
            raise OSError("CreateWindowExW 失败: %d" % ctypes.get_last_error())

        user32.ShowWindow(self.hwnd, SW_SHOW)
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, self.x, self.y, 0, 0,
                            SWP_NOSIZE | SWP_NOACTIVATE)
        self._apply_lock()

        self.input = InputMonitor(MONITORED_VKS)
        self.input.start()
        self.left = ClickRateCounter(cfg["cps_time_window"], cfg["cps_smoothing"])
        self.right = ClickRateCounter(cfg["cps_time_window"], cfg["cps_smoothing"])
        self.last_cps_tick = 0.0
        self.last_cps_text = str(cfg["cps_text"]).format(0.0, 0.0)

        self.settings = SettingsWindow(self)

    def _register_class(self):
        self._wndproc_ref = WNDPROC(self._wndproc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = ctypes.cast(self._wndproc_ref, ctypes.c_void_p)
        wc.hInstance = None
        wc.hCursor = user32.LoadCursorW(None, IDC_ARROW)
        wc.hIcon = wc.hIconSm = exe_icon()
        wc.hbrBackground = None          # 内容由 UpdateLayeredWindow 决定
        wc.lpszClassName = OVERLAY_CLASS
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            if ctypes.get_last_error() != 1410:
                raise OSError("RegisterClassExW 失败")

    @staticmethod
    def _wndproc(hwnd, msg, wparam, lparam):
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ---------- 模式与穿透 ----------
    def _apply_lock(self):
        """锁定 = 位置固定 + WS_EX_TRANSPARENT 鼠标穿透。

        好处：Windows 对分层窗口的**全透明像素会自动放行鼠标**，
        所以按键之间的缝隙本来就不挡点击。
        """
        style = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        if self.locked:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, style)

    def set_move_mode(self, on):
        """移动模式开关 —— **这是唯一的状态源**。

        开：解除鼠标穿透，按住窗口左键即可拖动。
        关：回到常驻（位置固定 + 鼠标穿透）。

        托盘菜单的勾选、设置面板的勾选都只是它的两个显示，改完必须一起
        对齐，否则两边会各说各话（用户反馈过这个问题）。
        """
        on = bool(on)
        self.move_mode = on
        self.locked = not on
        self.cfg["move_mode"] = on
        self._apply_lock()
        save_config(self.cfg)
        self._sync_move_mode_ui()

    def _sync_move_mode_ui(self):
        """把移动模式的新状态同步到所有显示它的地方。"""
        try:
            self.icon.update_menu()          # 托盘菜单的勾选
        except Exception:
            pass
        try:
            self.settings.sync_from_config()  # 设置面板的勾选
        except Exception:
            pass

    # ---------- 位图推送 ----------
    def push(self, img):
        w, h = img.size
        # UpdateLayeredWindow 要求预乘 alpha，否则边缘出白线、半透明色偏淡
        data = premultiply(img).tobytes("raw", "BGRA")
        hdc_screen = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h          # 负高度 = 自上而下
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        ppv = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi),
                                      DIB_RGB_COLORS, ctypes.byref(ppv), None, 0)
        ctypes.memmove(ppv, data, len(data))
        gdi32.SelectObject(hdc_mem, hbmp)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        size = SIZE(w, h)
        src = POINT(0, 0)
        dst = POINT(self.x, self.y)
        user32.UpdateLayeredWindow(self.hwnd, hdc_screen, ctypes.byref(dst),
                                   ctypes.byref(size), hdc_mem, ctypes.byref(src),
                                   0, ctypes.byref(blend), ULW_ALPHA)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)

    # ---------- 输入 ----------
    def down(self, vk):
        """读采样线程的快照。

        GetAsyncKeyState 的最低位是「自上次调用以来按下过」，多处调用会互相
        把它吃掉，所以只能有一个消费者，统一交给 InputMonitor。
        """
        return bool(self.input.state.get(vk, False))

    def clamp_to_screen(self, x, y):
        """把窗口夹进「最近的那块显示器」的工作区，保证不会拖出屏幕。

        用 MonitorFromPoint(MONITOR_DEFAULTTONEAREST) 而不是主屏尺寸：
        多显示器时能自由跨屏，但不会跑到所有屏幕之外（虚拟桌面最大的那块
        矩形里有大片是显示器之间的空隙）。用 rcWork 而不是 rcMonitor，
        是为了不让人把窗口藏到任务栏底下。
        """
        pt = POINT(int(x + self.win_w // 2), int(y + self.win_h // 2))
        hmon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not hmon or not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return int(x), int(y)
        work = info.rcWork
        nx = int(clamp(x, work.left, max(work.left, work.right - self.win_w)))
        ny = int(clamp(y, work.top, max(work.top, work.bottom - self.win_h)))
        return nx, ny

    def _cursor_in_window(self, pt):
        """光标是否落在窗口矩形内（用来判断这次按下是不是冲着窗口来的）。"""
        return (self.x <= pt.x < self.x + self.win_w and
                self.y <= pt.y < self.y + self.win_h)

    def refresh(self, now):
        # 先把采样线程攒下的点击事件取出来记账
        while True:
            try:
                vk, t = self.input.events.popleft()
            except IndexError:
                break
            name = VK_TO_NAME.get(vk)
            if name is None:
                continue
            self.press_t[name] = t
            # 超短点击可能整帧都被跳过，给个最小高亮时长，保证看得见
            self.flash[name] = t + 0.055
            if name == "LMB":
                self.left.click(t)
            elif name == "RMB":
                self.right.click(t)

        active = {}
        changed = False
        for name, vk in VK.items():
            if name == "MMB":
                continue                     # 中键留给拖动
            shown = self.down(vk) or now < self.flash.get(name, 0.0)
            active[name] = shown
            if shown != self.prev.get(name, False):
                changed = True
            self.prev[name] = shown

        if now - self.last_cps_tick >= 0.06:
            self.last_cps_tick = now
            text = str(self.cfg["cps_text"]).format(self.left.update(now),
                                                    self.right.update(now))
            if text != self.last_cps_text:
                self.last_cps_text = text
                changed = True
        return active, changed

    # ---------- 拖动 ----------
    def handle_drag(self):
        """按住窗口左键（或中键）拖动。

        关键是**按下必须发生在窗口上**：移动模式下窗口不再穿透鼠标，用户
        在屏幕任何地方按下左键都会产生输入事件，以前的做法是「左键一按就
        跟手」，于是全屏随便一拖窗口就飞了。现在用 _cursor_in_window 判一次，
        不是冲着窗口来的按下就整段忽略（drag_blocked），直到松开为止。
        """
        if not self.move_mode:
            self.drag_prev = None
            self.drag_session = None
            self.drag_blocked = False
            return False

        if not (self.down(VK["LMB"]) or self.down(VK["MMB"])):
            self.drag_prev = None
            self.drag_session = None
            self.drag_blocked = False
            return False

        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))

        if self.drag_prev is None:                       # 这一帧刚按下
            if self.drag_blocked:
                return False
            if not self._cursor_in_window(pt):
                self.drag_blocked = True                 # 不是冲着窗口来的
                return False
            self.drag_prev = (pt.x, pt.y, self.x, self.y)
            name = "LMB" if self.down(VK["LMB"]) else (
                "RMB" if self.down(VK["RMB"]) else "MMB")
            # [按下的键, 那次按下的时间, 是否已经扣掉]
            self.drag_session = [name, self.press_t.get(name), False]
            return False

        px, py, wx, wy = self.drag_prev
        nx, ny = self.clamp_to_screen(wx + (pt.x - px), wy + (pt.y - py))
        if (nx, ny) == (self.x, self.y):
            return False
        self.x, self.y = nx, ny
        # 拖完就落盘（主循环按 0.5 秒节流写）—— 否则只有从托盘正常退出才会
        # 保存位置，顺手把进程杀掉的话下次又回到老地方。
        self.cfg["position_x"], self.cfg["position_y"] = nx, ny
        self.cfg_dirty = True
        name, press_t, dropped = self.drag_session
        # 只有窗口**确实被拖动了**才把那次按下从 CPS 里扣掉
        if not dropped and press_t is not None:
            counter = self.left if name == "LMB" else (
                self.right if name == "RMB" else None)
            if counter is not None:
                counter.drop_since(press_t)
            self.drag_session[2] = True
        return True

    def reset_position(self):
        self.x = int(DEFAULT_CONFIG["position_x"])
        self.y = int(DEFAULT_CONFIG["position_y"])
        self.cfg["position_x"], self.cfg["position_y"] = self.x, self.y
        save_config(self.cfg)

    def reload_layout(self):
        """参数改了之后重算布局。

        窗口尺寸会跟着变，但不用重建窗口 —— UpdateLayeredWindow 每次推送会连
        尺寸一起更新。CPS 计数器只更新参数、不重建，否则拖滑条时数字会被反复清零。
        """
        self.scale = system_scale(self.cfg)
        self.keys, self.cps_rect, self.win_w, self.win_h = build_layout(
            self.cfg, self.scale)
        for counter in (self.left, self.right):
            counter.window = max(0.05, float(self.cfg["cps_time_window"]))
            counter.smoothing = clamp(float(self.cfg["cps_smoothing"]), 0.01, 1.0)
        # 变大之后可能顶出屏幕，夹回最近的显示器工作区
        self.x, self.y = self.clamp_to_screen(self.x, self.y)
        self.cfg["position_x"], self.cfg["position_y"] = self.x, self.y

    # ---------- 置顶保持 ----------
    def _real_window_above(self):
        """自己上方还有没有**真实的**内容窗口。

        要同时排除两类：
          * 系统窗口（输入法、tooltip、shell 的暂存/缩略图辅助窗口）
          * 不可见的窗口
        两者都不画东西，但它们同样带 WS_EX_TOPMOST 且永远压在最上面，
        不排除的话这个判断会永远为真。
        """
        h = self.hwnd
        for _ in range(200):
            h = user32.GetWindow(h, GW_HWNDPREV)
            if not h:
                return False
            if not user32.IsWindowVisible(h):
                continue
            if window_class(h) in SYSTEM_WINDOW_CLASSES:
                continue
            return True
        return False

    def raise_to_top(self):
        """把自己提到最上层。

        光调 SetWindowPos(HWND_TOPMOST) 是**不够**的：对已经置顶的窗口它基本
        只是「保持不动」，盖不住另一个同样置顶的窗口。而游戏进全屏时恰好就是
        这种情况 —— 它把自己的窗口设成 TOPMOST，而且它还是前台窗口，Windows
        会把前台窗口摆在置顶带的最上面。

        所以补一次 HWND_TOP（把窗口排到 Z 顺序最前），两次调用都是幂等的：
        失败或无效也不会有副作用。
        """
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        user32.SetWindowPos(self.hwnd, HWND_TOP, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def keep_on_top(self, now):
        """确认自己仍在最上层。

        触发时机有两个：
          * 前台窗口变化时**立刻**处理 —— 玩家切进游戏的那一刻就抢回来，
            不用等下一轮轮询（否则会有一小段时间看不到）
          * 平时每 0.5 秒兜底一次
        """
        if self.settings_open:
            return                     # 设置窗开着时别去抢它的位置
        foreground = user32.GetForegroundWindow()
        changed = foreground != self.last_foreground
        if not changed and now - self.last_topmost_tick < 0.5:
            return
        self.last_topmost_tick = now
        self.last_foreground = foreground
        if self._real_window_above():
            self.raise_to_top()

    # ---------- 托盘 ----------
    def start_tray(self):
        def toggle_move(icon, item):
            self.set_move_mode(not self.move_mode)
            icon.update_menu()

        def do_reset(icon, item):
            self.reset_position()

        def open_settings(icon, item):
            self.settings.open()

        def open_cfg(icon, item):
            try:
                os.startfile(CONFIG_PATH)
            except Exception as e:
                log_error("打开配置失败: %r" % (e,))

        def do_quit(icon, item):
            self.exit_reason = "托盘菜单退出"
            self.running = False
            icon.stop()

        menu = pystray.Menu(
            pystray.MenuItem("设置…", open_settings, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("移动模式（左键拖动调整位置）", toggle_move,
                             checked=lambda item: self.move_mode),
            pystray.MenuItem("重置位置", do_reset),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开配置文件", open_cfg),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", do_quit),
        )
        self.icon = pystray.Icon(TRAY_ID, tray_image(), APP_NAME, menu)

        def tray_thread():
            try:
                self.icon.run()
            except Exception as e:
                log_error("托盘线程异常: %r" % (e,))

        threading.Thread(target=tray_thread, daemon=True).start()
        for _ in range(60):            # 等托盘图标就绪，便于排查
            if getattr(self.icon, "visible", False):
                break
            time.sleep(0.05)
        debug("tray visible =", getattr(self.icon, "visible", None),
              "| hwnd =", self.hwnd, "| locked =", self.locked,
              "| win =", self.win_w, "x", self.win_h,
              "| scale =", round(self.scale, 4))

    # ---------- 主循环 ----------
    def run(self):
        self.start_tray()
        self.push(render(self.keys, self.cps_rect, self.last_cps_text,
                         self.win_w, self.win_h, {}, self.cfg, self.scale,
                         self.move_mode))
        last_move_mode = self.move_mode
        msg = MSG()
        while self.running:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if not self.running:
                break

            now = time.perf_counter()
            # 退出热键 Ctrl+Alt+Q 要求**长按 0.6 秒**。
            # 因为游戏里 Ctrl 常用于疾跑、Q 常用于丢弃物品，边跑边丢时
            # 很容易碰出 Ctrl+Q；万一 Alt 也正好按着，就会把本程序直接关掉
            # （表现为「按键显示突然不见了 / 盖不上去」）。
            if self.down(VK_CONTROL) and self.down(VK_MENU) and self.down(VK_Q):
                self.hotkey_since = self.hotkey_since or now
                if now - self.hotkey_since >= 0.6:
                    self.exit_reason = "热键 Ctrl+Alt+Q（长按 0.6 秒）"
                    break
            else:
                self.hotkey_since = 0.0

            force = False
            if self.dirty:             # 设置窗口刚改了参数
                self.dirty = False
                self.reload_layout()
                force = True
            if self.cfg_dirty and now - self.last_cfg_save > 0.5:
                self.cfg_dirty = False
                self.last_cfg_save = now
                save_config(self.cfg)

            self.keep_on_top(now)
            active, changed = self.refresh(now)
            changed = changed or force
            if self.handle_drag():
                changed = True

            # 切移动模式时边框提示色要跟着变
            if self.move_mode != last_move_mode:
                last_move_mode = self.move_mode
                changed = True

            if changed:
                self.push(render(self.keys, self.cps_rect, self.last_cps_text,
                                 self.win_w, self.win_h, active,
                                 self.cfg, self.scale, self.move_mode))
            time.sleep(0.008)

        self.cfg["position_x"], self.cfg["position_y"] = self.x, self.y
        save_config(self.cfg)
        try:
            self.input.stop()
        except Exception:
            pass
        try:
            user32.DestroyWindow(self.hwnd)
        except Exception:
            pass


def main():
    cfg = load_config()
    ov = Overlay(cfg)
    log_note("启动：缩放 %.2f 尺寸 %dx%d 位置 (%d,%d) 移动模式 %s" % (
        ov.scale, ov.win_w, ov.win_h, ov.x, ov.y, ov.move_mode))
    ov.run()
    log_note("退出：%s" % ov.exit_reason)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error(traceback.format_exc())
        raise