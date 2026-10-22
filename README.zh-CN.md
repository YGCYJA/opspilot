# OpsPilot

**一个在本机运行的 pytest 失败分析工具。**

把失败用例、相关源码、Git 改动和项目规则整理到一份可检查的报告中，帮助你决定接下来验证什么。默认离线运行，不需要显卡、模型权重或 API Key。

[English](README.md) · [架构](docs/architecture.md) · [配置](docs/configuration.md) · [API](docs/api.md) · [验证方法](docs/evaluation.md) · [设计取舍](docs/design-decisions.md)

## 解决什么问题

你改了一段购物车代码，某个边界测试开始失败：预期金额是 `90.0`，实际是 `100.0`。排查时需要来回查看测试断言、被测函数、本次修改和折扣规则。

OpsPilot 把这些上下文放到一起：这次测试在哪里失败、相关源码是什么、相对你指定的 Git 基线改了什么、哪条项目规则可能相关，再给出待验证的解释和复现命令。

**分析依赖本次失败的证据，不要求知识库里提前存过这个故障。** Markdown 检索只用于补充项目约定，例如“金额满 100 时减 10”。没有项目文档也能生成基础报告。

它适合几个文件和测试上下文需要一起看的情况。对于一眼就能定位原因的短报错，直接看 traceback 可能更快。

## 快速体验

需要 Python 3.11+ 和 Git：

```bash
git clone https://github.com/YGCYJA/opspilot.git
cd opspilot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

# 创建小型示例仓库，真实运行 pytest，保留成功与失败证据。
python scripts/reproduce_pytest_demo.py

# 只读取证据，不再次执行示例项目代码。
opspilot triage \
  --repo var/pytest_demo/project \
  --junit var/pytest_demo/junit.xml \
  --base HEAD \
  --notes var/pytest_demo/project/docs \
  --output var/pytest_demo/report
```

Windows 使用 `.venv\Scripts\activate` 激活环境。`dev` 安装项包含生成示例所需的 pytest。

示例将“满 100 减 10”的判断从 `>= 100` 人为改成 `> 100`，真实产生 **1 个失败、4 个通过** 的测试结果。示例仓库的 `HEAD` 保留修改前全部通过的版本。这是可重复构造的小例子，不代表外部系统的运行数据。

生成脚本不会覆盖已有的非空目录。重跑时可使用 `--output-dir var/pytest_demo_2`，并相应调整分析命令中的路径。

## 分析自己的项目

先在你自己的项目里运行测试，生成 JUnit XML：

```bash
cd /path/to/your/project
python -m pytest --junitxml=junit.xml
```

测试失败时命令通常返回非零退出码，仍会生成 XML。然后调用已安装的工具：

```bash
opspilot triage \
  --repo /path/to/your/project \
  --junit /path/to/your/project/junit.xml \
  --base HEAD~1 \
  --notes /path/to/your/project/docs \
  --output /path/to/your/project/var/triage
```

- `--repo`：待分析项目目录。
- `--junit`：本次 pytest 生成的 JUnit XML。
- `--base`：你选择的 Git 比较基线；`HEAD` 比较当前工作区和当前提交，`HEAD~1` 比较当前工作区和上一次提交。工具不会自动判断哪个提交曾经通过测试。
- `--notes`：可选的本地 Markdown 规则目录，须位于被分析仓库内；不传则不做规则检索。
- `--output`：报告输出目录，其中生成 `report.json` 和 `report.md`。

不传 `--base` 时省略 Git 比较。报告汇总测试数量，并展开 XML 顺序中的第一个失败或错误。它区分直接观察到的事实和需要进一步验证的解释，并保留证据引用。建议的命令需要你审核后手动运行，工具不会修改代码或自动执行测试。

## 本地网页

```bash
python -m uvicorn opspilot.api:app --host 127.0.0.1 --port 8000
```

打开 **http://127.0.0.1:8000** 使用本地表单，或打开 **http://127.0.0.1:8000/docs** 查看 API。输入路径指向运行 OpsPilot 的那台机器，而不是浏览器所在设备。[接口说明](docs/api.md)

下图为前述购物车回归示例生成的实际页面：

![购物车回归示例的本机分析报告](docs/images/pytest-report.png)

## 为什么保留 RAG 和可选模型

RAG 只解决“从本项目笔记里找相关规则”的小问题。失败断言、源码与 Git 改动直接读取，不需要先放进知识库。默认报告由确定性逻辑生成；可用 `--offline` 强制离线。可选模型用于组织解释，不能把推测变成已证实的根因。

引用校验能检查来源和原文，不能证明推理正确。配置方式与支持范围见[配置文档](docs/configuration.md)，实现边界见[架构文档](docs/architecture.md)。

## 验证与贡献

```bash
python -m pytest -q
python scripts/reproduce_pytest_demo.py --output-dir var/demo_check
opspilot triage --repo var/demo_check/project \
  --junit var/demo_check/junit.xml --base HEAD \
  --notes var/demo_check/project/docs --output var/demo_check/report
python -m pip install build
python -m build
```

测试检查 XML 解析、路径与 Git 输入、证据关联、报告输出以及模型失败处理。小型回归示例验证真实 pytest 结果能否进入报告，不用于声称通用的故障诊断准确率。[验证方法](docs/evaluation.md) · [贡献指南](CONTRIBUTING.md)

## 当前边界

面向本机小型 Python 项目的 pytest JUnit 输出。工具不连接 GitHub Actions、不自动克隆仓库、不监控服务、不自动修复代码，也不能证明根因。当前只展开第一个失败或错误。测试输出缺少路径或代码帧、动态导入、不同 XML 格式等情况，都可能导致源码关联不完整。源码以分析时磁盘上的内容为准；工具无法证明旧 XML 与当前代码来自同一次运行。

HTTP 服务没有认证，并能读取本机路径，应仅绑定 `127.0.0.1`，不适合直接公开部署。测试日志和源码可能含敏感内容，分享报告或启用外部模型前请检查。

代码及原创示例采用 [MIT](LICENSE) 许可；依赖与单独下载的模型保留各自许可。
