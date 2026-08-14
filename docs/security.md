# 安全设计

> 这套系统把「个人对话 + AI 会话 + 密钥」都沉淀在本地，安全设计是重中之重。

## 1. 威胁模型

| 威胁 | 缓解 |
|---|---|
| Vault 同步到第三方云（iCloud/GitHub）泄露明文密钥 | Raw 写入前自动脱敏，密钥进系统 Keychain |
| AI 把敏感信息写进笔记 | redact_secrets.py 前置脱敏 + prompt 层规则 |
| 开源仓库泄露真实路径/IP/账号 | 本仓库全部占位符化（<PLACEHOLDER>） |
| 服务器被攻破 | 密钥 fail-closed：无 Keychain 时写 UNSTORED- 引用，不落明文 |
| 误删数据（同步/脚本 bug） | 双向同步不带 --delete；每日加密备份；Git 历史 |
| AI 幻觉入库（报告成功但没写） | 自动化校验：文件存在性 + hash 签名；蒸馏状态机 |
| 恶意节点注册（往 .hermes-nodes 投递假节点） | 见下方「自动信任的设计边界」 |

### 自动信任的设计边界（重要，读后再部署）

`node-discovery.sh` 会**自动把注册标记里的 SSH 公钥加入服务器 authorized_keys**，实现新机器零人工接入。这是有意为之的设计选择（全自动优先），但有明确边界：

- ✅ **适用环境**：家庭内网、所有能写 Vault 的设备/账号都是你本人信任的
- ⚠️ **风险路径**：iCloud 账号被盗 / Vault 目录被第三方 App 写入 → 攻击者投递含自己公钥的 json → node-discovery 自动信任 → 攻击者获得服务器 SSH 权限。**注意：这条路径完全走 Vault 同步，不经过公网 22 端口直连。**
- 🛡️ **对症缓解**（按此风险路径设计）：
  1. **iCloud 账号开启双重认证**（降低账号被盗概率，直接堵住主要入口）
  2. **Vault 目录不共享给不受控的第三方 App/插件/其他人**（控制投递面的可写范围）
  3. **定期检查 `.hermes-nodes/` 目录**（有新文件会收到 Telegram 通知，检查是否本人操作）
  4. 不想要自动信任：注释掉 `node-discovery.sh` 里的「建立 SSH 信任」代码块，改为人工执行
- 📝 **代码层防护**（已内置，降低投递文件被误用的概率）：注册文件名白名单 + JSON 字段严格校验 + SSH 公钥格式校验（拒绝换行注入）+ flock 并发锁 + umask 077

> 补充说明：服务器防火墙限制 SSH 仅内网可访问，防的是「外部直接扫描 22 端口」这条攻击面，与上面的 iCloud 投递路径无关——两条防线独立，建议都做，但不要用前者替代后者。

## 2. 脱敏管线

```text
原始会话（含密钥/token/路径）
  │
  ▼ redact_secrets.py（写入 Raw 前）
  │  识别：API key / password / cookie / token / JWT / private key / db URL 密码
  │  macOS：加密进 Login Keychain，替换为 [SECRET:type:sec_xxx]
  │  Linux：无 Keychain → fail-closed 写 UNSTORED- 引用
  ▼
Raw Chat Logs（只含脱敏引用，无明文）
  │
  ▼ 蒸馏（LLM 只看到 [SECRET:...]）
  ▼
Wiki / Lessons（结论 + 来源，无明文）
```

### 密钥库备份与恢复

```bash
# 全量加密导出（AES-256-CBC + PBKDF2）
python3 ~/.hermes/scripts/secret_vault_export.py export

# 校验 vault 里所有 [SECRET] 引用都能在 Keychain 解析
python3 ~/.hermes/scripts/secret_vault_export.py check --vault ~/obsidian

# 换机恢复
python3 ~/.hermes/scripts/secret_vault_export.py import
```

## 3. 仓库安全红线

1. **绝不**在 Wiki / Chat Logs / SQLite / Chroma / GitHub / 日志中写明文密钥
2. **绝不**在没有用户明确同意时修改网络配置（iptables / 代理 / 路由）
3. **绝不**删除 Raw Chat Logs（蒸馏只读）
4. Secret Store 内容只在服务器读取，不复制到其他机器
5. SSH 密钥不离开本机
6. 修改 systemd 服务前先备份
7. 修改配置前先 cp 备份

## 4. 开源仓库的自检清单

推送公开仓库前，运行：

```bash
# 扫描真实 IP / 用户名 / 路径
grep -rnE "192\.168\.|/home/[a-z]+/|@[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" .

# 扫描密钥形态
grep -rnE "sk-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|token\s*=\s*['\"][a-zA-Z0-9_-]{20,}" .

# 扫描 .env 类文件
find . -name ".env" -o -name "*.pem" -o -name "*secret*" | grep -v _source
```

## 5. 备份策略

| 备份 | 频率 | 内容 |
|---|---|---|
| Git | 每小时 | Wiki 知识层版本控制（推私有仓库） |
| 加密备份 | 每日 | vault / database / runtime（rclone 到远程加密存储） |
| 密钥库 | 手动/定期 | Keychain secret 全量加密导出（.enc 文件） |

### 恢复演练

```bash
# 从加密备份恢复 vault
rclone copy crypt_remote:backup/obsidian/vault/ /tmp/restore-test/ -P

# 恢复密钥库
python3 ~/.hermes/scripts/secret_vault_export.py import --file hermes-secret-vault-xxx.enc
```

## 6. 已知风险

1. macOS Keychain 是单机绑定——换机必须用 secret_vault_export.py 迁移
2. 蒸馏 prompt 与 LLM 本身可能把 [SECRET] 引用以外的旁路信息写进页面——需要定期审计
3. 微信/Telegram 网关凭证在服务器 secret store，泄露面 = 服务器被攻破
4. **`keychain_secret.swift` 不在公开仓库**（属私有 Hermes 仓库）。缺失时 redact_secrets.py 降级为 `UNSTORED-` fail-closed：密钥不落明文，但也**不会被保存**（引用不可还原）。需要完整密钥保存功能的用户，请从私有 Hermes 仓库拷贝该文件到 `scripts/` 目录
