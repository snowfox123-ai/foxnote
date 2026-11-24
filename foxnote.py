#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import locale
import tempfile
import re
import json
import subprocess
import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio, Gdk, GLib, Pango

try:
    gi.require_version("GtkSource", "5")
    from gi.repository import GtkSource
    HAS_SOURCE = True
except (ValueError, ImportError):
    HAS_SOURCE = False

APP_NAME = "FoxNote"
APP_ID = "org.foxnote.FoxNote"

# FIX: GtkSourceView 5.0~5.3 之间 undo API 有变动，做个能力探测
if HAS_SOURCE:
    _probe = GtkSource.Buffer()
    HAS_UNDO_API = hasattr(_probe, "set_enable_undo") and hasattr(_probe, "get_can_undo")
    del _probe
else:
    HAS_UNDO_API = False


# ---------------------------------------------------------------------------
# 会话持久化
# ---------------------------------------------------------------------------
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "foxnote")
SESSION_FILE = os.path.join(CONFIG_DIR, "session.json")

# FIX: 会话中内联保存未保存文档的单个内容上限（字节）
MAX_INLINE_DRAFT = 512 * 1024


def _load_session():
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_session(data):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = SESSION_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SESSION_FILE)
    except OSError:
        pass


def _read_text(path):
    """返回 (text, encoding)。优先保留 BOM 状态和系统编码。"""
    with open(path, "rb") as f:
        head = f.read(3)
    if head == b"\xef\xbb\xbf":
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read(), "utf-8-sig"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), "utf-8"
    except UnicodeDecodeError:
        pass
    enc = locale.getpreferredencoding(False)
    try:
        with open(path, "r", encoding=enc) as f:
            return f.read(), enc
    except (UnicodeDecodeError, LookupError):
        pass
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read(), "utf-8"


def _selection(buffer):
    """返回 (start_iter, end_iter)。调用前应确保 get_has_selection() 为真。"""
    bounds = buffer.get_selection_bounds()
    if len(bounds) == 3:
        return bounds[1], bounds[2]
    return bounds[0], bounds[1]


# ---------------------------------------------------------------------------
# 单个标签页 = 一个 Document
# ---------------------------------------------------------------------------
class Document:
    def __init__(self, window, path=None, content="", encoding="utf-8"):
        self.window = window
        self.path = path
        self.display_name = None
        self.encoding = encoding

        self.tab_label = None

        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_hexpand(True)
        self.scrolled.set_vexpand(True)

        if HAS_SOURCE:
            self.buffer = GtkSource.Buffer()
            # FIX: set_enable_undo 在 GtkSourceView 5.0~5.3 不存在
            if HAS_UNDO_API:
                try:
                    self.buffer.set_enable_undo(True)
                except Exception:
                    pass
            self.buffer.set_highlight_syntax(True)
            self.buffer.set_highlight_matching_brackets(True)
            self.view = GtkSource.View(buffer=self.buffer)
            self.view.set_show_line_numbers(True)
            self.view.set_highlight_current_line(True)
            self.view.set_auto_indent(True)
            self.view.set_tab_width(4)
            self.view.set_insert_spaces_instead_of_tabs(True)
        else:
            self.buffer = Gtk.TextBuffer()
            self.buffer.set_enable_undo(True)
            self.view = Gtk.TextView(buffer=self.buffer)
            self.view.set_monospace(True)
            self.view.set_top_margin(6)
            self.view.set_bottom_margin(6)
            self.view.set_left_margin(8)
            self.view.set_right_margin(8)

        self.scrolled.set_child(self.view)

        if content:
            self.buffer.set_text(content)
        self.buffer.set_modified(False)
        self.buffer.connect("modified-changed", self._on_modified_changed)

        self._setup_context_menu()
        self.update_language_for_path(path)
        self.apply_style_scheme(window.dark)

    def update_language_for_path(self, path):
        if not HAS_SOURCE:
            return
        lm = GtkSource.LanguageManager.get_default()
        # FIX: guess_language 需要 (filename, content_type) 两个参数
        try:
            lang = lm.guess_language(path, None) if path else None
        except TypeError:
            lang = lm.guess_language(path) if path else None
        self.buffer.set_language(lang)

    def apply_style_scheme(self, dark):
        if not HAS_SOURCE:
            return
        mgr = GtkSource.StyleSchemeManager.get_default()
        candidates = ("Adwaita-dark", "oblivion", "solarized-dark") if dark \
            else ("Adwaita", "classic", "solarized-light")
        for sid in candidates:
            scheme = mgr.get_scheme(sid)
            if scheme is not None:
                self.buffer.set_style_scheme(scheme)
                return

    def set_wrap(self, enabled):
        self.view.set_wrap_mode(
            Gtk.WrapMode.WORD_CHAR if enabled else Gtk.WrapMode.NONE
        )

    def _on_modified_changed(self, buffer):
        self.window._update_tab_title(self)
        if self.window.get_current_doc() is self:
            self.window._update_title()
        self.window.status.set_text("已修改" if buffer.get_modified() else "就绪")

    def cleanup(self):
        try:
            if self.popover.get_parent() is not None:
                self.popover.unparent()
        except Exception:
            pass

    def _setup_context_menu(self):
        self.popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(4)
        box.set_margin_end(4)
        self.popover.set_child(box)

        def add(label, cb):
            b = Gtk.Button(label=label)
            b.add_css_class("flat")
            b.connect("clicked", lambda _b: (self.popover.popdown(), cb()))
            box.append(b)

        def sep():
            box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        add("撤销", self._undo)
        add("重做", self._redo)
        sep()
        add("剪切", lambda: self.view.emit("cut-clipboard"))
        add("复制", lambda: self.view.emit("copy-clipboard"))
        add("粘贴", lambda: self.view.emit("paste-clipboard"))
        add("全选", self._select_all)

        gesture = Gtk.GestureClick()
        gesture.set_button(3)
        gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gesture.connect("pressed", self._on_right_click)
        self.view.add_controller(gesture)

    def _on_right_click(self, gesture, n_press, x, y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET,
                                                   int(x), int(y))
        ok, over_iter = self.view.get_iter_at_location(bx, by)
        if ok:
            if self.buffer.get_has_selection():
                s, e = _selection(self.buffer)
                if (over_iter.get_offset() < s.get_offset()
                        or over_iter.get_offset() >= e.get_offset()):
                    self.buffer.place_cursor(over_iter)
            else:
                self.buffer.place_cursor(over_iter)

        if self.popover.get_parent() is None:
            self.popover.set_parent(self.view)
        if self.popover.get_visible():
            self.popover.popdown()
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self.popover.set_pointing_to(rect)
        self.popover.popup()

    def _undo(self):
        if not HAS_UNDO_API:
            return
        try:
            if self.buffer.get_can_undo():
                self.buffer.undo()
            self.view.grab_focus()
        except Exception:
            pass

    def _redo(self):
        if not HAS_UNDO_API:
            return
        try:
            if self.buffer.get_can_redo():
                self.buffer.redo()
            self.view.grab_focus()
        except Exception:
            pass

    def _select_all(self):
        self.buffer.select_range(self.buffer.get_start_iter(),
                                 self.buffer.get_end_iter())
        self.view.grab_focus()


# ---------------------------------------------------------------------------
# 语言 ID → 保存时默认扩展名
# ---------------------------------------------------------------------------
LANG_EXT = {
    "python": ".py",
    "html": ".html",
    "js": ".js",
    "css": ".css",
    "markdown": ".md",
    "json": ".json",
    "php": ".php",
    "sh": ".sh"
}


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class FoxNoteWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application)
        self.application = application
        self.docs = []
        self.dark = False
        self.wrap = True
        self._pending_close = []
        self._last_sidebar_pos = 200

        self.set_default_size(950, 650)
        self.set_title(APP_NAME)

        self._build_ui()
        self._apply_theme()
        self.connect("close-request", self._on_close_request)

        if not self._restore_session():
            self.new_file()
        self._update_title()

    # ------------------------------------------------------------------
    # 会话恢复
    # ------------------------------------------------------------------
    def _restore_session(self):
        sess = _load_session()
        if not sess:
            return False

        width = sess.get("width")
        height = sess.get("height")
        if isinstance(width, int) and isinstance(height, int) \
                and width > 200 and height > 200:
            self.set_default_size(width, height)

        self.dark = bool(sess.get("dark", False))
        self.wrap = bool(sess.get("wrap", True))
        if self.dark:
            self.dark_btn.set_icon_name("weather-clear-symbolic")
            self._apply_theme()

        if not sess.get("sidebar", True):
            self.sidebar_revealer.set_reveal_child(False)
            self.sidebar_btn.set_icon_name("sidebar-show-symbolic")
            self.paned.set_position(0)
        else:
            pos = sess.get("sidebar_pos", 200)
            if isinstance(pos, int) and pos >= 0:
                self._last_sidebar_pos = pos
                self.paned.set_position(pos)

        opened = False

        # FIX: 恢复磁盘文件
        files = sess.get("files", [])
        if isinstance(files, list):
            for item in files:
                if not isinstance(item, dict):
                    continue
                path = item.get("path")
                if not path or not os.path.isfile(path):
                    continue
                try:
                    data, enc = _read_text(path)
                except OSError:
                    continue
                doc = self._new_tab(path, data, enc)
                doc.set_wrap(self.wrap)
                cursor = item.get("cursor")
                if isinstance(cursor, int) and cursor >= 0:
                    it = doc.buffer.get_iter_at_offset(
                        min(cursor, doc.buffer.get_char_count())
                    )
                    doc.buffer.place_cursor(it)
                    doc.view.scroll_to_iter(it, 0.0, False, 0.0, 0.0)
                opened = True

        # FIX: 恢复未保存的草稿（内存中的内容）
        drafts = sess.get("drafts", [])
        if isinstance(drafts, list):
            for item in drafts:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or "未命名"
                content = item.get("content")
                if not isinstance(content, str):
                    continue
                doc = self._new_tab(None, content, "utf-8")
                doc.display_name = name
                doc.set_wrap(self.wrap)
                doc.update_language_for_path(None)
                cursor = item.get("cursor")
                if isinstance(cursor, int) and cursor >= 0:
                    it = doc.buffer.get_iter_at_offset(
                        min(cursor, doc.buffer.get_char_count())
                    )
                    doc.buffer.place_cursor(it)
                # 草稿视为已修改（用户还需要保存它）
                doc.buffer.set_modified(True)
                opened = True

        return opened

    def _save_session(self):
        # FIX: 多窗口时只让最后一个存活的窗口保存会话，
        # 避免先关闭的窗口覆盖后关闭窗口的会话
        app = self.get_application()
        if app is not None:
            others = [w for w in app.get_windows() if w is not self]
            if others:
                return  # 还有别的窗口，让最后关闭的那个来保存

        files = []
        drafts = []
        for d in self.docs:
            it = d.buffer.get_iter_at_mark(d.buffer.get_insert())
            cursor = it.get_offset()
            if d.path:
                files.append({"path": d.path, "cursor": cursor})
            else:
                # FIX: 未保存文档的内联草稿
                text = d.buffer.get_text(
                    d.buffer.get_start_iter(),
                    d.buffer.get_end_iter(),
                    False,
                )
                if not text.strip():
                    continue  # 空白未命名标签页不值得保存
                if len(text.encode("utf-8", "replace")) > MAX_INLINE_DRAFT:
                    continue  # 太大，跳过（避免 session.json 爆炸）
                drafts.append({
                    "name": d.display_name or "未命名",
                    "content": text,
                    "cursor": cursor,
                })

        sidebar_visible = self.sidebar_revealer.get_reveal_child()
        pos = self.paned.get_position()
        if sidebar_visible and pos > 0:
            self._last_sidebar_pos = pos

        _save_session({
            "width": self.get_width(),
            "height": self.get_height(),
            "dark": self.dark,
            "wrap": self.wrap,
            "sidebar": sidebar_visible,
            "sidebar_pos": self._last_sidebar_pos,
            "files": files,
            "drafts": drafts,
        })

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        header = Gtk.HeaderBar()
        self.set_titlebar(header)

        self.sidebar_btn = Gtk.ToggleButton(icon_name="sidebar-hide-symbolic")
        self.sidebar_btn.set_tooltip_text("折叠/展开侧栏 (F9)")
        self.sidebar_btn.set_action_name("app.toggle-sidebar")
        self.sidebar_btn.set_active(True)
        header.pack_start(self.sidebar_btn)

        for icon, tip, action in (
            ("document-new-symbolic", "新建标签页 (Ctrl+N)", "app.new"),
            ("document-open-symbolic", "打开 (Ctrl+O)", "app.open"),
            ("document-save-symbolic", "保存 (Ctrl+S)", "app.save"),
            ("document-print-symbolic", "打印 (Ctrl+P)", "app.print"),
            ("window-new-symbolic", "新建窗口 (Ctrl+Shift+N)", "app.new-window"),
        ):
            btn = Gtk.Button(icon_name=icon)
            btn.set_tooltip_text(tip)
            btn.set_action_name(action)
            header.pack_start(btn)

        self.dark_btn = Gtk.ToggleButton(icon_name="weather-clear-night-symbolic")
        self.dark_btn.set_tooltip_text("深色模式 (Ctrl+D)")
        self.dark_btn.set_action_name("app.toggle-dark")
        header.pack_end(self.dark_btn)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(vbox)

        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.paned.set_vexpand(True)
        self.paned.set_position(200)
        self.paned.set_resize_start_child(False)
        self.paned.set_shrink_start_child(True)
        self.paned.connect("notify::position", self._on_paned_position)
        vbox.append(self.paned)

        self.sidebar_revealer = Gtk.Revealer()
        self.sidebar_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_RIGHT)
        self.sidebar_revealer.set_transition_duration(200)
        self.sidebar_revealer.set_reveal_child(True)
        sidebar_content = self._build_sidebar()
        self.sidebar_revealer.set_child(sidebar_content)
        self.paned.set_start_child(self.sidebar_revealer)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.paned.set_end_child(main_box)

        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_vexpand(True)
        self.notebook.connect("switch-page", self._on_switch_page)
        main_box.append(self.notebook)

        self.find_revealer = Gtk.Revealer()
        self.find_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.find_revealer.set_reveal_child(False)
        self._build_find_bar()
        main_box.append(self.find_revealer)

        self.status = Gtk.Label(label="就绪")
        if not HAS_SOURCE:
            self.status.set_text("提示：未检测到 GtkSourceView，语法高亮与行号不可用。")
        self.status.set_xalign(0)
        self.status.set_margin_start(8)
        self.status.set_margin_end(8)
        self.status.set_margin_top(4)
        self.status.set_margin_bottom(4)
        main_box.append(self.status)

    def _on_paned_position(self, paned, _pspec):
        if self.sidebar_revealer.get_reveal_child():
            pos = paned.get_position()
            if pos > 0:
                self._last_sidebar_pos = pos

    def _build_sidebar(self):
        side_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        side_box.add_css_class("background")
        side_box.set_margin_top(8)
        side_box.set_margin_bottom(8)
        side_box.set_margin_start(8)
        side_box.set_margin_end(8)

        def add_btn(label, icon_name, action):
            btn = Gtk.Button()
            btn.add_css_class("flat")
            btn.set_halign(Gtk.Align.FILL)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            if icon_name:
                icon = Gtk.Image.new_from_icon_name(icon_name)
                box.append(icon)
            lbl = Gtk.Label(label=label)
            lbl.set_xalign(0)
            lbl.set_hexpand(True)
            box.append(lbl)
            btn.set_child(box)
            if action:
                btn.set_action_name(action)
            return btn

        def add_sep():
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.set_margin_top(6)
            sep.set_margin_bottom(6)
            side_box.append(sep)

        side_box.append(add_btn("新建标签页", "document-new-symbolic", "app.new"))
        side_box.append(add_btn("新建窗口", "window-new-symbolic", "app.new-window"))
        side_box.append(add_btn("打开...", "document-open-symbolic", "app.open"))
        side_box.append(add_btn("保存", "document-save-symbolic", "app.save"))
        side_box.append(add_btn("另存为...", "document-save-as-symbolic", "app.save-as"))
        side_box.append(add_btn("打印...", "document-print-symbolic", "app.print"))
        add_sep()

        side_box.append(add_btn("撤销", "edit-undo-symbolic", "app.undo"))
        side_box.append(add_btn("重做", "edit-redo-symbolic", "app.redo"))
        side_box.append(add_btn("剪切", "edit-cut-symbolic", "app.cut"))
        side_box.append(add_btn("复制", "edit-copy-symbolic", "app.copy"))
        side_box.append(add_btn("粘贴", "edit-paste-symbolic", "app.paste"))
        side_box.append(add_btn("全选", "edit-select-all-symbolic", "app.select-all"))
        add_sep()

        side_box.append(add_btn("重命名标签页", "document-edit-symbolic", "app.rename-tab"))
        side_box.append(add_btn("关闭标签页", "window-close-symbolic", "app.close-tab"))
        add_sep()

        side_box.append(add_btn("查找...", "edit-find-symbolic", "app.show-find"))
        side_box.append(add_btn("替换...", "edit-find-replace-symbolic", "app.show-replace"))
        add_sep()

        lang_btn = Gtk.MenuButton()
        lang_btn.add_css_class("flat")
        lang_btn.set_halign(Gtk.Align.FILL)
        lang_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lang_box.append(Gtk.Image.new_from_icon_name("accessories-text-editor-symbolic"))
        lbl = Gtk.Label(label="语言")
        lbl.set_xalign(0)
        lbl.set_hexpand(True)
        lang_box.append(lbl)
        lang_box.append(Gtk.Image.new_from_icon_name("pan-end-symbolic"))
        lang_btn.set_child(lang_box)

        if HAS_SOURCE:
            lang_menu = Gio.Menu()
            for name, lang_id in (
                ("纯文本", "none"),
                ("Python", "python"), ("HTML", "html"), ("JavaScript", "js"),
                ("CSS", "css"), ("JSON", "json"), ("PHP", "php"),
                ("Shell", "sh"), ("Markdown", "markdown"),
            ):
                item = Gio.MenuItem.new(name, None)
                item.set_action_and_target_value(
                    "app.set-lang", GLib.Variant.new_string(lang_id)
                )
                lang_menu.append_item(item)
            lang_btn.set_menu_model(lang_menu)
        else:
            lang_btn.set_sensitive(False)
        side_box.append(lang_btn)

        add_sep()
        side_box.append(add_btn("自动换行", "format-justify-fill-symbolic", "app.toggle-wrap"))
        side_box.append(add_btn("深色模式", "weather-clear-night-symbolic", "app.toggle-dark"))
        add_sep()
        side_box.append(add_btn("退出", "application-exit-symbolic", "app.quit"))

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_child(side_box)
        scrolled.set_vexpand(True)
        return scrolled

    def toggle_sidebar(self):
        reveal = not self.sidebar_revealer.get_reveal_child()
        self.sidebar_revealer.set_reveal_child(reveal)
        if reveal:
            self.sidebar_btn.set_icon_name("sidebar-hide-symbolic")
            self.paned.set_position(getattr(self, '_last_sidebar_pos', 200))
        else:
            self.sidebar_btn.set_icon_name("sidebar-show-symbolic")
            self._last_sidebar_pos = self.paned.get_position()
            self.paned.set_position(0)

    def _build_find_bar(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        outer.set_margin_start(8)
        outer.set_margin_end(8)
        outer.set_margin_top(6)
        outer.set_margin_bottom(6)
        self.find_revealer.set_child(outer)

        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        outer.append(row1)
        row1.append(Gtk.Label(label="查找"))
        self.find_entry = Gtk.Entry()
        self.find_entry.set_hexpand(True)
        self.find_entry.connect("activate", lambda e: self.find_next())
        row1.append(self.find_entry)
        self.case_check = Gtk.CheckButton(label="区分大小写")
        row1.append(self.case_check)
        for label, cb in (("上一个", self.find_prev),
                          ("下一个", self.find_next),
                          ("×", self.hide_find)):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, cb=cb: cb())
            row1.append(b)

        self.row_replace = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        outer.append(self.row_replace)
        self.row_replace.set_visible(False)
        self.row_replace.append(Gtk.Label(label="替换"))
        self.replace_entry = Gtk.Entry()
        self.replace_entry.set_hexpand(True)
        self.replace_entry.connect("activate", lambda e: self.replace_one())
        self.row_replace.append(self.replace_entry)
        for label, cb in (("替换", self.replace_one),
                          ("全部替换", self.replace_all)):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, cb=cb: cb())
            self.row_replace.append(b)

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_find_key)
        self.find_entry.add_controller(key_ctrl)

    def _on_find_key(self, ctrl, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.hide_find()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if state & Gdk.ModifierType.SHIFT_MASK:
                self.find_prev()
            else:
                self.find_next()
            return True
        return False

    def _apply_theme(self):
        settings = Gtk.Settings.get_default()
        if settings:
            settings.props.gtk_application_prefer_dark_theme = self.dark
            try:
                settings.set_property(
                    "gtk-interface-color-scheme",
                    "prefer-dark" if self.dark else "default",
                )
            except Exception:
                pass
        for doc in self.docs:
            doc.apply_style_scheme(self.dark)

    def toggle_dark(self):
        self.dark = not self.dark
        if self.dark:
            self.dark_btn.set_icon_name("weather-clear-symbolic")
        else:
            self.dark_btn.set_icon_name("weather-clear-night-symbolic")
        self._apply_theme()

    def toggle_wrap(self):
        self.wrap = not self.wrap
        for d in self.docs:
            d.set_wrap(self.wrap)
        self.status.set_text("自动换行：开" if self.wrap else "自动换行：关")

    def _display_name(self, doc):
        if doc.path:
            return os.path.basename(doc.path)
        return doc.display_name or "未命名"

    def _tab_title(self, doc):
        mark = "*" if doc.buffer.get_modified() else ""
        return f"{mark}{self._display_name(doc)}"

    def _update_tab_title(self, doc):
        if doc.tab_label is not None:
            doc.tab_label.set_text(self._tab_title(doc))

    def get_current_doc(self):
        page = self.notebook.get_current_page()
        if page < 0:
            return None
        child = self.notebook.get_nth_page(page)
        for d in self.docs:
            if d.scrolled is child:
                return d
        return None

    def _on_switch_page(self, notebook, page, page_num):
        self._update_title()
        doc = self.get_current_doc()
        if doc and doc.buffer.get_modified():
            self.status.set_text("已修改")
        else:
            self.status.set_text("就绪")

    def new_file(self):
        self._new_tab()
        self.status.set_text("新建文件")

    def new_window(self):
        win = FoxNoteWindow(self.application)
        win.present()

    def _new_tab(self, path=None, content="", encoding="utf-8"):
        doc = Document(self, path, content, encoding)
        doc.set_wrap(self.wrap)
        self.docs.append(doc)

        tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        tab_box.set_size_request(-1, 28)
        doc.tab_label = Gtk.Label(label=self._tab_title(doc))
        doc.tab_label.set_ellipsize(Pango.EllipsizeMode.END)
        doc.tab_label.set_max_width_chars(24)
        doc.tab_label.set_width_chars(12)
        doc.tab_label.set_xalign(0)
        doc.tab_label.set_single_line_mode(True)
        tab_box.append(doc.tab_label)

        dbl = Gtk.GestureClick()
        dbl.set_button(1)
        dbl.connect("pressed", self._on_tab_double_click, doc)
        tab_box.add_controller(dbl)

        close_btn = Gtk.Button(icon_name="window-close-symbolic")
        close_btn.set_valign(Gtk.Align.CENTER)
        close_btn.add_css_class("flat")
        close_btn.set_tooltip_text("关闭标签页")
        close_btn.connect("clicked", lambda _b, d=doc: self.close_tab_by_doc(d))
        tab_box.append(close_btn)

        self.notebook.append_page(doc.scrolled, tab_box)
        self.notebook.set_current_page(self.notebook.get_n_pages() - 1)
        doc.view.grab_focus()
        self._update_title()
        return doc

    def _on_tab_double_click(self, gesture, n_press, x, y, doc):
        if n_press >= 2:
            self.prompt_rename(doc)
            return True
        return False

    def _update_title(self):
        doc = self.get_current_doc()
        if doc:
            mark = "*" if doc.buffer.get_modified() else ""
            self.set_title(f"{mark}{self._display_name(doc)} - {APP_NAME}")
        else:
            self.set_title(APP_NAME)

    def close_tab(self):
        doc = self.get_current_doc()
        if doc:
            self.close_tab_by_doc(doc)

    def close_tab_by_doc(self, doc):
        if doc.buffer.get_modified():
            self._ask_save_discard_cancel(
                doc,
                on_discard=lambda: self._do_close_tab(doc),
                on_saved=lambda: self._do_close_tab(doc),
            )
        else:
            self._do_close_tab(doc)

    def _ask_save_discard_cancel(self, doc, on_discard, on_saved=None, on_cancel=None):
        dlg = Gtk.Window(transient_for=self, modal=True)
        dlg.set_title("未保存的更改")
        dlg.set_default_size(350, -1)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)
        dlg.set_child(box)

        label = Gtk.Label()
        safe = GLib.markup_escape_text(self._tab_title(doc))
        label.set_markup(f"<b>{safe} 还没保存</b>")
        label.set_xalign(0)
        box.append(label)
        label2 = Gtk.Label(label="要保存改动吗？")
        label2.set_xalign(0)
        box.append(label2)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_halign(Gtk.Align.END)
        box.append(btn_box)

        def finish(response):
            dlg.destroy()
            if response == "discard":
                on_discard()
            elif response == "save":
                self._save_doc(doc, on_saved or on_discard, on_cancel)
            elif on_cancel:
                on_cancel()

        cancel_btn = Gtk.Button(label="取消")
        cancel_btn.connect("clicked", lambda _b: finish("cancel"))
        btn_box.append(cancel_btn)

        discard_btn = Gtk.Button(label="丢弃")
        discard_btn.connect("clicked", lambda _b: finish("discard"))
        btn_box.append(discard_btn)

        save_btn = Gtk.Button(label="保存")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", lambda _b: finish("save"))
        btn_box.append(save_btn)

        dlg.connect("close-request", lambda w: finish("cancel"))
        dlg.present()

    def _save_doc(self, doc, on_success=None, on_cancel=None):
        if doc is None:
            return
        if doc.path:
            if self._save_to(doc, doc.path):
                if on_success:
                    on_success()
            elif on_cancel:
                on_cancel()
        else:
            self._save_as_doc(doc, on_success, on_cancel)

    def _do_close_tab(self, doc):
        doc.cleanup()
        page = self.notebook.page_num(doc.scrolled)
        if page >= 0:
            self.notebook.remove_page(page)
        if doc in self.docs:
            self.docs.remove(doc)
        if not self.docs:
            self._new_tab()
        self._update_title()
        self.status.set_text("已关闭标签页")

    def undo(self):
        doc = self.get_current_doc()
        if doc:
            doc._undo()

    def redo(self):
        doc = self.get_current_doc()
        if doc:
            doc._redo()

    def cut(self):
        doc = self.get_current_doc()
        if doc:
            doc.view.emit("cut-clipboard")

    def copy(self):
        doc = self.get_current_doc()
        if doc:
            doc.view.emit("copy-clipboard")

    def paste(self):
        doc = self.get_current_doc()
        if doc:
            doc.view.emit("paste-clipboard")

    def select_all(self):
        doc = self.get_current_doc()
        if doc:
            doc.buffer.select_range(doc.buffer.get_start_iter(),
                                    doc.buffer.get_end_iter())
            doc.view.grab_focus()

    def set_language(self, lang_id):
        if not HAS_SOURCE:
            return
        doc = self.get_current_doc()
        if not doc:
            return
        lm = GtkSource.LanguageManager.get_default()

        if lang_id == "none":
            doc.buffer.set_language(None)
            self.status.set_text("已切换为纯文本")
        else:
            lang = lm.get_language(lang_id)
            if lang is None:
                target = lang_id.lower()
                for lid in lm.get_language_ids():
                    cand = lm.get_language(lid)
                    if cand is None:
                        continue
                    if cand.get_name().lower() == target or lid.lower() == target:
                        lang = cand
                        break
            if lang:
                doc.buffer.set_language(lang)
                self.status.set_text(f"语法：{lang.get_name()}")
            else:
                lang_id = "none"
                self.status.set_text(f"未找到语言：{lang_id}")

        # FIX: 同步 stateful action 的状态，菜单出现单选圆点
        app = self.get_application()
        if app is not None:
            act = app.lookup_action("set-lang")
            if act is not None and hasattr(act, "set_state"):
                act.set_state(GLib.Variant.new_string(lang_id))

    def prompt_rename(self, doc=None):
        if doc is None:
            doc = self.get_current_doc()
        if doc is None:
            return
        dlg = Gtk.Window(transient_for=self, modal=True)
        dlg.set_title("重命名")
        dlg.set_default_size(320, -1)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(14)
        box.set_margin_bottom(14)
        box.set_margin_start(14)
        box.set_margin_end(14)
        dlg.set_child(box)

        if doc.path:
            current = os.path.basename(doc.path)
        else:
            current = doc.display_name or "未命名"

        entry = Gtk.Entry()
        entry.set_text(current)
        entry.select_region(0, -1)
        box.append(entry)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_halign(Gtk.Align.END)
        box.append(row)

        def finish(ok):
            if ok:
                new_name = entry.get_text().strip()
                if new_name and new_name != current:
                    self._rename_doc(doc, new_name)
            dlg.destroy()

        cancel_btn = Gtk.Button(label="取消")
        cancel_btn.connect("clicked", lambda _b: finish(False))
        row.append(cancel_btn)
        ok_btn = Gtk.Button(label="确定")
        ok_btn.add_css_class("suggested-action")
        ok_btn.connect("clicked", lambda _b: finish(True))
        row.append(ok_btn)
        entry.connect("activate", lambda _e: finish(True))
        dlg.set_default_widget(ok_btn)
        dlg.present()
        entry.grab_focus()

    def _rename_doc(self, doc, new_name):
        if doc.path:
            directory = os.path.dirname(doc.path)
            new_path = os.path.join(directory, new_name)
            if os.path.normpath(new_path) == os.path.normpath(doc.path):
                return
            if os.path.exists(new_path):
                self._show_error("重命名失败", f"目标已存在：{new_path}")
                return
            try:
                os.rename(doc.path, new_path)
            except OSError as ex:
                self._show_error("重命名失败", str(ex))
                return
            doc.path = new_path
            doc.update_language_for_path(new_path)
            doc.apply_style_scheme(self.dark)
        else:
            doc.display_name = new_name
        self._update_tab_title(doc)
        self._update_title()
        self.status.set_text(f"已重命名为 {self._display_name(doc)}")

    def open_file(self):
        if hasattr(Gtk, "FileDialog"):
            self._open_with_filedialog()
        else:
            self._open_with_choosernative()

    def _open_with_filedialog(self):
        dialog = Gtk.FileDialog()
        dialog.set_title("打开文件")

        def on_done(d, result):
            path = None
            try:
                file = d.open_finish(result)
                if file:
                    path = file.get_path()
            except Exception:
                pass
            if not path:
                return
            try:
                data, encoding = _read_text(path)
            except OSError as ex:
                self._show_error("打不开", str(ex))
                return
            self._open_path(path, data, encoding)

        dialog.open(self, None, on_done)

    def _open_with_choosernative(self):
        dialog = Gtk.FileChooserNative.new(
            "打开文件", self, Gtk.FileChooserAction.OPEN, "打开", "取消")
        filt = Gtk.FileFilter()
        filt.set_name("文本 / 代码")
        for p in ("*.txt", "*.md", "*.py", "*.html", "*.htm",
                  "*.js", "*.css", "*.json", "*"):
            filt.add_pattern(p)
        dialog.add_filter(filt)
        dialog.connect("response", self._on_open_response)
        dialog.show()

    def _on_open_response(self, dialog, response):
        try:
            if response == Gtk.ResponseType.ACCEPT:
                file = dialog.get_file()
                if not file:
                    return
                path = file.get_path()
                if not path:
                    self._show_error("打不开", "目前只支持本地文件")
                    return
                try:
                    data, encoding = _read_text(path)
                except OSError as ex:
                    self._show_error("打不开", str(ex))
                    return
                self._open_path(path, data, encoding)
        finally:
            try:
                dialog.destroy()
            except Exception:
                pass

    def _open_path(self, path, data, encoding="utf-8"):
        doc = self.get_current_doc()
        empty = (
            doc and doc.path is None
            and not doc.buffer.get_modified()
            and not doc.buffer.get_text(
                doc.buffer.get_start_iter(),
                doc.buffer.get_end_iter(), False).strip()
        )
        if empty:
            doc.buffer.set_text(data)
            doc.buffer.set_modified(False)
            doc.path = path
            doc.display_name = None
            doc.encoding = encoding
            doc.update_language_for_path(path)
            doc.apply_style_scheme(self.dark)
            self._update_tab_title(doc)
        else:
            self._new_tab(path, data, encoding)
        self._update_title()
        self.status.set_text(f"打开 {path}")

    def save_file(self):
        doc = self.get_current_doc()
        if not doc:
            return
        if doc.path:
            self._save_to(doc, doc.path)
        else:
            self._save_as_doc(doc)

    def save_as(self):
        doc = self.get_current_doc()
        if doc:
            self._save_as_doc(doc)

    def print_doc(self):
        doc = self.get_current_doc()
        if not doc:
            return
        data = doc.buffer.get_text(
            doc.buffer.get_start_iter(), doc.buffer.get_end_iter(), False)
        self.status.set_text("正在发送到打印队列…")

        def worker():
            try:
                subprocess.run(
                    ["lp"],
                    input=data.encode("utf-8"),
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
                GLib.idle_add(self._print_done, True, None)
            except FileNotFoundError:
                GLib.idle_add(self._print_done, False,
                              "系统里找不到 lp 命令（需要 CUPS）。")
            except subprocess.TimeoutExpired:
                GLib.idle_add(self._print_done, False, "打印超时。")
            except subprocess.CalledProcessError as ex:
                err = ex.stderr.decode("utf-8", "replace") if ex.stderr else str(ex)
                GLib.idle_add(self._print_done, False, f"lp 返回错误：{err}")
            except Exception as ex:
                GLib.idle_add(self._print_done, False, str(ex))

        threading.Thread(target=worker, daemon=True).start()

    def _print_done(self, ok, msg):
        try:
            if ok:
                self.status.set_text("已发送到打印队列")
            else:
                self._show_error("打印失败", msg)
        except Exception:
            pass
        return False

    def _default_ext(self, doc):
        if not HAS_SOURCE:
            return ".txt"
        try:
            lang = doc.buffer.get_language()
        except Exception:
            return ".txt"
        if lang is None:
            return ".txt"
        ext = LANG_EXT.get(lang.get_id())
        if ext:
            return ext
        try:
            globs = lang.get_globs() or []
        except Exception:
            globs = []
        if globs:
            g = globs[0]
            if g.startswith("*"):
                return g[1:]
        return ".txt"

    def _make_save_filters(self, doc):
        store = Gio.ListStore.new(Gtk.FileFilter)
        ext = self._default_ext(doc)
        default = None
        if ext != ".txt":
            f1 = Gtk.FileFilter()
            f1.set_name(f"当前语言 (*{ext})")
            f1.add_pattern("*" + ext)
            store.append(f1)
            default = f1
        f2 = Gtk.FileFilter()
        f2.set_name("纯文本 (*.txt)")
        f2.add_pattern("*.txt")
        store.append(f2)
        f3 = Gtk.FileFilter()
        f3.set_name("所有文件")
        f3.add_pattern("*")
        store.append(f3)
        return store, default or f2

    def _save_as_doc(self, doc, on_success=None, on_cancel=None):
        if doc is None:
            return
        if doc.path:
            base = os.path.splitext(os.path.basename(doc.path))[0]
        else:
            base = doc.display_name or "未命名"
        base = os.path.splitext(base)[0]
        ext = self._default_ext(doc)
        default_name = base + ext

        if hasattr(Gtk, "FileDialog"):
            self._save_as_filedialog(doc, default_name, on_success, on_cancel)
        else:
            self._save_as_choosernative(doc, default_name, on_success, on_cancel)

    def _save_as_filedialog(self, doc, default_name, on_success, on_cancel):
        dialog = Gtk.FileDialog()
        dialog.set_title("另存为")
        dialog.set_initial_name(default_name)
        try:
            store, default_filter = self._make_save_filters(doc)
            dialog.set_filters(store)
            dialog.set_default_filter(default_filter)
        except Exception:
            pass

        def on_done(d, result):
            path = None
            try:
                file = d.save_finish(result)
                if file:
                    path = file.get_path()
            except Exception:
                pass
            if path:
                if self._save_to(doc, path):
                    if on_success:
                        on_success()
                elif on_cancel:
                    on_cancel()
            else:
                if on_cancel:
                    on_cancel()

        dialog.save(self, None, on_done)

    def _save_as_choosernative(self, doc, default_name, on_success, on_cancel):
        dialog = Gtk.FileChooserNative.new(
            "另存为", self, Gtk.FileChooserAction.SAVE, "保存", "取消")
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name(default_name)
        try:
            store, default_filter = self._make_save_filters(doc)
            for i in range(store.get_n_items()):
                dialog.add_filter(store.get_item(i))
            dialog.set_filter(default_filter)
        except Exception:
            pass

        def resp(d, r):
            path = None
            try:
                if r == Gtk.ResponseType.ACCEPT:
                    file = d.get_file()
                    if file:
                        path = file.get_path()
            finally:
                try:
                    d.destroy()
                except Exception:
                    pass
            if path:
                if self._save_to(doc, path):
                    if on_success:
                        on_success()
                elif on_cancel:
                    on_cancel()
            else:
                if on_cancel:
                    on_cancel()

        dialog.connect("response", resp)
        dialog.show()

    def _save_to(self, doc, path):
        data = doc.buffer.get_text(
            doc.buffer.get_start_iter(), doc.buffer.get_end_iter(), False)
        try:
            directory = os.path.dirname(os.path.abspath(path)) or "."
            fd, tmp = tempfile.mkstemp(prefix=".foxnote-", dir=directory, text=True)
            try:
                with os.fdopen(fd, "w", encoding=doc.encoding) as f:
                    f.write(data)
                if os.path.exists(path):
                    try:
                        os.chmod(tmp, os.stat(path).st_mode)
                    except OSError:
                        pass
                else:
                    try:
                        os.chmod(tmp, 0o644)
                    except OSError:
                        pass
                os.replace(tmp, path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception as ex:
            self._show_error("存不了", str(ex))
            return False

        doc.path = path
        doc.display_name = None
        doc.buffer.set_modified(False)
        doc.update_language_for_path(path)
        doc.apply_style_scheme(self.dark)
        self._update_tab_title(doc)
        self._update_title()
        self.status.set_text(f"已保存到 {path}")
        return True

    def _on_close_request(self, window):
        if self._pending_close:
            return True
        unsaved = [d for d in self.docs if d.buffer.get_modified()]
        if not unsaved:
            self._save_session()
            for d in self.docs:
                d.cleanup()
            return False
        self._pending_close = unsaved[:]
        self._ask_next_close()
        return True

    def _ask_next_close(self):
        if not self._pending_close:
            self._save_session()
            for d in self.docs:
                d.cleanup()
            self.destroy()
            return
        doc = self._pending_close[0]

        def done():
            if self._pending_close:
                self._pending_close.pop(0)
            self._ask_next_close()

        def cancel():
            self._pending_close.clear()

        self._ask_save_discard_cancel(
            doc,
            on_discard=done,
            on_saved=done,
            on_cancel=cancel,
        )

    def show_find(self):
        self.find_revealer.set_reveal_child(True)
        self.row_replace.set_visible(False)
        self._prepare_find()

    def show_replace(self):
        self.find_revealer.set_reveal_child(True)
        self.row_replace.set_visible(True)
        self._prepare_find()
        self.replace_entry.grab_focus()

    def _prepare_find(self):
        if not self.find_entry.get_text():
            doc = self.get_current_doc()
            if doc:
                if doc.buffer.get_has_selection():
                    s, e = _selection(doc.buffer)
                    text = doc.buffer.get_text(s, e, False)
                    if text and "\n" not in text:
                        self.find_entry.set_text(text)
        self.find_entry.grab_focus()
        self.find_entry.select_region(0, -1)

    def hide_find(self):
        self.find_revealer.set_reveal_child(False)
        doc = self.get_current_doc()
        if doc:
            doc.view.grab_focus()

    def find_next(self):
        self._search(False)

    def find_prev(self):
        self._search(True)

    def _search(self, backwards):
        doc = self.get_current_doc()
        if not doc:
            return
        if not self.find_revealer.get_reveal_child():
            self.find_revealer.set_reveal_child(True)
            self._prepare_find()
        term = self.find_entry.get_text()
        if not term:
            return
        buffer = doc.buffer
        flags = Gtk.TextSearchFlags(0)
        if not self.case_check.get_active():
            flags |= Gtk.TextSearchFlags.CASE_INSENSITIVE

        result = None
        if buffer.get_has_selection():
            s, e = _selection(buffer)
            if backwards:
                result = s.backward_search(term, flags, buffer.get_start_iter())
                if not result:
                    result = buffer.get_end_iter().backward_search(
                        term, flags, buffer.get_start_iter())
            else:
                result = e.forward_search(term, flags, buffer.get_end_iter())
                if not result:
                    result = buffer.get_start_iter().forward_search(
                        term, flags, buffer.get_end_iter())
        else:
            cursor = buffer.get_iter_at_mark(buffer.get_insert())
            if backwards:
                result = cursor.backward_search(term, flags, buffer.get_start_iter())
                if not result:
                    result = buffer.get_end_iter().backward_search(
                        term, flags, buffer.get_start_iter())
            else:
                result = cursor.forward_search(term, flags, buffer.get_end_iter())
                if not result:
                    result = buffer.get_start_iter().forward_search(
                        term, flags, buffer.get_end_iter())

        if not result:
            self.status.set_text(f"没找到 {term}")
            return

        m_start, m_end = result
        buffer.select_range(m_start, m_end)
        doc.view.scroll_to_iter(m_start, 0.0, False, 0.0, 0.0)

    def replace_one(self):
        doc = self.get_current_doc()
        if not doc:
            return
        term = self.find_entry.get_text()
        if not term:
            return
        buffer = doc.buffer
        repl = self.replace_entry.get_text()

        if buffer.get_has_selection():
            s, e = _selection(buffer)
            sel = buffer.get_text(s, e, False)
            if self.case_check.get_active():
                matched = (sel == term)
            else:
                matched = (sel.lower() == term.lower())
            if matched:
                offset = s.get_offset()
                buffer.begin_user_action()
                buffer.delete(s, e)
                new_iter = buffer.get_iter_at_offset(offset)
                buffer.insert(new_iter, repl)
                buffer.end_user_action()
                self.find_next()
                return
        self.find_next()

    def replace_all(self):
        doc = self.get_current_doc()
        if not doc:
            return
        term = self.find_entry.get_text()
        if not term:
            return
        repl = self.replace_entry.get_text()
        buffer = doc.buffer
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        text = buffer.get_text(start, end, False)
        flags = re.IGNORECASE if not self.case_check.get_active() else 0
        pattern = re.compile(re.escape(term), flags)
        new_text, count = pattern.subn(lambda m: repl, text)
        if count > 0:
            offset = start.get_offset()
            buffer.begin_user_action()
            buffer.delete(start, end)
            new_iter = buffer.get_iter_at_offset(offset)
            buffer.insert(new_iter, new_text)
            buffer.end_user_action()
            self.status.set_text(f"替换了 {count} 处")
        else:
            self.status.set_text("未找到匹配项")

    def _show_error(self, title, msg):
        dlg = Gtk.Window(transient_for=self, modal=True)
        dlg.set_title(title)
        dlg.set_default_size(350, -1)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)
        dlg.set_child(box)
        label = Gtk.Label()
        label.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        label.set_xalign(0)
        box.append(label)
        label2 = Gtk.Label(label=msg)
        label2.set_xalign(0)
        label2.set_wrap(True)
        box.append(label2)
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        btn_box.set_halign(Gtk.Align.END)
        box.append(btn_box)
        close_btn = Gtk.Button(label="关闭")
        close_btn.add_css_class("suggested-action")
        close_btn.connect("clicked", lambda _b: dlg.destroy())
        btn_box.append(close_btn)
        dlg.connect("close-request", lambda w: (w.destroy(), True))
        dlg.present()


# ---------------------------------------------------------------------------
# 应用
# ---------------------------------------------------------------------------
class FoxNoteApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_OPEN)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self._setup_actions()
        self._setup_accels()

    def _setup_actions(self):
        def bind(name, fn):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", lambda a, p: fn(self.props.active_window))
            self.add_action(act)

        bind("new", lambda w: w.new_file() if w else None)
        bind("new-window", lambda w: w.new_window() if w else None)
        bind("open", lambda w: w.open_file() if w else None)
        bind("save", lambda w: w.save_file() if w else None)
        bind("save-as", lambda w: w.save_as() if w else None)
        bind("print", lambda w: w.print_doc() if w else None)
        bind("toggle-wrap", lambda w: w.toggle_wrap() if w else None)
        bind("close-tab", lambda w: w.close_tab() if w else None)
        bind("rename-tab", lambda w: w.prompt_rename() if w else None)
        bind("quit", lambda w: self.quit())
        bind("undo", lambda w: w.undo() if w else None)
        bind("redo", lambda w: w.redo() if w else None)
        bind("cut", lambda w: w.cut() if w else None)
        bind("copy", lambda w: w.copy() if w else None)
        bind("paste", lambda w: w.paste() if w else None)
        bind("select-all", lambda w: w.select_all() if w else None)
        bind("show-find", lambda w: w.show_find() if w else None)
        bind("show-replace", lambda w: w.show_replace() if w else None)
        bind("find-next", lambda w: w.find_next() if w else None)
        bind("find-prev", lambda w: w.find_prev() if w else None)

        sidebar_act = Gio.SimpleAction.new_stateful(
            "toggle-sidebar", None, GLib.Variant.new_boolean(True)
        )
        sidebar_act.connect("activate", self._on_toggle_sidebar)
        self.add_action(sidebar_act)

        dark = Gio.SimpleAction.new_stateful(
            "toggle-dark", None, GLib.Variant.new_boolean(False)
        )
        dark.connect("activate", self._on_toggle_dark)
        self.add_action(dark)

        # FIX: set-lang 改成 stateful action，菜单可显示当前选中语言
        lang_act = Gio.SimpleAction.new_stateful(
            "set-lang", GLib.VariantType.new("s"),
            GLib.Variant.new_string("none")
        )
        lang_act.connect("activate", self._on_set_lang)
        self.add_action(lang_act)

    def _on_toggle_sidebar(self, action, param):
        win = self.props.active_window
        if win:
            win.toggle_sidebar()
            action.set_state(
                GLib.Variant.new_boolean(win.sidebar_revealer.get_reveal_child())
            )

    def _on_toggle_dark(self, action, param):
        win = self.props.active_window
        if win:
            win.toggle_dark()
            action.set_state(GLib.Variant.new_boolean(win.dark))

    def _on_set_lang(self, action, param):
        win = self.props.active_window
        if win:
            win.set_language(param.get_string())

    def _setup_accels(self):
        self.set_accels_for_action("app.new", ["<Ctrl>N"])
        self.set_accels_for_action("app.new-window", ["<Ctrl><Shift>N"])
        self.set_accels_for_action("app.open", ["<Ctrl>O"])
        self.set_accels_for_action("app.save", ["<Ctrl>S"])
        self.set_accels_for_action("app.save-as", ["<Ctrl><Shift>S"])
        self.set_accels_for_action("app.print", ["<Ctrl>P"])
        self.set_accels_for_action("app.rename-tab", ["F2"])
        self.set_accels_for_action("app.close-tab", ["<Ctrl>W"])
        self.set_accels_for_action("app.quit", ["<Ctrl>Q"])
        self.set_accels_for_action("app.toggle-dark", ["<Ctrl>D"])
        self.set_accels_for_action("app.toggle-sidebar", ["F9"])
        self.set_accels_for_action("app.show-find", ["<Ctrl>F"])
        self.set_accels_for_action("app.show-replace", ["<Ctrl>H"])
        self.set_accels_for_action("app.toggle-wrap", ["<Ctrl><Alt>W"])
        self.set_accels_for_action("app.find-next", ["F3"])
        self.set_accels_for_action("app.find-prev", ["<Shift>F3"])

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = FoxNoteWindow(application=self)
        win.present()

    def do_open(self, files, n_files, hint):
        win = self.props.active_window
        if not win:
            win = FoxNoteWindow(application=self)
        win.present()
        for f in files:
            path = f.get_path()
            if not path:
                continue
            try:
                data, encoding = _read_text(path)
            except OSError as ex:
                win._show_error("打不开", str(ex))
                continue
            win._open_path(path, data, encoding)


def main():
    return FoxNoteApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

