"""一键换图标：从任意图片生成 .ico 并更新桌面快捷方式。

为什么要有这个脚本：
Windows 会缓存图标，直接覆盖同名 .ico 往往不生效，得手动清 iconcache、
重启资源管理器。这里改了个思路——**文件名带上内容哈希**，换了图就是新文件，
缓存自然失效，不用再折腾。

用法：
    python tools/set_icon.py 路径/图.jpg
    python tools/set_icon.py 图.jpg --box 0.2,0.05,0.8,0.7   # 自定义裁切比例
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("需要 Pillow：pip install pillow")
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "design" / "icons"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def build_ico(src: Path, box: tuple[float, float, float, float], radius: float = 0.22) -> Path:
    img = Image.open(src).convert("RGB")
    w, h = img.size
    crop = img.crop((int(w * box[0]), int(h * box[1]), int(w * box[2]), int(h * box[3])))
    squared = crop.resize((256, 256), Image.LANCZOS)

    mask = Image.new("L", (256, 256), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, 255, 255], radius=int(256 * radius), fill=255)
    rounded = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    rounded.paste(squared, (0, 0), mask)

    digest = hashlib.sha1(rounded.tobytes()).hexdigest()[:8]
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    dst = ICON_DIR / f"memoir-{digest}.ico"
    rounded.save(dst, format="ICO", sizes=SIZES)
    return dst


def update_shortcut(ico: Path) -> str:
    """把桌面快捷方式的图标指过去。文件名变了，缓存不会挡。"""
    if sys.platform != "win32":
        return "非 Windows，跳过快捷方式"
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'memoir 记忆.lnk'; "
        "if (Test-Path $lnk) { "
        f"$sc = $ws.CreateShortcut($lnk); $sc.IconLocation = '{ico},0'; $sc.Save(); "
        "'updated' } else { 'shortcut not found' }"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True)
    return (out.stdout or out.stderr).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="从图片生成图标并更新桌面快捷方式")
    ap.add_argument("image", help="源图片路径")
    ap.add_argument("--box", default="0.18,0.06,0.82,0.70",
                    help="裁切比例 left,top,right,bottom，默认聚焦人脸")
    ap.add_argument("--radius", type=float, default=0.22, help="圆角比例")
    args = ap.parse_args()

    src = Path(args.image).expanduser()
    if not src.is_file():
        print(f"找不到图片：{src}")
        return 1
    box = tuple(float(x) for x in args.box.split(","))
    if len(box) != 4:
        print("--box 需要四个数")
        return 1

    ico = build_ico(src, box, args.radius)  # type: ignore[arg-type]
    print(f"图标已生成：{ico}")
    print(f"快捷方式：{update_shortcut(ico)}")
    print("文件名带内容哈希，改了图就是新文件，不用清缓存。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
