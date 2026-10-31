# FoxNote 🦊

> 个人自用项目，基于 Python + GTK4 编写的轻量级代码/文本记事本。

![foxnote](foxnote.png)

## 🎨 开源协议与版权说明

- - **代码开源协议**: MIT License (或个人使用，可按需修改)
- **项目配图/图标**: `foxnote.png` 遵循 [![CC0](https://licensebuttons.net/p/zero/1.0/88x31.png)](https://creativecommons.org/publicdomain/zero/1.0/) 协议。
  作者已放弃该图片的所有版权，将其贡献至公共领域。您可以自由复制、修改、分发，甚至用于商业目的，无需署名。

- 基于 GTK4 和 GtkSourceView 5，原生 Linux 体验。
- 支持多标签页（Tab）编辑。
- 支持语法高亮、行号显示、自动缩进。
- 支持深色/浅色模式无缝切换。
- 内置查找、替换功能。
- 支持未保存状态拦截与确认提示。
- 采用了原子写入（临时文件替换）防止保存崩溃导致文件损坏。

## 🚀 运行方式
### 方式一：一键安装（推荐）
我们提供了一键安装脚本，脚本会自动安装依赖、将程序文件拷贝到系统目录，并创建桌面快捷方式：

```bash
# 赋予脚本执行权限
chmod +x install.sh

# 运行安装脚本（需要管理员权限）
./install.sh
# 然后运行
foxnote
```
如果你想卸载，请运行
```bash
./install.sh --uninstall
```

### 方式二：源码手动运行
如果您不想安装到系统中，只想在终端直接运行，请先安装环境依赖：
```bash
sudo apt update
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-gtksource-5
```
```bash
python3 foxnote.py
```
