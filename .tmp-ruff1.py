p = 'scripts/obsidian_backup.py'
s = open(p).read()
# F541: 去掉无占位符的 f 前缀
s = s.replace('print(f"📊 Obsidian Vault 统计")', 'print("📊 Obsidian Vault 统计")')
s = s.replace('print(f"📂 按目录:")', 'print("📂 按目录:")')
s = s.replace('print(f"🏷️  热门标签 (Top 10):")', 'print("🏷️  热门标签 (Top 10):")')
open(p, 'w').write(s)
import ast
ast.parse(open(p).read())
print('F541 x3 fixed')