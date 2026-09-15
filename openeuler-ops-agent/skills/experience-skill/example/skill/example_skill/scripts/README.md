# 可执行脚本目录

将可执行的辅助脚本（Python、Bash、JavaScript 等）放入此目录。
在 skill_def.md 中通过相对路径引用，例如：`scripts/extract.py`

脚本编写要求：
- 自包含或清晰声明依赖
- 包含 --help 用法说明
- 妥善处理错误和边界条件
