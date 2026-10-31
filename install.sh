#!/usr/bin/env bash
# FoxNote 一键安装脚本 (支持自定义图标)
#
# 用法:
#   ./install.sh              # 安装（默认安装到 ~/.local）
#   ./install.sh --uninstall  # 卸载
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SCRIPT_DIR}/foxnote.py"
ICON_SRC="${SCRIPT_DIR}/foxnote.png" # 自定义图标路径

APP_NAME="foxnote"
APP_ID="org.foxnote.FoxNote"

PREFIX="${HOME}/.local"
BIN_DIR="${PREFIX}/bin"
APPS_DIR="${PREFIX}/share/applications"
DATA_DIR="${PREFIX}/share/foxnote" # 图标存放目录

TARGET="${BIN_DIR}/${APP_NAME}"
DESKTOP_FILE="${APPS_DIR}/${APP_ID}.desktop"

# ---- 颜色 ----
if [ -t 1 ]; then
    GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
else
    GREEN=''; YELLOW=''; RED=''; NC=''
fi
info() { printf "${GREEN}==>${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}警告:${NC} %s\n" "$*"; }
err()  { printf "${RED}错误:${NC} %s\n" "$*" >&2; }

# ---- 卸载 ----
if [ "${1:-}" = "--uninstall" ] || [ "${1:-}" = "-u" ]; then
    info "卸载 FoxNote"
    rm -f "$TARGET" "$DESKTOP_FILE"
    rm -rf "$DATA_DIR"
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database "$APPS_DIR" 2>/dev/null || true
    info "已卸载。"
    exit 0
fi

# ---- 前置检查 ----
[ -f "$SRC" ] || { err "未找到 foxnote.py（应与本脚本在同一目录）"; exit 1; }
command -v python3 >/dev/null 2>&1 || { err "需要 python3 已安装"; exit 1; }

# 检测 Python 依赖：0 = 全部齐全；1 = 缺 GTK4/PyGObject；2 = 只缺 GtkSourceView
check_pydeps() {
    python3 - <<'PY'
import sys
try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk  # noqa: F401
except Exception:
    sys.exit(1)
try:
    gi.require_version("GtkSource", "5")
    from gi.repository import GtkSource  # noqa: F401
except Exception:
    sys.exit(2)
sys.exit(0)
PY
}

DEP_STATUS=0
check_pydeps || DEP_STATUS=$?

case $DEP_STATUS in
    0) info "依赖检查通过：GTK4 + GtkSourceView 5 ✓" ;;
    2) warn "缺少 GtkSourceView 5（程序仍可运行，但无语法高亮 / 行号）" ;;
    1) warn "缺少 GTK4 或 PyGObject" ;;
esac

if [ "$DEP_STATUS" -ne 0 ]; then
    DISTRO="unknown"
    if [ -r /etc/os-release ]; then
        . /etc/os-release
        DISTRO="${ID:-unknown}"
    fi
    INSTALL_CMD=""
    case "$DISTRO" in
        ubuntu|debian|linuxmint|pop|elementary|zorin)
            INSTALL_CMD="sudo apt-get update && sudo apt-get install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-gtksource-5" ;;
        fedora|rhel|centos)
            INSTALL_CMD="sudo dnf install -y python3-gobject gtk4 gtksourceview5" ;;
        arch|manjaro|endeavouros)
            INSTALL_CMD="sudo pacman -S --needed --noconfirm python-gobject gtk4 gtksourceview5" ;;
        opensuse*|suse|sles)
            INSTALL_CMD="sudo zypper install -y python3-gobject gtk4 typelib-1_0-GtkSource-5" ;;
    esac
    if [ -n "$INSTALL_CMD" ]; then
        echo
        warn "建议运行以下命令安装系统依赖："
        echo "    ${INSTALL_CMD}"
        echo
        read -r -p "现在自动安装？[y/N] " ans
        if [[ "${ans,,}" == "y" || "${ans,,}" == "yes" ]]; then
            bash -c "$INSTALL_CMD"
        fi
    else
        warn "未识别的发行版，请手动安装：PyGObject + GTK4 + GtkSourceView 5"
    fi
fi

# ---- 安装程序 ----
info "安装到 ${TARGET}"
mkdir -p "$BIN_DIR"
install -m 755 "$SRC" "$TARGET"

# ---- 处理图标 ----
ICON_PATH="accessories-text-editor" # 默认兜底图标
if [ -f "$ICON_SRC" ]; then
    info "安装自定义图标"
    mkdir -p "$DATA_DIR"
    install -m 644 "$ICON_SRC" "${DATA_DIR}/foxnote.png"
    ICON_PATH="${DATA_DIR}/foxnote.png"
else
    warn "当前目录未找到 foxnote.png，将使用系统默认图标"
fi

# ---- 创建桌面入口 ----
info "创建桌面入口 ${DESKTOP_FILE}"
mkdir -p "$APPS_DIR"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=FoxNote
GenericName=文本编辑器
Comment=轻量级 GTK4 文本编辑器
Exec=${TARGET} %F
Icon=${ICON_PATH}
Terminal=false
Categories=Utility;TextEditor;GTK;
MimeType=text/plain;text/markdown;text/x-python;application/json;
StartupNotify=true
StartupWMClass=${APP_ID}
EOF
chmod 644 "$DESKTOP_FILE"

# 刷新桌面数据库和图标缓存
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && \
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

# ---- 完成提示 ----
case ":${PATH}:" in
    *":${BIN_DIR}:"*) ;;
    *)
        warn "${BIN_DIR} 不在 PATH 中"
        echo "  请在 ~/.bashrc 或 ~/.zshrc 中加入："
        echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
        echo "  然后重新打开终端或执行: source ~/.bashrc"
        ;;
esac

echo
info "安装完成！"
echo "  · 可执行文件 : ${TARGET}"
echo "  · 桌面入口   : ${DESKTOP_FILE}"
echo "  · 图标路径   : ${ICON_PATH}"
echo "  · 启动方式   : 终端输入 'foxnote'，或在应用菜单搜索 'FoxNote'"
