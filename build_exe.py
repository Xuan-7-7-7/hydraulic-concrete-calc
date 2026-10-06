"""打包为单文件 exe（build_exe.bat 只是本脚本的纯 ASCII 壳）。

用 Python 而不是纯 bat 的原因：exe 名与提示信息含中文，cmd 在不同代码页下
对 UTF-8 批处理的解析与传参会错位（实测 chcp 65001 会触发"注释被当命令执行"、
goto/echo 被撕碎）；subprocess 以 UTF-16 传参、print 走控制台代码页（GBK 可表
中文），全程无编码歧义。打包配置以 受弯承载力计算.spec 为唯一事实源。
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXE = ROOT / "dist" / "受弯承载力计算.exe"


def main():
    if getattr(sys, "frozen", False):
        print("本脚本用于从源码打包；请在源码目录用 python 运行，不要在 exe 里跑。")
        return 1
    cmd = [sys.executable, "-m", "PyInstaller",
           "--noconfirm", str(ROOT / "受弯承载力计算.spec")]
    print("$", " ".join(cmd))
    if subprocess.run(cmd, cwd=str(ROOT)).returncode != 0:
        print("FAILED: close the running exe, then retry.")
        return 1
    if not EXE.exists():
        print(f"FAILED: {EXE.name} not found after build.")
        return 1
    # 同步题库：exe 读的是它自己旁边的 dist\problems.json（与开发态根目录那份相互
    # 独立）；以开发态题库为准覆盖过去，覆盖前留滚动备份 dist\problems.json.bak。
    # 注意 exe 启动时会重置题库（_reset_store_at_boot），这份只是初始化兜底。
    dist_store = ROOT / "dist" / "problems.json"
    if dist_store.exists():
        shutil.copyfile(dist_store, ROOT / "dist" / "problems.json.bak")
    shutil.copyfile(ROOT / "problems.json", dist_store)
    print(f"完成：{EXE}（约 {EXE.stat().st_size / 1e6:.0f} MB；"
          f"题库已同步，旧档备份 dist\\problems.json.bak）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
