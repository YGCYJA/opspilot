"""Hand-authored small benchmark. Labels refer to document paths, never answer strings."""
import json
from pathlib import Path

DEV = [
    ("401接口认证失败如何检查", ["auth.md"]),
    ("429怎么做指数退避重试", ["rate_limit.md"]),
    ("SSE流式输出断开怎么处理", ["timeout.md"]),
    ("什么情况建议回滚版本", ["deployment.md"]),
    ("文档切分应该保留哪些来源信息", ["retrieval.md"]),
    ("缓存键怎么避免租户数据泄漏", ["cache.md"]),
    ("连接池耗尽需要检查什么", ["database.md"]),
    ("消息重复消费怎么保证幂等", ["queue.md"]),
    ("不同session_id会共享记忆吗", ["memory.md"]),
    ("HTTP错误率和服务端错误率有何区别", ["observability.md"]),
]
TEST = [
    ("API返回HTTP 401，Authorization头该怎样设置", ["auth.md"]),
    ("身份有效却403，换一把新密钥能解决吗", ["auth.md"]),
    ("密钥轮换时先撤销旧密钥还是先验证新密钥", ["auth.md"]),
    ("被限流后能不能一直立即重试", ["rate_limit.md"]),
    ("请求数没有用完为什么还会触发Token限制", ["rate_limit.md"]),
    ("网关HTTP 504需要检查哪些超时和队列指标", ["timeout.md"]),
    ("TTFT和总延迟有什么区别", ["timeout.md"]),
    ("新版本灰度应该先放多少流量观察多久", ["deployment.md"]),
    ("readiness和liveness探针用途是否相同", ["deployment.md"]),
    ("RRF为什么融合排名而非直接相加分数", ["retrieval.md"]),
    ("Recall@3与MRR分别衡量什么", ["retrieval.md"]),
    ("扫描PDF能直接作为本项目知识库输入吗", ["retrieval.md"]),
    ("知识库更新后缓存里的旧答案如何处理", ["cache.md"]),
    ("缓存命中率的分母是什么", ["cache.md"]),
    ("数据库连接池耗尽时直接扩大上限可以吗", ["database.md"]),
    ("数据库事务超时后重试有什么重复写入风险", ["database.md"]),
    ("消费者积压要观察哪些指标", ["queue.md"]),
    ("失败消息超过重试预算后放到哪里", ["queue.md"]),
    ("session_id可以当作身份认证凭据吗", ["memory.md"]),
    ("模型生成的对话摘要可以当可靠事实吗", ["memory.md"]),
    ("P95延迟用哪个排序位置计算", ["observability.md"]),
    ("没有供应商usage数据能说真实费用是零吗", ["billing.md"]),
    ("诊断orders-api发布后的连接池问题，需要哪些记录和检查", ["incident.md", "database.md"]),
    ("orders-api该不该回滚，请结合事件记录和回滚阈值判断", ["incident.md", "deployment.md"]),
]
UNKNOWN = ["明天广州会下雨吗", "公司今年营收多少亿元", "帮我写一首关于月亮的诗", "火星上有没有外星人", "推荐深圳最好吃的餐厅", "量子纠缠如何用于星际通信"]
TOOLS = [
    ("统计orders-api日志的HTTP错误率和P95延迟", "orders-api"),
    ("诊断auth-api的错误率与请求数", "auth-api"),
    ("orders-api固定日志里有多少请求和503响应", "orders-api"),
    ("查看auth-api日志的P95和服务端错误率", "auth-api"),
    ("结合知识库诊断orders-api的日志延迟", "orders-api"),
    ("统计auth-api日志里401响应的数量", "auth-api"),
]


def seed():
    rows = []
    for split, examples in (("dev", DEV), ("test", TEST)):
        for question, relevant in examples:
            rows.append({"id": f"{split}-retrieval-{len(rows):02}", "split": split, "kind": "retrieval", "question": question, "relevant_docs": relevant})
    for i, question in enumerate(UNKNOWN):
        rows.append({"id": f"test-unknown-{i}", "split": "test", "kind": "unknown", "question": question})
    for i, (question, service) in enumerate(TOOLS):
        rows.append({"id": f"test-tool-{i}", "split": "test", "kind": "tool", "question": question, "service": service})
    target = Path(__file__).resolve().parents[1] / "data" / "eval.jsonl"
    target.parent.mkdir(exist_ok=True)
    target.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} benchmark cases")


if __name__ == "__main__":
    seed()
