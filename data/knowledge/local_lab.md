# 本地受控故障注入实验说明
## 实验来源与边界
本知识条目描述 OpsPilot 本地实验，不是企业生产事故或公司内部手册。日志 data_kind=local_fault_injection。服务 orders-api 在 127.0.0.1 运行，由真实 HTTP 请求产生状态码和时间测量，实验结束关闭。
## 场景与排查依据
normal 正常返回 HTTP 200。slow 人为增加约 50ms 处理等待，延迟应使用日志的实测值。rate_limit 人为返回 HTTP 429；unavailable 人为返回 HTTP 503。它们验证统计和引用链路，不代表真实限流策略或真实上游故障。
## 客户端超时和服务端状态
timeout 场景人为等待约 80ms，客户端读取期限约 30ms。客户端可能先超时，服务端仍完成 HTTP 200。检查 client_observations.json 与 logs.csv 的同一 request_id，不能把客户端超时写成服务端 HTTP 504，也不能据此断言真实故障根因。
## 时间窗口和复现
运行 scripts/run_fault_lab.py 生成独立 run_id 目录，summary.json 提供每个场景实际 start_time 和 end_time。日志 timestamp 是服务器收到请求的 UTC 时间，latency_ms 是服务器用单调时钟测量的处理时长；它不是端到端网络延迟。
