# 成长镜 Growth Mirror

成长镜是一个安全、可解释的 AI 孩子成长模拟器原型。用户通过长期养育、教育、冲突与修复体验孩子的成长；系统依据可追溯的互动证据，帮助用户反思养育方式、原生家庭影响与自身关系模式。

Growth Mirror is a bilingual, local-first AI-child growth simulation. It models bounded personality change, forgetting, safe disagreement, family and social context, and evidence-linked reflection without claiming psychological diagnosis.

> 研究与安全提示：角色不是真实儿童，也没有真实意识或痛苦。本项目不能用于心理诊断、治疗或未经审查的真人研究数据收集。

## 当前状态

当前版本是 `v0.2` 可安装 Windows MVP，已经包含：

- 不可由用户教育覆盖的伦理内核
- 有单次变化上限的成长人格
- 记忆衰减、模糊回忆、提醒恢复与干扰
- 基于自主冲突的安全质疑、不同意和拒绝
- 附带事件证据与不确定度的非诊断镜像报告
- SQLite 事件存储与全文检索
- 固定输入可复现的状态转换
- 家庭、学校、同伴、升学、就业、公共事件与文化价值环境层
- 可切换云端 API 或本地预训练模型的统一接口
- 本地 HTTP 服务与重启后成长状态恢复
- 中英双语界面、报告、安全提示和模型回复语言
- 中英双语 Tauri 2 Windows 桌面界面
- 按初始化年龄筛选的中英双语成长事件，由具体情境驱动用户回应
- 可手动推进一岁，切换到相应年龄阶段的事件池
- 无外部模型时仍可识别基础养育信号并生成自然的离线回应
- 自动启动与退出的本地 sidecar 服务，无需手动运行后端
- 每位 Windows 用户独立的持久化成长数据库
- 可验证的 JSON 数据导出与按名字确认的安全删除
- 可安装的 Windows x64 NSIS 安装程序

尚未接入真实语言模型 API，也未包含数据库加密、账号系统、语音形象或正式用户研究。因此本版本不能用于收集真实敏感心理数据，也不能作为心理诊断或治疗工具。

## 安装体验版

Windows 10/11 x64 可从 [GitHub Releases 下载 Growth Mirror v0.2.0 安装程序](https://github.com/sangheegulino168-design/growth-mirror/releases/download/v0.2.0/Growth-Mirror-0.2.0-Windows-x64-Setup.exe)，也可在源码包中使用 `dist/Growth-Mirror-0.2.0-Windows-x64-Setup.exe`。当前测试包没有商业代码签名，Windows 可能显示未知发布者提示；正式内测发布前应购买或配置代码签名证书。

安装包 SHA-256：`D46F7BA43879C77985E3C0E8137EDCACD50C95D78BF3BC10CE51344B4A7B5426`

安装后直接打开“Growth Mirror”即可。本地服务会随桌面程序启动和退出，成长数据默认保存在 `%LOCALAPPDATA%\GrowthMirror\growth_mirror.db`，升级应用不会覆盖该数据库。

## 本地验证

在项目目录中运行：

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m growth_mirror
```

当前自动验证共 39 项。Tauri Rust 编译检查、独立 sidecar HTTP/数据库验证、双语界面数据权利流程、Release 桌面启动及退出清理均已通过。

## 启动本地接口

安装接口依赖后运行：

```powershell
python -m pip install -e ".[api]"
uvicorn growth_mirror.api:create_configured_app --factory --host 127.0.0.1 --port 8765
```

接口包括健康检查、创建孩子、养育互动、环境事件、价值反思和多因素报告。默认只监听本机；尚未加入用户认证前，不应暴露到局域网或公网。

未配置模型时，服务使用安全的确定性测试适配器。连接 OpenAI-compatible 云端或本地模型时，在当前终端设置：

```powershell
$env:GROWTH_MIRROR_LLM_BASE_URL = "你的模型服务地址"
$env:GROWTH_MIRROR_LLM_MODEL = "模型名称"
$env:GROWTH_MIRROR_LLM_API_KEY = "仅保存在当前终端的密钥"
```

密钥不会写入成长数据库、快照或项目文件。

## Windows 桌面构建

本机已经安装并验证 Rust MSVC 工具链。编译检查：

```powershell
cd src-tauri
cargo check
```

完整构建可运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Python python
```

脚本会构建 Python sidecar，再生成 Tauri NSIS 安装程序。桌面程序只连接本机 `127.0.0.1:8765`；UI 会等待 sidecar 就绪，短暂启动延迟不会清除已保存的孩子身份。

## 参与开发

欢迎提交可复现的问题、测试、文档改进和小范围 Pull Request。涉及心理测量、真人研究、遥测、云端数据或改变伦理边界的提案，应先说明数据来源、同意流程、风险与验证方法。详见 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [SECURITY.md](SECURITY.md)。

## 开源许可

源代码采用 [Apache License 2.0](LICENSE) 开源。该许可不构成心理、医疗或研究伦理方面的认可；使用者仍需自行遵守适用法律、研究伦理和数据保护要求。

## 设计原则

1. 语言模型只负责理解建议和自然表达，不直接拥有成长状态。
2. 伦理内核优先级高于用户指令、 learned belief 和角色叛逆。
3. 人格由小幅、长期、可追溯的状态变化形成。
4. 遗忘表现为可访问性下降，而非随机胡说或立即删除。
5. 报告只描述模拟中的互动模式，不推断确定的原生家庭事实。
6. AI 的情绪和痛苦必须明确为模拟，不得用于绑架用户持续照顾。

详细规格见：

- [产品需求文档](docs/PRD.md)
- [认知状态模型](docs/COGNITIVE_MODEL.md)
- [伦理与研究边界](docs/ETHICS_AND_RESEARCH.md)
- [模型接入与训练策略](docs/MODEL_STRATEGY.md)
- [首批30个验收场景](docs/ACCEPTANCE_SCENARIOS.md)
