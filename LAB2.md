# 实验 2 记录：第 13 组

评分时依据本文件和 `runs/` 中的原始数据核对。本文件中的每一个数值，都须能在某个 `runs/<名字>/` 的文件中找到：表格用 `scripts/table.sh` 生成后粘贴，其他数值注明出处（例如“`runs/r1-pool4/red.csv` 第 6 阶段”）。不要只贴截图。将 `<填写>` 替换为本组的内容。

第 4.1、4.4、5.1、5.3 节的预测须在对应的测量之前写好，写好后不要修改。预测错误不扣分，与实测不一致之处在分析中讨论。

## 1. 基本信息

| 项 | 内容 |
|---|---|
| 小组 | 第 13 组 |
| 仓库地址 | <https://github.com/SS80194/ops-lab2-13> |
| 主机 | 华为云 ECS（KVM 虚拟化）；来宾系统可见 2 vCPU、1771 MiB 内存；控制台规格名未查询 |
| CPU | General Purpose Processor；2 vCPU；`lscpu -e` 中 CPU 0、1 均对应 CORE 0（同一物理核的两个超线程，虚拟机暴露的拓扑） |
| 内存 | `free -m` total 1771 MiB，无 swap |
| 数据目录所在的盘 | `/dev/vda1`，ext4，整盘 `vda` 40 GiB，挂在 `/`；`data/` 在真实块设备上（非 tmpfs）；云盘产品类型未查询 |
| 操作系统与内核 | Ubuntu 22.04.5 LTS；5.15.0-186-generic |
| Go、Prometheus、node_exporter | go1.26.10 linux/amd64；Prometheus 3.13.4；node_exporter 1.12.1 |
| 分核 | enrolld：CPU 1；loadgen、Prometheus、node_exporter：CPU 0 |

以上环境信息的原始输出见 `runs/t0-baseline/host.txt`（任务 0 采集）和 `runs/t1-light/environment.txt`、`meta.txt`。两逻辑 CPU 共享同一 CORE，分核后仍可能有物理资源干扰。小组编号取自仓库名 `ops-lab2-13`。

## 2. 任务 0：基线

`bin/enrolld -bench-fsync 2000` 连续运行三次的输出（原始输出见 `runs/t0-baseline/fsync-3x.txt`）：

```text
### run 1  2026-10-29 13:34:49
fsync 次数 2000，总耗时 2.35 s，数据目录 data
fsync 耗时（毫秒）：mean 1.169  p50 1.102  p90 1.364  p99 2.188  max 6.249
按平均值推算，一个写者串行 fsync 每秒最多约 855 次（= 1000 / 1.169）

### run 2  2026-10-29 13:34:52
fsync 次数 2000，总耗时 2.33 s，数据目录 data
fsync 耗时（毫秒）：mean 1.161  p50 1.085  p90 1.309  p99 2.522  max 6.846
按平均值推算，一个写者串行 fsync 每秒最多约 861 次（= 1000 / 1.161）

### run 3  2026-10-29 13:34:54
fsync 次数 2000，总耗时 2.36 s，数据目录 data
fsync 耗时（毫秒）：mean 1.173  p50 1.081  p90 1.391  p99 2.794  max 4.907
按平均值推算，一个写者串行 fsync 每秒最多约 853 次（= 1000 / 1.173）
```

按平均值计算，单个写者串行 fsync 每秒最多约 **856** 次（三次 mean 1.169、1.161、1.173 ms，平均 1.168 ms，1000 ÷ 1.168 ≈ 856）。三次之间相差多少？三次平均耗时相差不到 0.012 ms（约 1%）；p99 在 2.188～2.794 ms 之间，max 在 4.907～6.846 ms 之间，单次抖动来自云盘与宿主机，平均值稳定。

空载和运行 fsync 测试时各工具的读数（各观察 5 秒以上，取典型值；空载观察 12 s、负载段为 `bin/enrolld -bench-fsync 5000` 的 5.8 s，均为 1 s 采样的中位数，原始输出见 `runs/t0-baseline/vmstat.log`、`runs/t0-baseline/iostat.log`、`runs/t0-baseline/summary.json`）：

| 工具与列 | 空载 | 运行 `-bench-fsync` 时 | 该列的含义 |
|---|---|---|---|
| `vmstat -w 1`：r、b | r=0，b=0 | r=0，b=1 | r：可运行队列中的进程数；b：阻塞在不可中断睡眠（多为等 I/O）的进程数 |
| `vmstat -w 1`：us、sy、id、wa、st | us=1，sy=1，id=99，wa=0，st=0 | us=0，sy=3，id=50，wa=47，st=0 | 用户态、内核态、空闲、等 I/O、被宿主机占走的 CPU 时间百分比 |
| `iostat -dx 1 vda`：w/s、wkB/s | 0、0 | 2559、13984 | 每秒写请求数、每秒写入的 KiB |
| `iostat -dx 1 vda`：w_await、f/s、f_await | 0、0、0 | 0.38、1698、0.03 | 写请求的平均等待+服务时间（ms）；每秒 flush 次数；flush 的平均耗时（ms） |
| `iostat -dx 1 vda`：aqu-sz、%util | 0、0 | 1.02、100 | 平均队列长度（请求数）；设备忙碌时间占比 |

运行 fsync 测试时，CPU 是否繁忙？哪几列表明存在等待？CPU 不繁忙：`us` 为 0、`sy` 为 3、`id` 为 50，约一半时间空闲。等待体现在 `vmstat` 的 `b=1`（有进程阻塞在不可中断睡眠）和 `wa=47`（近一半 CPU 时间在等 I/O），以及 `iostat` 的 `aqu-sz≈1.02`、`%util=100`。按块层计数，每次 fsync 约对应 3 次写（2559 ÷ 863 ≈ 3.0）和 2 次 flush（1698 ÷ 863 ≈ 2.0）；应用量到的 fsync 平均 1.158 ms 远大于块层 `w_await` 0.38 ms，差额是提交日志与设备缓存刷新必须等待的时间。863 次/秒 × 1.158 ms ≈ 100%，与 `%util=100` 一致：串行 fsync 已经把这块盘的写通道占满，而 CPU 仍未饱和。

## 3. 任务 1：指标流水线

两个抓取目标的状态：`enrolld=up`、`node=up`，`lastError` 均为空。原始 API 响应见 `runs/t1-light/targets.json`；测试区间每 5 秒查询 `up`，两个目标各 18 个采样点全部为 1（`runs/t1-light/up-range.json`）。

本组编写的四条查询（与 `deploy/queries-red.txt` 一致）：

```text
server_rps          sum(rate(http_requests_total{route="${route}"}[${window}]))
server_error_rate   (sum(rate(http_requests_total{route="${route}",code=~"5.."}[${window}])) or vector(0)) / sum(rate(http_requests_total{route="${route}"}[${window}]))
server_p99_ms       1000 * histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{route="${route}"}[${window}])))
server_slo_good     (sum(rate(http_request_duration_seconds_bucket{route="${route}",code="200",le="${slo}"}[${window}])) or vector(0)) / sum(rate(http_requests_total{route="${route}"}[${window}]))
```

`runs/t1-light` 的数据（`scripts/table.sh runs/t1-light ok_rps mean_ms p99_ms server_rps server_mean_ms server_p99_ms cpu_ms_per_req db_query_mean_ms`）：

| step | target_rps | ok_rps | mean_ms | p99_ms | server_rps | server_mean_ms | server_p99_ms | cpu_ms_per_req | db_query_mean_ms |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0 | 0.0 | - | - | - | - | - | - | NaN |
| 2 | 50 | 50.5 | 11.48 | 12.91 | 51.5833 | 10.7481 | 19.9 | 0.553748 | 10.3004 |
| 3 | 100 | 97.8 | 11.60 | 14.57 | 95.4167 | 10.9031 | 19.9043 | 0.533471 | 10.4232 |
| all | - | 74.2 | 11.56 | 14.12 | - | - | - | - | - |

从这次实验读出：每次查询实际占用连接 **10.4232 ms**；每个请求消耗的 CPU **0.533471 ms**。均取 `runs/t1-light/red.csv` 第 3 阶段（目标 100 请求/秒）的 `db_query_mean_ms`、`cpu_ms_per_req`。50 请求/秒阶段的连接占用为 10.3004 ms。


本次运行于 **2026-10-29 13:26:11–13:27:41（UTC+8）**，执行：

```bash
GEN_CPUS=0 scripts/run.sh t1-light -url http://127.0.0.1:8080/api/courses/1 -rates 0,50,100 -step 30s
```

服务参数为 `-work 200000 -pool 4 -db-ms 10 -sync each`，详见 `meta.txt`。验收结果：

- `steps.csv` 共 4451 个请求全部成功；HTTP 错误、超时、网络错误、丢请求均为 0，无压测器警告。
- `metrics-end.txt` 相比 `metrics-start.txt` 的读接口请求计数增量也是 4451，与客户端完全一致。
- 两个有效负载阶段四条新查询均返回有限数值，5xx 比例为 0，服务端 50 ms SLI 为 1。
- 第 3 阶段客户端实际吞吐 97.8 请求/秒，p99 14.57 ms；服务端吞吐 95.4167 请求/秒，p99 19.9043 ms。到达过程随机，客户端统计完整 30 秒，Prometheus 查询后 25 秒；服务端 p99 使用直方图桶插值，因此不能要求逐值相等。
- 第 3 阶段服务 CPU 忙碌比例 0.052（5.2%），最少可用内存 1124.47 MiB（`use.csv`），没有达到资源饱和。
- `vmstat.log`、`mpstat.log`、`iostat.log`、`pidstat.log` 均有连续原始输出。自动核对结果见 `validation.json`、`validation.log`；核对脚本是 `verify.py`。
- 空载没有请求时比率/延迟为空或 NaN；纯读测试的 fsync 平均耗时等为 NaN，属于没有对应事件，不是采集失败。

启动、SSH 隧道访问、复测和停止命令见 `docs/task1-operations.md`。本 PR 完成任务 1；任务 0 基线已由主分支补齐，任务 2 以后的预测、实验与结论保留待完成。

## 4. 任务 2：读路径

### 4.1 预测（R1 之前写）

| 资源 | 容量 | 每个请求占用（数据来源） | 推算的上限（请求/秒） |
|---|---|---|---|
| 连接池 | 4 个连接 | 10.4232 ms（`runs/t1-light/red.csv` 第 3 阶段 `db_query_mean_ms`） | 4 ÷ 0.0104232 ≈ 384 |
| CPU | enrolld 的 1 个核 | 0.533471 ms（`runs/t1-light/red.csv` 第 3 阶段 `cpu_ms_per_req`） | 1 ÷ 0.000533471 ≈ 1875 |

先达到上限的是：**连接池**。预计从约 **345 请求/秒**（约为连接池上限的 0.9 倍）起，客户端 p99 超过 50 ms，理由：此时池平均已有 3.5 个连接同时被占用，泊松到达的尾部会让排队时间迅速变长；此时连接池是唯一接近饱和的资源，CPU 上限约 1875 请求/秒，远未触及。

R1 的到达率（`scripts/rates.sh 384` 的输出）：`77,154,230,269,307,346,384,422,461`

### 4.2 R1：`-pool 4`

`scripts/table.sh runs/r1-pool4 ok_rps error_rate p99_ms server_p99_ms server_mean_ms inflight_avg cpu_ms_per_req pool_in_use_avg pool_wait_p99_ms sched_wait_p99_ms svc_cpu_busy procs_running_avg`：

| step | target_rps | ok_rps | error_rate | p99_ms | server_p99_ms | server_mean_ms | inflight_avg | cpu_ms_per_req | pool_in_use_avg | pool_wait_p99_ms | sched_wait_p99_ms | svc_cpu_busy | procs_running_avg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 77 | 79.0 | 0.0000 | 13.39 | 19.9 | 10.8324 | 1.36 | 0.539024 | 1.36 | 1.09 | 0.745 | 0.053 | 1.6 |
| 2 | 154 | 152.8 | 0.0000 | 18.09 | 19.9296 | 11.2142 | 1.64 | 0.529353 | 1.48 | 7.62302 | 0.824938 | 0.0865 | 1.8 |
| 3 | 230 | 229.8 | 0.0000 | 22.86 | 33.6604 | 12.0121 | 2.64 | 0.518391 | 2.52 | 13.1081 | 0.784211 | 0.122 | 3 |
| 4 | 269 | 273.9 | 0.0000 | 31.85 | 47.1302 | 13.8724 | 3.04 | 0.514871 | 2.72 | 25.6341 | 0.774353 | 0.141 | 2.2 |
| 5 | 307 | 311.1 | 0.0000 | 46.50 | 49.3282 | 16.3839 | 6.16 | 0.513574 | 3.76 | 45.0195 | 0.838508 | 0.163 | 2.4 |
| 6 | 346 | 342.4 | 0.0000 | 60.92 | 86.1393 | 21.9644 | 8.04 | 0.50419 | 3.68 | 53.5899 | 0.770833 | 0.168 | 2.8 |
| 7 | 384 | 384.7 | 0.0051 | 1007.24 | 1091.11 | 538.351 | 208.48 | 0.508842 | 4 | 992.772 | 0.779655 | 0.1925 | 2.8 |
| 8 | 422 | 374.4 | 0.1032 | 1011.83 | 1982.26 | 997.748 | 414.64 | 0.489147 | 4 | 1903.03 | 0.839267 | 0.2055 | 3.2 |
| 9 | 461 | 376.5 | 0.1868 | 1012.07 | 1987.03 | 1002.26 | 462.76 | 0.489674 | 4 | 1947.97 | 0.833115 | 0.2195 | 3 |
| all | - | 280.5 | 0.0495 | 1011.31 | - | - | - | - | - | - | - | - | - |

最大吞吐量 **384.7 请求/秒**，出现在第 **7** 阶段（目标 384 请求/秒）；客户端 p99 首次超过 50 ms 是在第 **6** 阶段（**346** 请求/秒，p99 = 60.92 ms），与 4.1 预测的 345 请求/秒基本一致。

从第 7 阶段起：`pool_in_use_avg` 达到 4（4 个连接全部在用，池满）、`pool_wait_p99_ms` 从 53.59 ms 跳到 992.77 ms，而 `svc_cpu_busy` 只有 0.1925（约 19%）。说明限制吞吐的是**连接池**，不是 CPU。第 8、9 阶段即使把目标提高到 422、461 请求/秒，成功吞吐反而降到 374.4、376.5，`error_rate` 为 10.32%、18.68%，原因是等连接时间超过 `-pool-timeout`（1 s）后返回 503。

### 4.3 CPU 消耗在何处

在约 0.8 倍上限的负载（`runs/r1-pprof`，目标 307 请求/秒）下采集 20 秒 CPU 剖析，`go tool pprof -top` 的前 10 行（同时保存在 `runs/r1-pprof/pprof-top.txt`）：

```text
File: enrolld
Build ID: 0bde9eed8a74b4c2cdb1dadfda8dae01951b8d07
Type: cpu
Time: 2026-10-29 16:23:56 CST
Duration: 20s, Total samples = 2.57s (12.85%)
Showing nodes accounting for 2.47s, 96.11% of 2.57s total
Dropped 37 nodes (cum <= 0.01s)
      flat  flat%   sum%        cum   cum%
     2.33s 90.66% 90.66%      2.33s 90.66%  main.spin (inline)
     0.11s  4.28% 94.94%      0.11s  4.28%  internal/runtime/syscall/linux.Syscall6
```

`main.spin` 占 **90.66%**；本次该阶段吞吐 305.44 请求/秒，`cpu_ms_per_req` 为 0.514584 ms（`runs/r1-pprof/red.csv`），所以每个请求约 **0.515 ms**，其中 spin 约 **0.467 ms**，其余约 **0.048 ms** 消耗在：系统调用 4.28%（约 0.022 ms，主要是 epoll 等待和 accept/read/write）、网络读与写各约 0.39%，剩下的约 3.9% 落在 `-top` 折叠掉的小节点里（内存分配、GC、调度、JSON 编解码等）。

### 4.4 R2：调大连接池（预测在 R2 之前写）

| 项 | 值与算法 |
|---|---|
| 每个请求占用的 CPU（取 R1 哪一阶段的 `cpu_ms_per_req`，选取理由） | 0.513574 ms，取 R1 第 5 阶段（307 请求/秒，约 0.8 倍上限）：此时连接池尚未饱和、没有 503，CPU 采样稳定，且与 4.3 抓 pprof 的负载相同，便于对照 |
| 推算的 CPU 上限 C | 1 ÷ 0.000513574 ≈ **1947 请求/秒** |
| R2 的池大小 P2 = ceil(2 × C × 每次查询的秒数) | ceil(2 × 1947 × 0.0104232) = ceil(40.6) = **41** |
| R2 的到达率（`scripts/rates.sh C 0.3 0.6 0.8 0.9 1.0 1.1 1.25 1.5`） | `584,1168,1558,1752,1947,2142,2434,2921` |
| 预测：R2 中先达到上限的是 | **CPU**：池大小为 41 时连接池上限约 41 ÷ 0.0104232 ≈ 3934 请求/秒，远高于 C ≈ 1947 |

`scripts/table.sh runs/r2-pool41 ok_rps error_rate p99_ms server_p99_ms inflight_avg cpu_cores cpu_ms_per_req cpu_wait_threads sched_wait_p99_ms pool_in_use_avg svc_cpu_busy procs_running_avg cpu_psi_some`：

| step | target_rps | ok_rps | error_rate | p99_ms | server_p99_ms | inflight_avg | cpu_cores | cpu_ms_per_req | cpu_wait_threads | sched_wait_p99_ms | pool_in_use_avg | svc_cpu_busy | procs_running_avg | cpu_psi_some |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 584 | 585.0 | 0.0000 | 13.38 | 19.9 | 6.88 | 0.278258 | 0.476809 | 0.0177799 | 0.814181 | 6.88 | 0.28 | 3.2 | 0.024076 |
| 2 | 1168 | 1175.1 | 0.0000 | 13.98 | 19.9 | 13.28 | 0.502257 | 0.428638 | 0.0122138 | 1.20651 | 13.28 | 0.4945 | 3 | 0.0186754 |
| 3 | 1558 | 1553.8 | 0.0000 | 14.51 | 19.9 | 16.08 | 0.645874 | 0.415866 | 0.00721897 | 1.86345 | 16.08 | 0.653 | 2.8 | 0.0129966 |
| 4 | 1752 | 1746.8 | 0.0000 | 15.77 | 19.9014 | 18.52 | 0.723164 | 0.414381 | 0.00568983 | 2.99042 | 18.52 | 0.724 | 3.4 | 0.0125847 |
| 5 | 1947 | 1943.5 | 0.0000 | 17.35 | 19.9 | 20.64 | 0.797066 | 0.410656 | 0.0045486 | 4.01206 | 20.64 | 0.7955 | 3.2 | 0.0098178 |
| 6 | 2142 | 2135.7 | 0.0000 | 21.19 | 19.901 | 23.08 | 0.876087 | 0.410193 | 0.00371376 | 5.19596 | 23.08 | 0.877 | 3.8 | 0.0106922 |
| 7 | 2434 | 2444.6 | 0.0000 | 124.67 | 19.922 | 24.88 | 0.988454 | 0.404883 | 0.00180678 | 49.9821 | 24.88 | 0.9885 | 4 | 0.0086932 |
| 8 | 2921 | 420.2 | 0.8561 | 1993.00 | 1929.99 | 400.25 | 0.995776 | 0.40651 | 0.0115105 | 1000 | 33.875 | 1 | 4.4 | 0.0160402 |
| all | - | 1500.6 | 0.1724 | 1461.85 | - | - | - | - | - | - | - | - | - | - |

最大吞吐量 **2444.6 请求/秒**（第 7 阶段，目标 2434），此时 `svc_cpu_busy` 已达到 0.9885、`cpu_cores` 0.988，`pool_in_use_avg` 只有 24.88（池大小 41），`pool_wait_p99_ms` 仍为 0.99 ms，说明**先饱和的是 CPU，连接池还没满**，与预测一致；再往上加到达率（第 8 阶段 2921）只会堆出 400 个在途请求、`sched_wait_p99_ms` 1000 ms，成功吞吐塌到 420.2，`error_rate` 85.61%。

与预测的 C = 1947 相差 **+497.6（+25.6%）**。原因：`cpu_ms_per_req` 并不是常数，它随负载升高而下降（R1 从 0.539 降到 0.489，R2 从 0.477 降到 0.405）。4.4 的 C 用的是 0.8 倍池上限（307 请求/秒）那一级的 0.5136 ms，包含了较空的 CPU 缓存；到 2444 请求/秒时循环代码和数据一直在缓存里，每个请求实测只要 0.4049 ms。用这个实测值重算：1 ÷ 0.000404883 ≈ **2470 请求/秒**，与实测最大吞吐 2444.6 只差 1.0%。这也说明 C 的公式本身没问题，误差来自“每请求 CPU 随负载变化”这个假设。

## 5. 任务 3：写路径

### 5.1 预测：`-sync each`（W1 之前写）

| 项 | 值与算法 |
|---|---|
| fsync 平均耗时（任务 0） | <填写> ms |
| 推算的最大 TPS | <填写> |
| 达到上限时 enrolld 大约使用几个核（写路径没有 spin，按 4.3 节拆分出的“spin 以外的开销”估计每个写请求的 CPU） | <填写> |
| W1 的到达率（`scripts/rates.sh <最大 TPS> 0.2 0.4 0.6 0.8 0.9 1.0 1.1 1.2`） | <填写> |

### 5.2 W1：`-sync each`

`scripts/table.sh runs/w1-<…> ok_rps error_rate p99_ms server_p99_ms cpu_cores fsync_per_s fsync_mean_ms batch_mean svc_cpu_busy cpu_iowait disk_w_per_s disk_w_await_ms disk_f_per_s disk_f_await_ms disk_aqu_sz disk_util`：

<粘贴表格>

### 5.3 预测：`-sync group`（W2 之前写）

在 W1 达到上限时的到达率下，改为组提交后：吞吐量 <填写>；平均每次 fsync 处理 <填写> 条记录；客户端 p99 约 <填写>。理由：<填写>

W2 的到达率：<填写>

### 5.4 W2：`-sync group`

（列与 5.2 相同）

<粘贴表格>

### 5.5 W3：`-sync interval`

（列与 5.2 相同）

<粘贴表格>

## 6. 分析问题

每题先列出所用数据（引用上面的表或 `runs/` 中的文件），再写结论，并说明结论的成立条件。每题 300～600 字。

**问题 1：上限由什么决定。** 按 L-07 第 25 页资源账的格式，为 enrolld 的读路径编制一份资源账：资源、每个请求占用（实测）、容量、推算的上限、实测的最大吞吐量、饱和观测项。预测与实测相差多少，差异来自何处？`cpu_ms_per_req` 随负载如何变化，原因是什么？这对“在低负载下测量每请求开销，再推算上限”的做法意味着什么？`db_query_mean_ms` 为什么大于 `-db-ms`？以“p99 ≤ 50 ms”为目标，R1 能承受的最大阶段相当于上限的多少比例？与 L-07 第 6 页“容量 = 上限 × 0.7”比较，为什么尚未达到上限延迟就已上升？R2 调大连接池后，瓶颈转移到了哪个资源？

<填写>

**问题 2：利用率不等于饱和。** R1 达到上限时，enrolld 所在核的 CPU 利用率是多少？哪个数值最先表明资源已经饱和？R2 中 CPU 利用率接近 100% 时，内核层的 `procs_running_avg`、`cpu_psi_some`、`cpu_wait_threads` 和 Go 运行时层的 `sched_wait_p99_ms` 分别如何变化？为什么内核层几乎观察不到排队，排队发生在哪里？这与 L-06 第 16、17 页 Tomcat 的线程池有何相同之处？最后用 Little's Law 核对：从 R1 选取三个阶段，用 `server_rps × server_mean_ms` 计算在途请求数，并与 `inflight_avg` 比较；W 为什么必须用平均值而不能用 p99？哪个阶段不一致，原因是什么？

<填写>

**问题 3：持久性以延迟为代价。** W1 实测的最大 TPS 与 1000 ÷ fsync 平均耗时相比如何？W1 达到上限时 CPU、内存、磁盘的指标各是多少，哪几列表明磁盘饱和？应用测得的 `fsync_mean_ms` 与 `disk_w_await_ms`、`disk_f_await_ms` 为什么不同？一次 fsync 大约对应几次写和几次 flush？W1 与 W2 在 `disk_util` 相近时吞吐量相差多少，`%util` 接近 100% 能否说明磁盘已经饱和？组提交的 `batch_mean` 如何随负载变化，低负载时是否有收益，本组的预测是否正确？W3 快了多少，代价是什么？选课记录应采用哪一种方式，在什么条件下 interval 可以接受？

<填写>

**问题 4：延迟数值的测量位置与方法。** 同一阶段中，客户端与服务端的平均值、p99 各相差多少？列出只计入客户端的时间组成。找出一个服务端 p99 大于客户端 p99 的阶段，并解释原因（L-08 第 10 页）。比较服务端的 `server_slo_good` 与客户端的 `slo_good`；若存在过载阶段，二者为何相差很大？SLI 应在何处测量（L-08 第 19 页）？用 R1 的 `steps.csv`，将各阶段的 p99 求平均，与 `all` 行的 p99 比较，说明百分位数为什么不能平均，以及正确的合并方法。最后计算错误预算：SLO 为“30 天内 99% 的读请求在 50 ms 内成功返回”，若 R1 中第一个不达标阶段的负载持续下去，燃烧率是多少，30 天的预算多久耗尽（L-08 第 21 页）？

<填写>

## 7. 选做记录

| 选做 | 完成情况与证据 |
|---|---|
| O1 内存与 GC | <未做 / 预测、`runs/` 目录、结论> |
| O2 网络 | <未做 / 两台主机的规格与拓扑、`runs/` 或日志、结论> |
| O3 告警与看板 | <未做 / 规则文件、触发记录、看板说明> |
| O4 迁移到小组项目 | <未做 / 仓库链接、测了哪个资源、结论> |

## 8. 成员分工

每位成员一行，只填写 GitHub 用户名，无需填写姓名；行数应与小组人数一致。

| GitHub 用户名 | 负责的部分 |
|---|---|
| <用户名> | <填写> |
