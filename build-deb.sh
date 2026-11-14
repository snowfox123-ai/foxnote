#!/usr/bin/env bash
set -e

NAME=foxnote
VERSION="1.0.2"
ARCH=all
PKG="build/${NAME}_${VERSION}_${ARCH}"

rm -rf build
mkdir -p "$PKG/DEBIAN"
mkdir -p "$PKG/usr/bin"
mkdir -p "$PKG/usr/share/applications"
# 创建图标存放目录
mkdir -p "$PKG/usr/share/icons/hicolor/256x256/apps"

# 安装可执行文件
install -m 755 foxnote.py "$PKG/usr/bin/foxnote"
# 安装桌面文件
install -m 644 foxnote.desktop "$PKG/usr/share/applications/foxnote.desktop"
# 安装图标 (源文件为 foxnote.png，目标重命名为 foxnote.png)
install -m 644 foxnote.png "$PKG/usr/share/icons/hicolor/256x256/apps/foxnote.png"

cat > "$PKG/DEBIAN/control" <<CTRL
Package: ${NAME}
Version: ${VERSION}
Architecture: ${ARCH}
Maintainer: Your Name <you@example.com>
Section: editors
Priority: optional
Depends: python3, python3-gi, gir1.2-gtk-4.0
Recommends: gir1.2-gtksource-5
Description: FoxNote - a lightweight GTK4 text editor
 A simple tabbed text editor written in Python with GTK4 / GtkSourceView.
CTRL

dpkg-deb --build --root-owner-group "$PKG" "${NAME}_${VERSION}_${ARCH}.deb"
echo "✔ 生成: ${NAME}_${VERSION}_${ARCH}.deb"
