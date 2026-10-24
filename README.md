# FoxNote 🦊

> 个人自用项目，基于 Python + GTK4 编写的轻量级代码/文本记事本。

![foxnote](foxnote.png)

## 🎨 开源协议与版权说明

- **代码开源协议**：MIT License（或个人使用，可按需修改）
- **项目配图/图标**：`foxnote.png` 遵循 **[CC BY-SA 4.0](http://creativecommons.org/licenses/by-sa/4.0/)** 协议开源。
[![CC BY-SA 4.0](https://licensebuttons.net/l/by-sa/4.0/88x31.png)](http://creativecommons.org/licenses/by-sa/4.0/)
*(你可以自由共享、演绎此图片，但需保留原作者署名并以相同协议共享。)*

## ✨ 项目说明 / 功能特性

- 基于 GTK4 和 GtkSourceView 5，原生 Linux 体验。
- 支持多标签页（Tab）编辑。
- 支持语法高亮、行号显示、自动缩进。
- 支持深色/浅色模式无缝切换。
- 内置查找、替换功能。
- 支持未保存状态拦截与确认提示。
- 采用了原子写入（临时文件替换）防止保存崩溃导致文件损坏。

## 🚀 运行方式

在 Debian/Ubuntu 等系统上，需要先安装依赖：

```bash
sudo apt update
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-gtksource-5
```
python3 foxnote.py
🚧 待办 / 更新日志 (Todo)

    ☑

    初始化项目并上传代码
    ☑

    更新 README
    ☑

    修复撤销回退后 * 标记不消失的 Bug
    ☑

    修复远程/特殊文件路径获取失败的崩溃问题
    ☑

    深色模式改用 stateful action，状态同步更完美
    ☑

    替换功能增加选区校验，防止误替换
    □

    后续功能修改记在这里...
