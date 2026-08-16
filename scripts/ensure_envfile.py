#!/usr/bin/env python3
"""确保 gateway service 的 EnvironmentFile 存在。
每次 gateway 启动前自动运行（通过 systemd ExecStartPre）。
hermes update 会覆盖 service 文件，但 ExecStartPre 调用这个脚本，
脚本会重新加回 EnvironmentFile。"""
import pathlib, sys

PROFILES = {
    "hermes-gateway": pathlib.Path.home() / ".hermes" / ".env",
    "hermes-gateway-wechat2": pathlib.Path.home() / ".hermes" / "profiles" / "wechat2" / ".env",
    "hermes-gateway-wechat3": pathlib.Path.home() / ".hermes" / "profiles" / "wechat3" / ".env",
}

# 从 systemd service 名字推断 profile
service_name = pathlib.Path(sys.argv[0] if len(sys.argv) > 0 else "").stem
# ExecStartPre 传入的是脚本路径，我们需要从环境变量获取 service name
import os
invocation_id = os.environ.get("INVOCATION_ID", "")

# 遍历所有 service 文件确保 EnvironmentFile 存在
systemd_dir = pathlib.Path.home() / ".config/systemd/user"
fixed = 0
for svc, envf in PROFILES.items():
    svc_path = systemd_dir / f"{svc}.service"
    if not svc_path.exists():
        continue
    text = svc_path.read_text()
    
    # 检查是否已有正确的 EnvironmentFile
    if f"EnvironmentFile={envf}" in text:
        continue
    
    # 加 EnvironmentFile（在 ExecStart 前）
    lines = text.splitlines()
    new_lines = []
    inserted = False
    for line in lines:
        if line.startswith("ExecStart=") and not inserted:
            new_lines.append(f"EnvironmentFile={envf}")
            inserted = True
        new_lines.append(line)
    
    if inserted:
        svc_path.write_text("\n".join(new_lines) + "\n")
        fixed += 1
        print(f"✅ {svc}: EnvironmentFile added")

if fixed > 0:
    import subprocess
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=10)
    print(f"✅ daemon-reload done ({fixed} files fixed)")
else:
    print("✅ All EnvironmentFile entries present")

sys.exit(0)
