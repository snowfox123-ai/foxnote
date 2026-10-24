#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import locale
import tempfile
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio, Gdk, GLib

try:
    gi.require_version("GtkSource", "5")
    from gi.repository import GtkSource
    HAS_SOURCE = True
except (ValueError, ImportError):
    HAS_SOURCE = False

APP_NAME = "FoxNote"
APP_ID = "org.foxnote.FoxNote"


def _read_text(path):
    """依次尝试 utf-8-sig / 系统编码 / 容错 utf-8。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except UnicodeDecodeError:
        pass
    try:
        enc = locale.getpreferredencoding(False)
        with open(path, "r", encoding=enc) as f:
            return f.read()
    except (UnicodeDecodeError, LookupError):
        pass
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 单个标签页 = 一个 Document
# ---------------------------------------------------------------------------
class Document:
    def __init__(self, window, path=None, content=""):
        self.window = window
        self.path = path
        self.tab_label = None

        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_hexpand(True)
        self.scrolled.set_vexpand(True)

        if HAS_SOURCE:
            self.buffer = GtkSource.Buffer()
            self.buffer.set_enable_undo(True)
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

        self.view.set_wrap_mode(Gtk.WrapMode.WORD)
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
        # 有路径就猜，猜不到就是纯文本；新建文件也默认纯文本
        lang = lm.guess_language(path) if path else None
        self.buffer.set_language(lang)

    def apply_style_scheme(self, dark):
        if not HAS_SOURCE:
            return
        mgr = GtkSource.StyleSchemeManager.get_default()
        candidates = ("Adwaita-dark", "oblivion", "solarized-dark") if dark else ("Adwaita", "classic", "solarized-light")
        for sid in candidates:
            scheme = mgr.get_scheme(sid)
            if scheme is not None:
                self.buffer.set_style_scheme(scheme)
                return

    def _on_modified_changed(self, buffer):
        # 无论变成已修改还是恢复为未修改，都要刷新
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
        gesture.connect("pressed", self._on_right_click)
        self.view.add_controller(gesture)

    def _on_right_click(self, gesture, n_press, x, y):
        bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        ok, over_iter = self.view.get_iter_at_location(bx, by)
        if ok:
            has_sel, s, e = self.buffer.get_selection_bounds()
            if (not has_sel or over_iter.get_offset() < s.get_offset()
                    or over_iter.get_offset() >= e.get_offset()):
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
        try:
            if self.buffer.get_can_undo():
                self.buffer.undo()
                self.view.grab_focus()
        except Exception:
            pass

    def _redo(self):
        try:
            if self.buffer.get_can_redo():
                self.buffer.redo()
                self.view.grab_focus()
        except Exception:
            pass

    def _select_all(self):
        self.buffer.select_range(self.buffer.get_start_iter(), self.buffer.get_end_iter())
        self.view.grab_focus()


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class FoxNoteWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application)
        self.application = application
        self.docs = []
        self.dark = False
        self._pending_close = []

        self.set_default_size(800, 600)
        self.set_title(APP_NAME)

        self._build_ui()
        self._apply_theme()
        self.connect("close-request", self._on_close_request)

        self.new_file()
        self._update_title()

    def _build_ui(self):
        header = Gtk.HeaderBar()
        self.set_titlebar(header)

        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_tooltip_text("菜单")
        menu_btn.set_menu_model(self._build_menu())
        header.pack_start(menu_btn)

        for icon, tip, action in (
            ("document-new-symbolic",  "新建 (Ctrl+N)", "app.new"),
            ("document-open-symbolic", "打开 (Ctrl+O)", "app.open"),
            ("document-save-symbolic", "保存 (Ctrl+S)", "app.save"),
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

        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_vexpand(True)
        self.notebook.connect("switch-page", self._on_switch_page)
        vbox.append(self.notebook)

        self.find_revealer = Gtk.Revealer()
        self.find_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.find_revealer.set_reveal_child(False)
        self._build_find_bar()
        vbox.append(self.find_revealer)

        self.status = Gtk.Label(label="就绪")
        if not HAS_SOURCE:
            self.status.set_text("提示：未检测到 GtkSourceView，语法高亮与行号不可用。")
        self.status.set_xalign(0)
        self.status.set_margin_start(8)
        self.status.set_margin_end(8)
        self.status.set_margin_top(4)
        self.status.set_margin_bottom(4)
        vbox.append(self.status)

    def _build_menu(self):
        menu = Gio.Menu()

        sec = Gio.Menu()
        sec.append("新建", "app.new")
        sec.append("打开…", "app.open")
        sec.append("保存", "app.save")
        sec.append("另存为…", "app.save-as")
        menu.append_section(None, sec)

        sec = Gio.Menu()
        sec.append("关闭标签页", "app.close-tab")
        sec.append("退出", "app.quit")
        menu.append_section(None, sec)

        sec = Gio.Menu()
        sec.append("撤销", "app.undo")
        sec.append("重做", "app.redo")
        menu.append_section(None, sec)

        sec = Gio.Menu()
        sec.append("剪切", "app.cut")
        sec.append("复制", "app.copy")
        sec.append("粘贴", "app.paste")
        sec.append("全选", "app.select-all")
        menu.append_section(None, sec)

        sec = Gio.Menu()
        sec.append("查找…", "app.show-find")
        sec.append("替换…", "app.show-replace")
        sec.append("查找下一个", "app.find-next")
        sec.append("查找上一个", "app.find-prev")
        menu.append_section(None, sec)

        if HAS_SOURCE:
            sec = Gio.Menu()
            lang_menu = Gio.Menu()
            for name, lang_id in (("Python", "python"), ("HTML", "html"),
                                  ("JavaScript", "javascript"), ("CSS", "css"),
                                  ("Markdown", "markdown"), ("纯文本", "none")):
                item = Gio.MenuItem.new(name, None)
                item.set_action_and_target_value("app.set-lang", GLib.Variant.new_string(lang_id))
                lang_menu.append_item(item)
            sec.append_submenu("语法高亮", lang_menu)
            menu.append_section(None, sec)

        sec = Gio.Menu()
        sec.append("深色模式", "app.toggle-dark")
        menu.append_section(None, sec)

        return menu

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

        for label, cb in (("上一个", self.find_prev), ("下一个", self.find_next), ("×", self.hide_find)):
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

        for label, cb in (("替换", self.replace_one), ("全部替换", self.replace_all)):
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
                settings.set_property("gtk-interface-color-scheme",
                                      "prefer-dark" if self.dark else "default")
            except Exception:
                pass
        for doc in self.docs:
            doc.apply_style_scheme(self.dark)

    def toggle_dark(self):
        self.dark = not self.dark
        self._apply_theme()

    def _tab_title(self, doc):
        name = os.path.basename(doc.path) if doc.path else "未命名"
        mark = "*" if doc.buffer.get_modified() else ""
        return f"{mark}{name}"

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
        self.status.set_text("就绪")

    def new_file(self):
        self._new_tab()
        self.status.set_text("新建文件")

    def _new_tab(self, path=None, content=""):
        doc = Document(self, path, content)
        self.docs.append(doc)

        tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        doc.tab_label = Gtk.Label(label=self._tab_title(doc))
        tab_box.append(doc.tab_label)

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

    def _update_title(self):
        doc = self.get_current_doc()
        if doc:
            name = os.path.basename(doc.path) if doc.path else "未命名"
            mark = "*" if doc.buffer.get_modified() else ""
            self.set_title(f"{mark}{name} - {APP_NAME}")
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
        """统一的“保存 / 丢弃 / 取消”对话框。"""
        dlg = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=f"{self._tab_title(doc)} 还没保存",
        )
        dlg.set_secondary_text("要保存改动吗？")
        dlg.add_button("取消", Gtk.ResponseType.CANCEL)
        dlg.add_button("丢弃", Gtk.ResponseType.NO)
        dlg.add_button("保存", Gtk.ResponseType.YES)
        dlg.set_default_response(Gtk.ResponseType.YES)

        def resp(d, r):
            d.destroy()
            if r == Gtk.ResponseType.NO:
                on_discard()
            elif r == Gtk.ResponseType.YES:
                self._save_doc(doc, on_saved or on_discard, on_cancel)
            elif on_cancel:
                on_cancel()

        dlg.connect("response", resp)
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
            doc.buffer.select_range(doc.buffer.get_start_iter(), doc.buffer.get_end_iter())
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
            if lang:
                doc.buffer.set_language(lang)
                self.status.set_text(f"语法：{lang.get_name()}")

    def open_file(self):
        dialog = Gtk.FileChooserNative.new("打开文件", self,
                                           Gtk.FileChooserAction.OPEN, "打开", "取消")
        filt = Gtk.FileFilter()
        filt.set_name("文本 / 代码")
        for p in ("*.txt", "*.md", "*.py", "*.html", "*.htm", "*.js",
                  "*.css", "*.json", "*"):
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
                    data = _read_text(path)
                except OSError as ex:
                    self._show_error("打不开", str(ex))
                    return
                self._open_path(path, data)
        finally:
            try:
                dialog.destroy()
            except Exception:
                pass

    def _open_path(self, path, data):
        doc = self.get_current_doc()
        empty = (
            doc and doc.path is None and not doc.buffer.get_modified()
            and not doc.buffer.get_text(doc.buffer.get_start_iter(),
                                        doc.buffer.get_end_iter(), False).strip()
        )
        if empty:
            doc.buffer.set_text(data)
            doc.buffer.set_modified(False)
            doc.path = path
            doc.update_language_for_path(path)
            doc.apply_style_scheme(self.dark)
            self._update_tab_title(doc)
        else:
            self._new_tab(path, data)
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

    def _save_as_doc(self, doc, on_success=None, on_cancel=None):
        if doc is None:
            return
        dialog = Gtk.FileChooserNative.new("另存为", self,
                                           Gtk.FileChooserAction.SAVE, "保存", "取消")
        dialog.set_do_overwrite_confirmation(True)
        name = os.path.basename(doc.path) if doc.path else "未命名.txt"
        dialog.set_current_name(name)

        def resp(d, r):
            saved = False
            try:
                if r == Gtk.ResponseType.ACCEPT:
                    file = d.get_file()
                    if file:
                        path = file.get_path()
                        if path:
                            saved = self._save_to(doc, path)
                        else:
                            self._show_error("存不了", "目前只支持保存到本地文件")
            finally:
                try:
                    d.destroy()
                except Exception:
                    pass
            if saved:
                if on_success:
                    on_success()
            elif on_cancel:
                on_cancel()

        dialog.connect("response", resp)
        dialog.show()

    def _save_to(self, doc, path):
        data = doc.buffer.get_text(doc.buffer.get_start_iter(),
                                   doc.buffer.get_end_iter(), False)
        try:
            directory = os.path.dirname(os.path.abspath(path)) or "."
            fd, tmp = tempfile.mkstemp(prefix=".foxnote-", dir=directory, text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(data)
                if os.path.exists(path):
                    try:
                        os.chmod(tmp, os.stat(path).st_mode)
                    except OSError:
                        pass
                os.replace(tmp, path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as ex:
            self._show_error("存不了", str(ex))
            return False

        doc.path = path
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
            return False
        self._pending_close = unsaved[:]
        self._ask_next_close()
        return True

    def _ask_next_close(self):
        if not self._pending_close:
            self.destroy()
            return
        doc = self._pending_close[0]

        def done():
            if self._pending_close:
                self._pending_close.pop(0)
            self._ask_next_close()

        self._ask_save_discard_cancel(
            doc,
            on_discard=done,
            on_saved=done,
            on_cancel=lambda: setattr(self, "_pending_close", []),
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
                has_sel, s, e = doc.buffer.get_selection_bounds()
                if has_sel:
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
            # 第一次按 F3 / Shift+F3 时展开查找栏，但继续用已有文本搜索
            self.find_revealer.set_reveal_child(True)
            self._prepare_find()
        term = self.find_entry.get_text()
        if not term:
            return

        buffer = doc.buffer
        flags = Gtk.TextSearchFlags(0)
        if not self.case_check.get_active():
            flags |= Gtk.TextSearchFlags.CASE_INSENSITIVE

        has_sel, s, e = buffer.get_selection_bounds()
        result = None
        if has_sel:
            if backwards:
                result = s.backward_search(term, flags, buffer.get_start_iter())
                if not result:
                    result = buffer.get_end_iter().backward_search(term, flags, buffer.get_start_iter())
            else:
                result = e.forward_search(term, flags, buffer.get_end_iter())
                if not result:
                    result = buffer.get_start_iter().forward_search(term, flags, buffer.get_end_iter())
        else:
            cursor = buffer.get_iter_at_mark(buffer.get_insert())
            if backwards:
                result = cursor.backward_search(term, flags, buffer.get_start_iter())
                if not result:
                    result = buffer.get_end_iter().backward_search(term, flags, buffer.get_start_iter())
            else:
                result = cursor.forward_search(term, flags, buffer.get_end_iter())
                if not result:
                    result = buffer.get_start_iter().forward_search(term, flags, buffer.get_end_iter())

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
        has_sel, s, e = buffer.get_selection_bounds()
        if has_sel:
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

    def replace_all(self):
        doc = self.get_current_doc()
        if not doc:
            return
        term = self.find_entry.get_text()
        if not term:
            return
        repl = self.replace_entry.get_text()
        buffer = doc.buffer

        flags = Gtk.TextSearchFlags(0)
        if not self.case_check.get_active():
            flags |= Gtk.TextSearchFlags.CASE_INSENSITIVE

        count = 0
        buffer.begin_user_action()
        start = buffer.get_start_iter()
        while True:
            result = start.forward_search(term, flags, buffer.get_end_iter())
            if not result:
                break
            m_start, m_end = result
            offset = m_start.get_offset()
            buffer.delete(m_start, m_end)
            new_iter = buffer.get_iter_at_offset(offset)
            buffer.insert(new_iter, repl)
            start = buffer.get_iter_at_offset(offset + len(repl))
            count += 1
        buffer.end_user_action()
        self.status.set_text(f"替换了 {count} 处")

    def _show_error(self, title, msg):
        dlg = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text=title,
        )
        dlg.set_secondary_text(msg)
        dlg.connect("response", lambda d, r: d.destroy())
        dlg.present()


# ---------------------------------------------------------------------------
# 应用
# ---------------------------------------------------------------------------
class FoxNoteApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self._setup_actions()
        self._setup_accels()

    def _setup_actions(self):
        def bind(name, fn):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", lambda a, p: fn(self.props.active_window))
            self.add_action(act)

        bind("new",         lambda w: w.new_file()      if w else None)
        bind("open",        lambda w: w.open_file()     if w else None)
        bind("save",        lambda w: w.save_file()     if w else None)
        bind("save-as",     lambda w: w.save_as()       if w else None)
        bind("close-tab",   lambda w: w.close_tab()     if w else None)
        bind("quit",        lambda w: self.quit())
        bind("undo",        lambda w: w.undo()          if w else None)
        bind("redo",        lambda w: w.redo()          if w else None)
        bind("cut",         lambda w: w.cut()           if w else None)
        bind("copy",        lambda w: w.copy()          if w else None)
        bind("paste",       lambda w: w.paste()         if w else None)
        bind("select-all",  lambda w: w.select_all()    if w else None)
        bind("show-find",   lambda w: w.show_find()     if w else None)
        bind("show-replace",lambda w: w.show_replace()  if w else None)
        bind("find-next",   lambda w: w.find_next()     if w else None)
        bind("find-prev",   lambda w: w.find_prev()     if w else None)

        # 深色模式改为 stateful action，ToggleButton / 菜单 / 快捷键 三处同步
        dark = Gio.SimpleAction.new_stateful(
            "toggle-dark", None, GLib.Variant.new_boolean(False)
        )
        dark.connect("activate", self._on_toggle_dark)
        self.add_action(dark)

        act = Gio.SimpleAction.new("set-lang", GLib.VariantType.new("s"))
        act.connect("activate", lambda a, p: (
            self.props.active_window.set_language(p.get_string())
            if self.props.active_window else None
        ))
        self.add_action(act)

    def _on_toggle_dark(self, action, param):
        win = self.props.active_window
        if win:
            win.toggle_dark()
            action.set_state(GLib.Variant.new_boolean(win.dark))

    def _setup_accels(self):
        self.set_accels_for_action("app.new",          ["<Ctrl>N"])
        self.set_accels_for_action("app.open",         ["<Ctrl>O"])
        self.set_accels_for_action("app.save",         ["<Ctrl>S"])
        self.set_accels_for_action("app.save-as",      ["<Ctrl><Shift>S"])
        self.set_accels_for_action("app.close-tab",    ["<Ctrl>W"])
        self.set_accels_for_action("app.quit",         ["<Ctrl>Q"])
        self.set_accels_for_action("app.toggle-dark",  ["<Ctrl>D"])
        self.set_accels_for_action("app.show-find",    ["<Ctrl>F"])
        self.set_accels_for_action("app.show-replace", ["<Ctrl>H"])
        self.set_accels_for_action("app.find-next",    ["F3"])
        self.set_accels_for_action("app.find-prev",    ["<Shift>F3"])

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = FoxNoteWindow(application=self)
        win.present()


def main():
    return FoxNoteApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
