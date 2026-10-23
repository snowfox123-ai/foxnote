#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "FoxNote"
ICONS = ("foxnote.png", "icon.png")


class Document:
    """一个标签页对应一个 Document，持有自己的 Text / 路径 / 修改状态。"""

    def __init__(self, app, notebook, path=None, content=""):
        self.app = app
        self.path = path
        self.modified = False

        self.frame = tk.Frame(notebook)
        self.text = tk.Text(self.frame, undo=True, wrap="word", font=("Monospace", 12))
        self.text.pack(side="left", fill="both", expand=True)

        sb = tk.Scrollbar(self.frame, command=self.text.yview)
        sb.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=sb.set)

        if content:
            self.text.insert("1.0", content)
        self.text.edit_reset()          # 清掉插入内容产生的 undo 栈
        self.text.edit_modified(False)  # 重置修改标记
        self.text.mark_set("insert", "1.0")

        app._bind_text(self.text)


class FoxNote:
    def __init__(self, root):
        self.root = root
        self.dark = False
        self.docs = {}          # key = str(frame)，value = Document

        root.geometry("800x600")
        self._load_icon()
        self._build_menu()
        self._build_editor()
        self._build_find_bar()
        self._apply_theme()
        self._update_title()

        root.protocol("WM_DELETE_WINDOW", self.on_close)

        # 全局快捷键（文件、视图、查找）
        root.bind_all("<Control-n>", self.new_file)
        root.bind_all("<Control-t>", self.new_file)
        root.bind_all("<Control-o>", self.open_file)
        root.bind_all("<Control-s>", self.save_file)
        root.bind_all("<Control-Shift-S>", self.save_as)
        root.bind_all("<Control-w>", self.close_tab)
        root.bind_all("<Control-d>", self.toggle_dark)
        root.bind_all("<Control-f>", self.show_find)
        root.bind_all("<Control-h>", self.show_replace)
        root.bind_all("<F3>", self.find_next)
        root.bind_all("<Shift-F3>", self.find_prev)

    @property
    def current_doc(self):
        if not hasattr(self, "notebook"):
            return None
        sel = self.notebook.select()
        if not sel:
            return None
        doc = self.docs.get(sel)
        if doc:
            return doc
        for d in self.docs.values():
            if str(d.frame) == sel:
                return d
        return None

    @property
    def text(self):
        doc = self.current_doc
        return doc.text if doc else None

    @property
    def current_file(self):
        doc = self.current_doc
        return doc.path if doc else None

    @current_file.setter
    def current_file(self, value):
        doc = self.current_doc
        if doc:
            doc.path = value

    @property
    def modified(self):
        doc = self.current_doc
        return doc.modified if doc else False

    @modified.setter
    def modified(self, value):
        doc = self.current_doc
        if doc:
            doc.modified = value

    def _doc_of(self, widget):
        for doc in self.docs.values():
            if doc.text is widget:
                return doc
        return None

    # ---- 图标 ----
    def _load_icon(self):
        for name in ICONS:
            try:
                self.icon = tk.PhotoImage(file=name)
                self.root.iconphoto(True, self.icon)
                return
            except tk.TclError:
                pass

    # ---- 菜单 ----
    def _build_menu(self):
        bar = tk.Menu(self.root)

        m = tk.Menu(bar, tearoff=0)
        m.add_command(label="新建", accelerator="Ctrl+N", command=self.new_file)
        m.add_command(label="打开...", accelerator="Ctrl+O", command=self.open_file)
        m.add_command(label="保存", accelerator="Ctrl+S", command=self.save_file)
        m.add_command(label="另存为...", accelerator="Ctrl+Shift+S", command=self.save_as)
        m.add_separator()
        m.add_command(label="关闭标签页", accelerator="Ctrl+W", command=self.close_tab)
        m.add_command(label="退出", command=self.on_close)
        bar.add_cascade(label="文件", menu=m)

        m = tk.Menu(bar, tearoff=0)
        m.add_command(label="撤销", accelerator="Ctrl+Z", command=self.undo)
        m.add_command(label="重做", accelerator="Ctrl+Y", command=self.redo)
        m.add_separator()
        m.add_command(label="剪切", accelerator="Ctrl+X", command=self.cut)
        m.add_command(label="复制", accelerator="Ctrl+C", command=self.copy)
        m.add_command(label="粘贴", accelerator="Ctrl+V", command=self.paste)
        m.add_command(label="全选", accelerator="Ctrl+A", command=self.select_all)
        m.add_separator()
        m.add_command(label="查找...", accelerator="Ctrl+F", command=self.show_find)
        m.add_command(label="替换...", accelerator="Ctrl+H", command=self.show_replace)
        m.add_command(label="查找下一个", accelerator="F3", command=self.find_next)
        m.add_command(label="查找上一个", accelerator="Shift+F3", command=self.find_prev)
        bar.add_cascade(label="编辑", menu=m)

        m = tk.Menu(bar, tearoff=0)
        m.add_command(label="深色模式", accelerator="Ctrl+D", command=self.toggle_dark)
        bar.add_cascade(label="视图", menu=m)

        self.root.config(menu=bar)

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="撤销", command=self.undo)
        self.context_menu.add_command(label="重做", command=self.redo)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="剪切", command=self.cut)
        self.context_menu.add_command(label="复制", command=self.copy)
        self.context_menu.add_command(label="粘贴", command=self.paste)
        self.context_menu.add_command(label="全选", command=self.select_all)

    # ---- 编辑操作 ----
    def undo(self, e=None):
        try:
            self.text.edit_undo()
        except tk.TclError:
            self.status.configure(text="没有可撤销的操作")
        self.text.focus_set()
        return "break"

    def redo(self, e=None):
        try:
            self.text.edit_redo()
        except tk.TclError:
            self.status.configure(text="没有可重做的操作")
        self.text.focus_set()
        return "break"

    def cut(self, e=None):
        self.text.focus_set()
        try:
            self.text.event_generate("<<Cut>>")
        except tk.TclError:
            pass
        return "break"

    def copy(self, e=None):
        self.text.focus_set()
        try:
            self.text.event_generate("<<Copy>>")
        except tk.TclError:
            pass
        return "break"

    def paste(self, e=None):
        self.text.focus_set()
        try:
            self.text.event_generate("<<Paste>>")
        except tk.TclError:
            pass
        return "break"

    def select_all(self, e=None):
        self.text.tag_add("sel", "1.0", "end-1c")
        self.text.mark_set("insert", "1.0")
        self.text.see("insert")
        self.text.focus_set()
        return "break"

    def _show_context_menu(self, event):
        clicked = self.text.index(f"@{event.x},{event.y}")
        try:
            sel_start = self.text.index("sel.first")
            sel_end = self.text.index("sel.last")
            inside_selection = (
                self.text.compare(clicked, ">=", sel_start)
                and self.text.compare(clicked, "<", sel_end)
            )
        except tk.TclError:
            inside_selection = False

        if not inside_selection:
            self.text.tag_remove("sel", "1.0", "end")
            self.text.mark_set("insert", clicked)

        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
        return "break"

    # ---- 主体 ----
    def _build_editor(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)

        self.status = tk.Label(self.root, text="就绪", anchor="w")
        self.status.pack(side="bottom", fill="x")

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._new_tab()

    def _bind_text(self, text):
        text.bind("<<Modified>>", self._on_modified)
        text.bind("<Escape>", self._on_escape)
        text.bind("<Control-a>", self.select_all)
        text.bind("<Control-A>", self.select_all)
        text.bind("<Control-z>", self.undo)
        text.bind("<Control-Z>", self.undo)
        text.bind("<Control-y>", self.redo)
        text.bind("<Control-Y>", self.redo)
        text.bind("<Control-x>", self.cut)
        text.bind("<Control-X>", self.cut)
        text.bind("<Control-c>", self.copy)
        text.bind("<Control-C>", self.copy)
        text.bind("<Control-v>", self.paste)
        text.bind("<Control-V>", self.paste)
        text.bind("<Button-3>", self._show_context_menu)

    # ---- 标签页管理 ----
    def _tab_title(self, doc):
        name = os.path.basename(doc.path) if doc.path else "未命名"
        return ("*" if doc.modified else "") + name

    def _update_tab_title(self, doc):
        try:
            self.notebook.tab(doc.frame, text=self._tab_title(doc))
        except tk.TclError:
            pass

    def _new_tab(self, path=None, content=""):
        doc = Document(self, self.notebook, path, content)
        key = str(doc.frame)
        self.docs[key] = doc
        self.notebook.add(doc.frame, text=self._tab_title(doc))
        self.notebook.select(doc.frame)
        self._apply_theme_to(doc)
        self._update_title()
        return doc

    def _on_tab_changed(self, e=None):
        self._clear_tags()
        self._update_title()
        if self.current_doc:
            self.status.configure(text="就绪")

    def close_tab(self, e=None):
        doc = self.current_doc
        if not doc:
            return "break"
        if doc.modified:
            self.notebook.select(doc.frame)
            if not messagebox.askyesno(
                    "等等", f"{self._tab_title(doc)} 还没保存，确定要丢弃改动吗？"):
                return "break"
        key = str(doc.frame)
        self.notebook.forget(doc.frame)
        self.docs.pop(key, None)
        doc.frame.destroy()
        if not self.docs:
            self._new_tab()
        self._update_title()
        self.status.configure(text="已关闭标签页")
        return "break"

    def _build_find_bar(self):
        self.find_frame = tk.Frame(self.root)

        # -- 查找行 --
        self.row_find = tk.Frame(self.find_frame)
        self.row_find.pack(fill="x", pady=2)

        tk.Label(self.row_find, text="查找").pack(side="left", padx=(6, 2))
        self.find_entry = tk.Entry(self.row_find, width=24)
        self.find_entry.pack(side="left", fill="x", expand=True, padx=2)

        self.case_var = tk.BooleanVar(value=False)
        self.case_check = tk.Checkbutton(self.row_find, text="区分大小写", variable=self.case_var)
        self.case_check.pack(side="left", padx=4)

        tk.Button(self.row_find, text="上一个", command=self.find_prev).pack(side="left", padx=2)
        tk.Button(self.row_find, text="下一个", command=self.find_next).pack(side="left", padx=2)
        tk.Button(self.row_find, text="×", width=2, command=self.hide_find).pack(side="left", padx=(2, 6))

        # -- 替换行 --
        self.row_replace = tk.Frame(self.find_frame)
        self.row_replace.pack(fill="x", pady=(0, 4))

        tk.Label(self.row_replace, text="替换").pack(side="left", padx=(6, 2))
        self.replace_entry = tk.Entry(self.row_replace, width=24)
        self.replace_entry.pack(side="left", fill="x", expand=True, padx=2)

        tk.Button(self.row_replace, text="替换", command=self.replace_one).pack(side="left", padx=2)
        tk.Button(self.row_replace, text="全部替换", command=self.replace_all).pack(side="left", padx=2)

        self.find_entry.bind("<Return>", self.find_next)
        self.find_entry.bind("<Shift-Return>", self.find_prev)
        self.find_entry.bind("<Escape>", self.hide_find)
        self.find_entry.bind("<KeyRelease>", self._clear_tags)
        self.replace_entry.bind("<Return>", self.replace_one)

    # ---- 配色 ----
    def _colors(self):
        if self.dark:
            return dict(bg="#1e1e1e", fg="#d4d4d4", cursor="#ffffff",
                        select="#264f78", status_bg="#2d2d2d", bar_bg="#252526")
        return dict(bg="#ffffff", fg="#000000", cursor="#000000",
                    select="#cce8ff", status_bg="#f0f0f0", bar_bg="#f0f0f0")

    def _apply_theme(self):
        c = self._colors()
        self.status.configure(bg=c["status_bg"], fg=c["fg"])

        self.find_frame.configure(bg=c["bar_bg"])
        self.row_find.configure(bg=c["bar_bg"])
        self.row_replace.configure(bg=c["bar_bg"])
        for row in (self.row_find, self.row_replace):
            for w in row.winfo_children():
                try:
                    w.configure(bg=c["bar_bg"], fg=c["fg"])
                except tk.TclError:
                    pass

        self.find_entry.configure(bg=c["bg"], fg=c["fg"], insertbackground=c["cursor"])
        self.replace_entry.configure(bg=c["bg"], fg=c["fg"], insertbackground=c["cursor"])
        self.case_check.configure(activebackground=c["bar_bg"], activeforeground=c["fg"],
                                  selectcolor=c["bg"])

        for doc in self.docs.values():
            self._apply_theme_to(doc)

    def _apply_theme_to(self, doc):
        c = self._colors()
        doc.frame.configure(bg=c["bg"])
        doc.text.configure(bg=c["bg"], fg=c["fg"],
                           insertbackground=c["cursor"],
                           selectbackground=c["select"])
        doc.text.tag_configure("hit", background="#ffb74d", foreground="#000000")

    def toggle_dark(self, e=None):
        self.dark = not self.dark
        self._apply_theme()

    # ---- 修改标记 ----
    def _on_modified(self, e=None):
        w = e.widget if e is not None else self.text
        doc = self._doc_of(w)
        if doc is None:
            return
        if not w.edit_modified():
            return
        doc.modified = True
        w.edit_modified(False)
        w.tag_remove("hit", "1.0", "end")
        self._update_tab_title(doc)
        if doc is self.current_doc:
            self._update_title()
            self.status.configure(text="已修改")

    def _update_title(self):
        doc = self.current_doc
        name = os.path.basename(doc.path) if doc and doc.path else "未命名"
        mark = "*" if doc and doc.modified else ""
        self.root.title(f"{mark}{name} - {APP_NAME}")

    # ---- 文件 ----
    def new_file(self, e=None):
        self._new_tab()
        self.status.configure(text="新建文件")
        return "break"

    def open_file(self, e=None):
        path = filedialog.askopenfilename(
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return "break"
        try:
            with open(path, encoding="utf-8") as f:
                data = f.read()
        except OSError as ex:
            messagebox.showerror("打不开", str(ex))
            return "break"

        doc = self.current_doc
        if (doc and doc.path is None and not doc.modified
                and not doc.text.get("1.0", "end-1c").strip()):
            doc.text.delete("1.0", "end")
            doc.text.insert("1.0", data)
            doc.text.edit_reset()
            doc.text.edit_modified(False)
            doc.path = path
            doc.modified = False
            self._update_tab_title(doc)
        else:
            self._new_tab(path, data)

        self._update_title()
        self.status.configure(text=f"打开 {path}")
        return "break"

    def save_file(self, e=None):
        doc = self.current_doc
        if not doc:
            return "break"
        if doc.path:
            self._save_to(doc.path, doc)
        else:
            self.save_as()
        return "break"

    def save_as(self, e=None):
        doc = self.current_doc
        if not doc:
            return "break"
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if path:
            self._save_to(path, doc)
        return "break"

    def _save_to(self, path, doc=None):
        doc = doc or self.current_doc
        if not doc:
            return
        data = doc.text.get("1.0", "end")
        if data.endswith("\n"):
            data = data[:-1]
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)
        except OSError as ex:
            messagebox.showerror("存不了", str(ex))
            return
        doc.path = path
        doc.modified = False
        self._update_tab_title(doc)
        self._update_title()
        self.status.configure(text=f"已保存到 {path}")

    def on_close(self):
        for doc in list(self.docs.values()):
            if doc.modified:
                self.notebook.select(doc.frame)
                self.root.update_idletasks()
                if not messagebox.askyesno(
                        "等等", f"{self._tab_title(doc)} 还没保存，确定要丢弃改动吗？"):
                    return
        self.root.destroy()

    # ---- 查找与替换 ----
    def show_find(self, e=None):
        if not self.find_frame.winfo_ismapped():
            self.find_frame.pack(side="bottom", fill="x", before=self.status)

        if not hasattr(self, '_show_replace_mode'):
            self._show_replace_mode = False
        if not self._show_replace_mode:
            self.row_replace.pack_forget()

        self._prepare_find()
        return "break"

    def show_replace(self, e=None):
        if not self.find_frame.winfo_ismapped():
            self.find_frame.pack(side="bottom", fill="x", before=self.status)

        self._show_replace_mode = True
        self.row_replace.pack(fill="x", pady=(0, 4))
        self._prepare_find()
        self.replace_entry.focus_set()
        return "break"

    def _prepare_find(self):
        if not self.find_entry.get():
            try:
                sel = self.text.get("sel.first", "sel.last")
            except tk.TclError:
                sel = ""
            if sel and "\n" not in sel:
                self.find_entry.insert(0, sel)
        self.find_entry.focus_set()
        self.find_entry.select_range(0, "end")

    def hide_find(self, e=None):
        self.find_frame.pack_forget()
        self._clear_tags()
        self.text.focus_set()
        return "break"

    def _on_escape(self, e=None):
        if self.find_frame.winfo_ismapped():
            return self.hide_find()
        return None

    def _clear_tags(self, e=None):
        doc = self.current_doc
        if doc:
            doc.text.tag_remove("hit", "1.0", "end")

    def find_next(self, e=None):
        return self._search(backwards=False)

    def find_prev(self, e=None):
        return self._search(backwards=True)

    def _search(self, backwards=False):
        if not self.find_frame.winfo_ismapped():
            return self.show_find()

        term = self.find_entry.get()
        if not term:
            return "break"

        nocase = not self.case_var.get()

        if self.text.tag_ranges("hit"):
            start = self.text.index("hit.first" if backwards else "hit.last")
        else:
            start = "insert"

        if backwards:
            pos = self.text.search(term, start, stopindex="1.0", backwards=True, nocase=nocase)
            if not pos:
                pos = self.text.search(term, "end", stopindex="1.0", backwards=True, nocase=nocase)
        else:
            pos = self.text.search(term, start, stopindex="end", nocase=nocase)
            if not pos:
                pos = self.text.search(term, "1.0", stopindex="end", nocase=nocase)

        if not pos:
            self._clear_tags()
            self.status.configure(text=f"没找到 {term}")
            return "break"

        end = f"{pos}+{len(term)}c"
        self._clear_tags()
        self.text.tag_add("hit", pos, end)
        self.text.mark_set("insert", end)
        self.text.see(pos)
        return "break"

    def replace_one(self, e=None):
        if not self.text.tag_ranges("hit"):
            self.find_next()
            return "break"

        pos_start = self.text.index("hit.first")
        pos_end = self.text.index("hit.last")
        repl = self.replace_entry.get()

        self.text.delete(pos_start, pos_end)
        self.text.insert(pos_start, repl)

        self._clear_tags()
        self.find_next()
        return "break"

    def replace_all(self):
        term = self.find_entry.get()
        repl = self.replace_entry.get()
        if not term:
            return

        nocase = not self.case_var.get()
        count = 0
        insert_mark = self.text.index("insert")
        start = "1.0"

        while True:
            pos = self.text.search(term, start, stopindex="end", nocase=nocase)
            if not pos:
                break
            end = f"{pos}+{len(term)}c"
            self.text.delete(pos, end)
            self.text.insert(pos, repl)
            start = f"{pos}+{len(repl)}c"
            count += 1

        self.text.mark_set("insert", insert_mark)
        self._clear_tags()
        self.status.configure(text=f"替换了 {count} 处")


if __name__ == "__main__":
    root = tk.Tk()
    FoxNote(root)
    root.mainloop()
