#!/usr/bin/env python3
"""
Hermes 更新后自动修复脚本 — 一键修所有更新后丢失的东西

用法:
  python3 hermes_patch.py              # 执行全部修复
  python3 hermes_patch.py --check      # 检查状态
  python3 hermes_patch.py --revert     # 还原代码 patch（不影响 systemd）
"""
import os
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
REPO = HOME / ".hermes" / "hermes-agent"
RUN_PY = REPO / "gateway" / "run.py"
BASE_PY = REPO / "gateway" / "platforms" / "base.py"
SYSTEMD_DIR = HOME / ".config" / "systemd" / "user"
GATEWAY_SERVICES = ["hermes-gateway", "hermes-gateway-wechat2", "hermes-gateway-wechat3"]

def is_git_patched():
    if not RUN_PY.exists():
        return False
    return "PATCHED: 不发 shutdown" in RUN_PY.read_text(encoding="utf-8")

def patch_git():
    """静默 shutdown 通知"""
    if not RUN_PY.exists():
        print("❌ 找不到 gateway/run.py")
        return False
    # 先还原
    subprocess.run(["git", "checkout", "--", "gateway/run.py"], cwd=str(REPO), capture_output=True, timeout=10)
    text = RUN_PY.read_text(encoding="utf-8")
    
    old = 'async def _notify_active_sessions_of_shutdown(self) -> None:\n        """Send shutdown/restart notifications'
    new = 'async def _notify_active_sessions_of_shutdown(self) -> None:\n        return  # PATCHED: 不发 shutdown 通知到微信\n        """Send shutdown/restart notifications'
    
    if old in text:
        text = text.replace(old, new, 1)
        RUN_PY.write_text(text, encoding="utf-8")
        print("  ✅ shutdown 通知已静默")
    else:
        print("  ⚠️ shutdown patch 匹配失败（代码可能已变）")
    return True

def is_image_cache_patched():
    if not BASE_PY.exists():
        return False
    return "Images are now persisted into the Obsidian vault" in BASE_PY.read_text(encoding="utf-8")


def patch_image_cache():
    """图片缓存永久保留：cleanup_image_cache 改为 no-op"""
    if not BASE_PY.exists():
        print(" 找不到 base.py")
        return False
    text = BASE_PY.read_text(encoding="utf-8")
    if "Images are now persisted into the Obsidian vault" in text:
        print("  cleanup_image_cache already patched")
        return True
    if "return _cleanup_cache_dir(get_image_cache_dir(), max_age_hours)" in text:
        text = text.replace(
            "    return _cleanup_cache_dir(get_image_cache_dir(), max_age_hours)",
            "    return 0  # PATCHED: 图片永久保留（assets/weixin）",
            1,
        )
        BASE_PY.write_text(text, encoding="utf-8")
        print("  cleanup_image_cache no-op")
    else:
        print("  cleanup_image_cache patch 匹配失败（代码可能已变）")
    return True


def is_tavily_in_service(svc):
    p = SYSTEMD_DIR / f"{svc}.service"
    if not p.exists():
        return False
    return "TAVILY_API_KEY" in p.read_text()

def patch_systemd():
    """给所有 gateway service 加 EnvironmentFile"""
    env_map = {
        "hermes-gateway": [
            str(HOME / ".config" / "hermes" / "secret-store" / "hermes.env"),
            str(HOME / ".hermes" / ".env"),
        ],
        "hermes-gateway-wechat2": [
            str(HOME / ".config" / "hermes" / "secret-store" / "hermes.env"),
            str(HOME / ".hermes" / "profiles" / "wechat2" / ".env"),
        ],
        "hermes-gateway-wechat3": [
            str(HOME / ".config" / "hermes" / "secret-store" / "hermes.env"),
            str(HOME / ".hermes" / "profiles" / "wechat3" / ".env"),
        ],
    }
    fixed = 0
    for svc, env_files in env_map.items():
        svc_path = SYSTEMD_DIR / f"{svc}.service"
        if not svc_path.exists():
            continue
        text = svc_path.read_text()
        # 删掉旧的 TAVILY Environment 行
        text = "\n".join(l for l in text.splitlines() if "Environment=\"TAVILY" not in l)
        # 加缺失的 EnvironmentFile（secret store + profile env）
        lines = text.splitlines()
        existing_efs = [l.split("=", 1)[1] for l in lines if l.startswith("EnvironmentFile=")]
        missing = [ef for ef in env_files if ef not in existing_efs]
        if missing:
            new_lines = []
            for line in lines:
                if "ExecStart=" in line:
                    for ef in missing:
                        new_lines.append(f"EnvironmentFile={ef}")
                new_lines.append(line)
            text = "\n".join(new_lines) + "\n"
            svc_path.write_text(text)
            print(f"  ✅ {svc}: +{len(missing)} EnvironmentFile {missing}")
            fixed += 1
        else:
            print(f"  ⏭️ {svc}: EnvironmentFile 完整")
    if fixed > 0:
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=10)
    return True

def fix_wigolo_chromium():
    """修复 wigolo Playwright Chromium 符号链接"""
    pw_dir = HOME / ".cache" / "ms-playwright"
    if not pw_dir.exists():
        return
    
    # 找已有的 chromium 版本
    chromium_dirs = [d for d in pw_dir.iterdir() if d.name.startswith("chromium-") and not "headless" in d.name]
    if not chromium_dirs:
        return
    
    # 用最新的
    src = sorted(chromium_dirs)[-1]
    src_version = src.name.split("-")[-1]
    
    # 链接 chromium-1223（wigolo 期望的版本）
    link = pw_dir / "chromium-1223"
    if not link.exists() or link.resolve() != src.resolve():
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(src)
        print(f"  ✅ chromium-1223 → {src.name}")
    
    # headless shell
    hl_dir = pw_dir / f"chromium_headless_shell-1223" / "chrome-headless-shell-linux64"
    hl_dir.mkdir(parents=True, exist_ok=True)
    hl_link = hl_dir / "chrome-headless-shell"
    src_chrome = src / "chrome-linux64" / "chrome"
    if src_chrome.exists() and not hl_link.exists():
        hl_link.symlink_to(src_chrome)
        print(f"  ✅ headless-shell → {src.name}")

def run_all():
    print("🔧 Hermes 更新后修复...")
    print()
    print("① 代码 patch（静默 shutdown）:")
    patch_git()
    print()
    print("①b 代码 patch（图片缓存永久保留）:")
    patch_image_cache()
    print()
    print("② systemd TAVILY key:")
    patch_systemd()
    print()
    print("③ wigolo Chromium 链接:")
    fix_wigolo_chromium()
    print()
    print("✅ 全部完成。请重启 gateway：")
    print("   hermes_update_hook.sh")

def check():
    print(f"代码 patch: {'✅ 已 patch' if is_git_patched() else '❌ 未 patch'}")
    for svc in GATEWAY_SERVICES:
        print(f"TAVILY {svc}: {'✅' if is_tavily_in_service(svc) else '❌'}")

if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    elif "--revert" in sys.argv:
        subprocess.run(["git", "checkout", "--", "gateway/run.py"], cwd=str(REPO), capture_output=True)
        print("✅ 代码已还原")
    else:
        run_all()
