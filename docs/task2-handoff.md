# 任务 2 交接（3 号 → 4 号）

任务 2（读路径）已完成，`LAB2.md` 第 4 节 4.1–4.4 全部填写，原始数据在下面三个目录。本文只列 4 号写任务 3 时需要用到的东西。

## 一、结论数字

| 项 | 值 | 出处 |
|---|---|---|
| 每次查询占用连接 | 10.4232 ms | `runs/t1-light/red.csv` 第 3 阶段 |
| 连接池上限（`-pool 4`） | 4 ÷ 0.0104232 ≈ 384 请求/秒 | 4.1 |
| R1 实测最大成功吞吐 | 384.7 请求/秒（第 7 阶段） | `runs/r1-pool4/steps.csv` |
| R1 客户端 p99 首次 > 50 ms | 第 6 阶段，346 请求/秒（60.92 ms） | `runs/r1-pool4/steps.csv` |
| R1 饱和资源 | **连接池**（`pool_in_use_avg`=4、`pool_wait_p99`≈993 ms、CPU 仅 19%） | `runs/r1-pool4/red.csv`、`use.csv` |
| CPU 剖析 | `main.spin` 占 90.66%，每请求 0.515 ms（spin 0.467 + 其余 0.048） | `runs/r1-pprof/pprof-top.txt`、`red.csv` |
| CPU 上限 C（写路径预测时参考） | 1947 请求/秒（用 0.8 倍负载下的 0.5136 ms 算） | 4.4 |
| P2 | 41 | 4.4 |
| R2 实测最大成功吞吐 | 2444.6 请求/秒（第 7 阶段），CPU 饱和（0.9885） | `runs/r2-pool41/steps.csv` |
| R2 与 C 的偏差 | +25.6%；用实测 0.4049 ms 重算 C'=2470，差 1.0% | 4.4 |

## 二、写路径要用到的唯一一条衍生数据

4.3 拆出：**spin 以外的每请求 CPU ≈ 0.048 ms**（307 请求/秒、`cpu_ms_per_req` 0.514584 ms 时测得）。

写路径没有 `spin`，每个写请求的 CPU 建议按 **0.05 ms** 量级估计（含 HTTP、JSON、加锁、fsync 调用）。5.1 里“达到上限时 enrolld 用几个核”= 最大 TPS × 0.05 ms ÷ 1000。

注意两条：
- 这个值是在中等负载下测的；读路径数据表明每请求 CPU 会随负载升高而下降（0.515 → 0.405），所以 0.05 ms 偏保守，写路径饱和时的实际值可能更低。
- 不要直接拿 0.5136 ms 当写路径的每请求 CPU，那是含 spin 的读路径数字。

## 三、当前服务状态（重要）

任务 2 结束后已把 enrolld **恢复成基线参数**：

```
-pool 4 -work 200000 -db-ms 10 -sync each
```

R2 期间曾经用 `-pool 41` 跑过，别被 `runs/r2-pool41/meta.txt` 里的 `/config` 弄混。写路径开始前按 5.1 需要重启成 `-sync each`（W1）、`-sync group`（W2）等，重启命令见 `docs/task1-operations.md`。

## 四、可以复现的命令

```bash
cd /opt/ops-lab2-13
# R1
GEN_CPUS=0 SLO=0.05 scripts/run.sh r1-pool4 -url http://127.0.0.1:8080/api/courses/1 \
  -rates 77,154,230,269,307,346,384,422,461 -step 30s
# pprof
GEN_CPUS=0 scripts/run.sh r1-pprof -url http://127.0.0.1:8080/api/courses/1 -rates 307 -step 40s
# 另一窗口，负载起来后
curl -fsS "http://127.0.0.1:8080/debug/pprof/profile?seconds=20" -o /tmp/cpu-08.pprof
go tool pprof -top bin/enrolld /tmp/cpu-08.pprof
# R2（需先把 enrolld 重启成 -pool 41）
GEN_CPUS=0 SLO=0.05 scripts/run.sh r2-pool41 -url http://127.0.0.1:8080/api/courses/1 \
  -rates 584,1168,1558,1752,1947,2142,2434,2921 -step 30s
```

## 五、注意事项

- Prometheus 数据在 `/dev/shm`，保留 24 小时；过期后 `requery.sh` 无法补查，必须在 24 小时内提交。
- `run.sh` 不覆盖同名目录；复测请换名字。
- 读路径结论要能回答：为什么 `-pool 4` 时 p99 在 346 请求/秒就超过 50 ms（池排队），以及为什么加到 422、461 反而掉吞吐（等连接超过 1 s 的 `-pool-timeout` 返回 503）。
