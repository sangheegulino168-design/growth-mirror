# Contributing to Growth Mirror

感谢你帮助改进成长镜。为了让项目保持可解释、可复现和安全，请遵循以下约定。

## 开始之前

1. 先搜索现有 Issue，确认问题没有重复。
2. Bug 报告请包含操作系统、版本、最小复现步骤、预期结果和实际结果。
3. 不要上传真实儿童、家庭、医疗、心理或其他敏感个人数据。
4. 安全漏洞不要放入公开 Issue，请按 `SECURITY.md` 处理。

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[api,desktop-build]"
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

桌面端还需要 Node.js、Rust MSVC 工具链和 Tauri 2 构建依赖。

## Pull Request 要求

- 修改保持小而清晰，并解释行为变化。
- 新增状态变化逻辑必须具备确定性测试和单次变化上限。
- 模型输出不能直接修改长期人格、伦理内核或删除数据。
- 报告必须链接证据并保留不确定性与替代解释。
- 中英双语界面修改应同时更新两种语言。
- 提交前运行完整测试，且不得提交密钥、数据库、构建缓存或打包二进制。

提交贡献即表示你同意按本仓库的 Apache License 2.0 提供该贡献。
