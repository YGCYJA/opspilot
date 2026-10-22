# OpsPilot

OpsPilot 是一个可本地运行、能够检查执行过程的故障分析助手。它从 Markdown 知识库检索资料，调用只读工具统计日志，并在回答中附带证据引用。支持命令行、FastAPI、离线规则流程，以及可选的本地模型和 HTTP 模型接口。

[English README](README.md) · [架构](docs/architecture.md) · [配置](docs/configuration.md) · [API](docs/api.md) · [评测](docs/evaluation.md) · [故障实验](docs/fault-lab.md)

## 快速运行

需要 Python 3.11+，默认模式不需要显卡、模型权重或 API Key。

```bash
git clone https://github.com/YGCYJA/opspilot.git
cd opspilot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

opspilot ask '统计 orders-api 的请求数、错误率和 P95 延迟' --json
opspilot ask 'HTTP 401 应该如何排查？'
python -m uvicorn opspilot.api:app --host 127.0.0.1 --port 8000
```

浏览器打开 http://127.0.0.1:8000/docs 可以直接调用接口。Windows 使用 `.venv\Scripts\activate` 激活环境。

## 功能与数据

- Markdown 按标题和长度切分，保留文件名、行号和基于内容的引用 ID。
- 提供 BM25、字符 TF-IDF、两者的 RRF 融合，以及可选的本地向量检索。
- 统计 CSV 中的请求数、HTTP 错误率、服务端错误率和最近秩 P95，支持带时区的 `[start,end)` 时间范围。
- 使用固定 LangGraph 流程执行规划、工具调用、回答和引用校验，最多调用 3 次白名单工具。
- 在 SQLite 中保存执行记录，包含证据、规划、延迟、模型用量及降级原因。
- 提供检索对比评测和真实本机 HTTP 故障注入实验。

内置知识库描述虚构的 `orders-api` 和 `auth-api`。`data/logs.csv` 是合成夹具；故障实验产生的日志来自真实本机请求，并标记为 `local_fault_injection`。两者都不代表生产服务指标。

默认 `orders-api` 夹具为 100 个请求、HTTP 错误率 0.2、服务端错误率 0.1、P95 为 1980.0 ms。空窗口的错误率与 P95 为 `null`，不能解释为健康。未指定服务的统计问题会请求澄清。

## 使用自己的资料

```bash
cp -R data my-data
export OPS_DATA_DIR="$PWD/my-data"
export OPS_STATE_DIR="$PWD/var"
opspilot ingest
opspilot ask 'HTTP 429 应该如何处理？'
```

修改 `my-data/knowledge/` 下的 Markdown 即可；应用启动时重新建立内存索引。`ingest` 用于导出可检查的 JSON 索引，应用不会自动读取该导出文件。安装包包含默认数据，离开源码目录也可以运行。

环境变量、日志 CSV 格式和本地 Qwen3/BGE 模型安装步骤见[配置文档](docs/configuration.md)。`.env.example` 只作配置示例，程序不会自动加载 `.env`。

## 验证

```bash
python -m pytest -q
opspilot eval --split test --output reports/generated
python scripts/run_fault_lab.py --requests-per-scenario 5
python scripts/verify_fault_integration.py --output reports/generated/fault_lab
```

测试集有 24 条检索问题、6 条工具问题和 6 条未知问题，另有 10 条开发案例。样本较小且为人工编写，不能据此推断真实业务表现。真实模型验收与离线流程评测分开运行。

返回结果中 `status` 表示已回答、拒答或需要澄清；`mode=offline_fallback` 表示模型失败后发生规则降级。引用校验只验证来源 ID 和逐字原文，不能证明结论在语义上正确。内置意图识别、服务名和日志类型均有明确范围；本地小模型仍为实验功能。

完整目录和 Docker 用法见 [README](README.md)。API 没有内置认证，默认仅绑定回环地址；对外部署前需自行增加认证与访问控制。代码及内置原创夹具采用 [MIT](LICENSE) 许可；外部模型及依赖保留各自许可。
