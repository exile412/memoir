"""打包入口：PyInstaller 从这里开始。

直接跑这个文件等价于 `memoir gui`。
"""

from memoir.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
