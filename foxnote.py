#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FoxNote —— 增加了查找/替换功能

import os
import tkinter as tk
from tkinter import filedialog, messagebox

APP_NAME = "FoxNote"
ICONS = ("foxnote.png", "icon.png")


class FoxNote:
    def __init__(self, root):
        self.root = root
        self.current_file = None
        self.modified = False
        self.dark = False

        root.geometry("800x600")
        self._load_icon()
        self._build_menu()
        self._build_editor()
        self._build_find_bar()      # 必须在 editor 之后
        self._apply_theme()
        self._update_title()

        root.protocol("WM_DELETE_WINDOW", self.on_close)

        root.bind_all("<Control-n>", self.new_file)
        root.bind_all("<Control-o>", self.open_file)
        root.bind_all("<Control-s>", self.save_file)
        root.bind_all("<Control-Shift-S>", self.save_as)
        root.bind_all("<Control-d>", self.toggle_dark)
        root.bind_all("<Control-f>", self.show_find)
        root.bind_all("<Control-h>", self.show_replace) # Ctrl+H 呼出替换
        root.bind_all("<F3>", self.find_next)
        root.bind_all("<Shift-F3>", self.find_prev)

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
        m.add_command(label="退出", command=self.on_close)
        bar.add_cascade(label="文件", menu=m)

        m = tk.Menu(bar, tearoff=0)
        m.add_command(label="查找...", accelerator="Ctrl+F", command=self.show_find)
        m.add_command(label="替换...", accelerator="Ctrl+H", command=self.show_replace)
        m.add_command(label="查找下一个", accelerator="F3", command=self.find_next)
        m.add_command(label="查找上一个", accelerator="Shift+F3", command=self.find_prev)
        bar.add_cascade(label="编辑", menu=m)

        m = tk.Menu(bar, tearoff=0)
        m.add_command(label="深色模式", accelerator="Ctrl+D", command=self.toggle_dark)
        bar.add_cascade(label="视图", menu=m)

        self.root.config(menu=bar)

    # ---- 主体 ----
    def _build_editor(self):
        self.frame = tk.Frame(self.root)
        self.frame.pack(fill="both", expand=True)

        self.text = tk.Text(self.frame, undo=True, wrap="word", font=("Monospace", 12))
        self.text.pack(side="left", fill="both", expand=True)

        sb = tk.Scrollbar(self.frame, command=self.text.yview)
        sb.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=sb.set)

        self.text.bind("<<Modified>>", self._on_modified)
        self.text.bind("<Escape>", self._on_escape)

        self.status = tk.Label(self.root, text="就绪", anchor="w")
        self.status.pack(side="bottom", fill="x")

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
        self.text.configure(bg=c["bg"], fg=c["fg"],
                            insertbackground=c["cursor"],
                            selectbackground=c["select"])
        self.frame.configure(bg=c["bg"])
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

        self.text.tag_configure("hit", background="#ffb74d", foreground="#000000")

    def toggle_dark(self, e=None):
        self.dark = not self.dark
        self._apply_theme()

    # ---- 修改标记 ----
    def _on_modified(self, e=None):
        if not self.text.edit_modified():
            return
        self.modified = True
        self.status.configure(text="已修改")
        self._clear_tags()
        self._update_title()
        self.text.edit_modified(False)

    def _update_title(self):
        name = os.path.basename(self.current_file) if self.current_file else "未命名"
        mark = "*" if self.modified else ""
        self.root.title(f"{mark}{name} - {APP_NAME}")

    def _maybe_save(self):
        if not self.modified:
            return True
        return messagebox.askyesno("等等", "还没保存，确定要丢弃改动吗？")

    # ---- 文件 ----
    def new_file(self, e=None):
        if not self._maybe_save():
            return
        self.text.delete("1.0", "end")
        self.current_file = None
        self.modified = False
        self._clear_tags()
        self._update_title()
        self.status.configure(text="新建文件")

    def open_file(self, e=None):
        if not self._maybe_save():
            return
        path = filedialog.askopenfilename(
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = f.read()
        except OSError as ex:
            messagebox.showerror("打不开", str(ex))
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", data)
        self.current_file = path
        self.modified = False
        self._clear_tags()
        self._update_title()
        self.status.configure(text=f"打开 {path}")

    def save_file(self, e=None):
        if self.current_file:
            self._save_to(self.current_file)
        else:
            self.save_as()

    def save_as(self, e=None):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if path:
            self._save_to(path)

    def _save_to(self, path):
        data = self.text.get("1.0", "end")
        if data.endswith("\n"):
            data = data[:-1]
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)
        except OSError as ex:
            messagebox.showerror("存不了", str(ex))
            return
        self.current_file = path
        self.modified = False
        self._update_title()
        self.status.configure(text=f"已保存到 {path}")

    def on_close(self):
        if self._maybe_save():
            self.root.destroy()

    # ---- 查找与替换 ----
    def show_find(self, e=None):
        if not self.find_frame.winfo_ismapped():
            self.find_frame.pack(side="bottom", fill="x", before=self.status)
        
        # 默认隐藏替换行
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
        self.row_replace.pack(fill="x", pady=(0, 4)) # 显示替换行
        self._prepare_find()
        self.replace_entry.focus_set() # 焦点给替换框
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
        self.text.tag_remove("hit", "1.0", "end")

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
        self.find_next() # 替换完自动找下一个
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
            # 从替换后的文本末尾继续找
            start = f"{pos}+{len(repl)}c"
            count += 1
            
        self.text.mark_set("insert", insert_mark)
        self._clear_tags()
        self.status.configure(text=f"替换了 {count} 处")


if __name__ == "__main__":
    root = tk.Tk()
    FoxNote(root)
    root.mainloop()
