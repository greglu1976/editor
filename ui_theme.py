# -*- coding: utf-8 -*-
"""Единая тема оформления редактора электрических схем.

Модуль НЕ меняет бизнес-логику и НЕ требует перехода на другой
GUI-фреймворк. Он решает три задачи:

1. :func:`apply` -- один раз задаёт палитру, шрифты и стили ``ttk`` для
   всего приложения. База опций Tk распространяется и на диалоги из
   ``library.py`` / ``pdfexport.py``, поэтому их можно не трогать.
2. :func:`recolor` -- приводит «исторические» жёстко заданные цвета и
   шрифты Arial к новой палитре. Это позволяет не переписывать ~150
   строк с ``bg=`` / ``font=`` в ``main.py``: виджеты нормализуются
   обходом дерева после построения окна.
3. :func:`stabilize` -- фиксирует стартовую геометрию главного окна,
   чтобы переключение вкладок ленты не меняло его размер.

Тема включается автоматически из ``CircuitEditor.__init__``. Для полного
отката достаточно убрать вызов :func:`apply`: все константы определены в
одном месте, а цвета, которые приложение меняет динамически, берутся из
``ui_theme.*`` и при откате остаются корректными.
"""

try:                        # константы темы доступны и без Tk (тесты/CI)
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import ttk
except ImportError:         # pragma: no cover - зависит от сборки Python
    tk = tkfont = ttk = None

_TclError = tk.TclError if tk is not None else Exception

# ============================ ПАЛИТРА =====================================
# Светлая «деловая» гамма. ACCENT намеренно совпадает с фирменным синим,
# которым уже рисуются шкафы и связи на полотне (#1f4e79), чтобы лента,
# диалоги и схема выглядели одним продуктом.
WINDOW = "#f5f7fa"        # фон окон и диалогов
RIBBON = "#ffffff"        # рабочая область ленты
TABBAR = "#e8eef6"        # полоса вкладок
TAB_ACTIVE = "#ffffff"    # активная вкладка «сливается» с лентой
PALETTE = "#f1f5fa"       # левая палитра элементов
CANVAS = "#ffffff"        # полотно, поля ввода, таблицы
HOVER = "#e3eefb"         # подсветка кнопок ленты
BORDER = "#d7dfe9"        # разделители и рамки
ACCENT = "#1f4e79"        # фирменный синий
ACCENT_SOFT = "#2f6da5"
TEXT = "#1f2730"          # основной текст
TEXT_SOFT = "#46515f"     # вторичный текст
TEXT_MUTED = "#697586"    # подписи групп, подсказки
TEXT_FAINT = "#8d98a6"    # самые мелкие примечания
ON_ACCENT = "#ffffff"

# Шрифт: «Segoe UI» на Windows, переносимые запасные варианты на Linux/macOS.
FONT_FAMILY = "Segoe UI"
_FONT_CANDIDATES = ("Segoe UI", "Segoe UI Variable", "Inter", "Roboto",
                    "DejaVu Sans", "Helvetica", "Arial")
FIXED_FONT_FAMILY = "Courier New"

DEFAULT_WIDTH, DEFAULT_HEIGHT = 1440, 900
MIN_WIDTH, MIN_HEIGHT = 1040, 660

# «Исторические» цвета, которыми виджеты заданы явно в main.py/library.py.
# Цвета элементов схемы (create_line/create_text) сюда НЕ входят: обход
# дерева меняет только опции виджетов, рисунок на полотне не затрагивается.
LEGACY_COLORS = {
    "#f3f3f3": RIBBON,
    "#e4e4e4": TABBAR,
    "#f0f0f0": PALETTE,
    "#f7f7f7": RIBBON,
    "#e8e8e8": TABBAR,
    "#dce9f7": HOVER,
    "#eef3f8": WINDOW,
    "#f2f6fb": WINDOW,
    "#f7fafd": WINDOW,
    "#fdfdf7": CANVAS,
    "#d8d8d8": BORDER,
    "#c3d2e0": BORDER,
    "#b0b0b0": BORDER,
    "#a8a8a8": BORDER,
    "#808080": TEXT_MUTED,
    "#8a8a8a": TEXT_MUTED,
    "#8a9bb0": TEXT_MUTED,
    "#9a9a9a": TEXT_FAINT,
    "#999999": TEXT_FAINT,
    "#6f6f6f": TEXT_MUTED,
    "#777777": TEXT_MUTED,
    "#555555": TEXT_SOFT,
    "#404040": TEXT_SOFT,
    "#333333": TEXT,
}

# Канонические имена опций (алиасы bg/fg пропускаем, чтобы не настраивать
# один и тот же ресурс дважды).
_COLOR_OPTIONS = frozenset((
    "background", "foreground", "activebackground", "activeforeground",
    "disabledforeground", "highlightbackground", "highlightcolor",
    "selectbackground", "selectforeground", "insertbackground",
    "readonlybackground", "troughcolor",
))



# ============================ ШРИФТЫ ======================================
#: Ниже 8 pt интерфейсные подписи нечитаемы на современных экранах.
MIN_FONT_SIZE = 8


def font(size=9, *style):
    """Шрифт темы: ``font(9, "bold")`` -> ``("Segoe UI", 9, "bold")``."""
    return (FONT_FAMILY, max(MIN_FONT_SIZE, int(size))) + tuple(style)


def font_spec(size=9, *style):
    """Тот же шрифт строкой для базы опций Tk."""
    parts = ["{%s}" % FONT_FAMILY, str(size)] + [str(item) for item in style]
    return " ".join(parts)


def _resolve_family(root):
    try:
        available = set(tkfont.families(root))
    except _TclError:
        available = set()
    for name in _FONT_CANDIDATES:
        if name in available:
            return name
    return "TkDefaultFont"


# ============================ ПРИМЕНЕНИЕ ==================================
def apply(root):
    """Включает тему для ``root`` и всех последующих окон приложения.

    Вызывается до построения виджетов: база опций Tk влияет только на
    виджеты, созданные после неё.
    """
    if tk is None:
        raise RuntimeError("ui_theme.apply() требует Python со сборкой Tk")
    global FONT_FAMILY
    FONT_FAMILY = _resolve_family(root)
    base_spec = font_spec(9)

    # Значения по умолчанию для классических виджетов без явного bg/fg/font.
    root.option_add("*font", base_spec)
    root.option_add("*Background", WINDOW)
    root.option_add("*Foreground", TEXT)
    root.option_add("*Canvas.Background", CANVAS)
    root.option_add("*Entry.Background", CANVAS)
    root.option_add("*Entry.Foreground", TEXT)
    root.option_add("*Entry.insertBackground", TEXT)
    root.option_add("*Text.Background", CANVAS)
    root.option_add("*Text.Foreground", TEXT)
    root.option_add("*Listbox.Background", CANVAS)
    root.option_add("*Listbox.selectBackground", ACCENT)
    root.option_add("*Listbox.selectForeground", ON_ACCENT)
    root.option_add("*Button.activeBackground", HOVER)
    root.option_add("*Button.activeForeground", ACCENT)
    # Классические tk.Scrollbar есть и в main.py, и в диалогах library.py:
    # красим их через базу опций, не переписывая каждый вызов.
    root.option_add("*Scrollbar.background", TABBAR)
    root.option_add("*Scrollbar.troughColor", WINDOW)
    root.option_add("*Scrollbar.activeBackground", HOVER)
    root.option_add("*Scrollbar.highlightBackground", WINDOW)
    root.option_add("*Scrollbar.relief", "flat")
    root.option_add("*selectBackground", ACCENT)
    root.option_add("*selectForeground", ON_ACCENT)

    # Именованные шрифты Tk -- ими пользуются виджеты без явного font=.
    for name, size, weight in (("TkDefaultFont", 9, "normal"),
                               ("TkTextFont", 9, "normal"),
                               ("TkMenuFont", 9, "normal"),
                               ("TkHeadingFont", 9, "bold")):
        try:
            tkfont.nametofont(name).configure(family=FONT_FAMILY, size=size,
                                              weight=weight)
        except (_TclError, KeyError):
            pass

    _configure_ttk(root)
    _install_autotint(root)
    return root


def _configure_ttk(root):
    """Стили ttk: «clam» даёт предсказуемые цвета на всех платформах."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except _TclError:
        pass

    style.configure(".", background=WINDOW, foreground=TEXT,
                    fieldbackground=CANVAS, bordercolor=BORDER,
                    focuscolor=ACCENT, font=font(9))
    style.configure("TFrame", background=WINDOW)
    style.configure("TLabel", background=WINDOW, foreground=TEXT)
    style.configure("TLabelframe", background=WINDOW, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=WINDOW,
                    foreground=TEXT_SOFT, font=font(9, "bold"))
    style.configure("TButton", background=RIBBON, foreground=TEXT,
                    bordercolor=BORDER, padding=(9, 5), font=font(9))
    style.map("TButton",
              background=[("pressed", BORDER), ("active", HOVER)],
              foreground=[("active", ACCENT), ("disabled", TEXT_FAINT)])
    style.configure("Accent.TButton", background=ACCENT, foreground=ON_ACCENT,
                    bordercolor=ACCENT, font=font(9, "bold"))
    style.map("Accent.TButton",
              background=[("active", ACCENT_SOFT), ("pressed", ACCENT)],
              foreground=[("active", ON_ACCENT)])

    style.configure("Treeview", background=CANVAS, fieldbackground=CANVAS,
                    foreground=TEXT, bordercolor=BORDER, rowheight=23,
                    font=font(9))
    style.map("Treeview",
              background=[("selected", ACCENT)],
              foreground=[("selected", ON_ACCENT)])
    style.configure("Treeview.Heading", background=TABBAR,
                    foreground=TEXT_SOFT, bordercolor=BORDER,
                    font=font(9, "bold"), padding=(8, 5))
    style.map("Treeview.Heading", background=[("active", HOVER)])
    style.configure("TNotebook", background=WINDOW, bordercolor=BORDER)
    style.configure("TNotebook.Tab", background=TABBAR, foreground=TEXT_MUTED,
                    bordercolor=BORDER, padding=(12, 6), font=font(9))
    style.map("TNotebook.Tab",
              background=[("selected", TAB_ACTIVE)],
              foreground=[("selected", ACCENT)])
    style.configure("TEntry", fieldbackground=CANVAS, bordercolor=BORDER,
                    padding=4)
    style.configure("TCombobox", fieldbackground=CANVAS,
                    background=CANVAS, arrowcolor=TEXT_SOFT)
    style.configure("TCheckbutton", background=WINDOW, foreground=TEXT)
    style.configure("TRadiobutton", background=WINDOW, foreground=TEXT)
    style.configure("TScrollbar", background=TABBAR, troughcolor=WINDOW,
                    bordercolor=BORDER, arrowcolor=TEXT_SOFT)
    style.configure("TSeparator", background=BORDER)
    style.configure("TProgressbar", background=ACCENT,
                    troughcolor=WINDOW, bordercolor=BORDER)
    return style


# ============================ НОРМАЛИЗАЦИЯ ================================
def recolor(widget):
    """Рекурсивно приводит цвета и шрифты поддерева виджетов к теме.

    Меняются только опции самих виджетов. Цвета линий/текста, созданных на
    ``Canvas`` через ``create_*``, и цвета тегов ``Text``/``Treeview``
    остаются нетронутыми -- рисунок схемы и смысловая раскраска дерева
    сохраняются.
    """
    try:
        options = widget.configure()
    except (_TclError, AttributeError, TypeError):
        options = {}

    for name, cfg in options.items():
        if not isinstance(cfg, tuple) or len(cfg) < 5:
            continue
        value = cfg[4]
        if name in _COLOR_OPTIONS and isinstance(value, str):
            replacement = LEGACY_COLORS.get(value.strip().lower())
            if replacement and replacement.lower() != value.strip().lower():
                try:
                    widget.configure(**{name: replacement})
                except _TclError:
                    pass
        elif name == "font" and isinstance(value, str):
            _replace_font(widget, value)

    try:
        children = widget.winfo_children()
    except (_TclError, AttributeError):
        return widget
    for child in children:
        recolor(child)
    return widget


def _replace_font(widget, value):
    """``"Arial 9 bold"`` -> шрифт темы. Моноширинные шрифты не трогаем."""
    parts = value.split()
    if len(parts) < 2 or parts[0].lower() != "arial":
        return
    try:
        size = int(parts[1])
    except ValueError:
        return
    try:
        widget.configure(font=font(size, *parts[2:]))  # 6/7 pt -> минимум 8
    except _TclError:
        pass


def _install_autotint(root):
    """Красит окна, создаваемые позже (каталоги, формы, отчёты, подсказки).

    ``<Map>`` приходит к каждому новому ``Toplevel``; обработчик срабатывает
    один раз на окно и не мешает уже назначенным обработчикам (``add="+"``).
    """
    # Признак хранится на самом объекте окна: строковые имена Tk (".",
    # ".<toplevel>") повторно используются после destroy(), поэтому набор
    # имён здесь был бы ненадёжен.
    if getattr(root, "_ui_theme_tint_installed", False):
        return
    root._ui_theme_tint_installed = True
    seen = set()

    def on_map(event):
        target = event.widget
        if not isinstance(target, (tk.Tk, tk.Toplevel)):
            return
        key = str(target)
        if key in seen:
            return
        seen.add(key)

        def tint(window=target):
            try:
                if window.winfo_exists():
                    recolor(window)
            except _TclError:
                pass

        root.after_idle(tint)

    root.bind_all("<Map>", on_map, add="+")


# ============================ ГЕОМЕТРИЯ ===================================
def stabilize(root, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    """Фиксирует стартовый размер главного окна и минимальные границы.

    Явная геометрия -- ключ к стабильности: без неё Tk пересчитывает размер
    окна по содержимому ленты, а вкладки имеют разную запрошенную ширину
    и высоту. Пользователь по-прежнему может менять размер вручную.
    """
    try:
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
    except _TclError:
        screen_w, screen_h = width, height
    w = max(640, min(width, screen_w - 40)) if screen_w else width
    h = max(480, min(height, screen_h - 60)) if screen_h else height
    x = max(0, (screen_w - w) // 2)
    y = max(0, (screen_h - h) // 3)
    root.geometry("%dx%d+%d+%d" % (w, h, x, y))
    root.minsize(min(MIN_WIDTH, w), min(MIN_HEIGHT, h))
    return w, h
