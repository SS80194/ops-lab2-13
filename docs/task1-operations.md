# 任务 1：部署与复现

本次只完成监控启动、四条 RED/SLI 查询和低负载采集验收。实测数据见 `LAB2.md` 第 3 节和 `runs/t1-light/`；后续饱和实验及其预测未执行、未填写。

## 已部署环境

- 华为云 Ubuntu 22.04.5 LTS；项目目录 `/opt/ops-lab2-13`。
- Go 1.26.10 位于 `/opt/ops-lab2-go1.26.10/go`；工具链压缩包使用 go.dev 发布的 SHA256 校验。
- Prometheus 3.13.4、node_exporter 1.12.1 位于项目的 `tools/`，通过 `scripts/get-tools.sh` 的固定 SHA256 校验。
- 已安装 `sysstat`，提供 `mpstat`、`iostat`、`pidstat`；构建、原有测试、vet、格式检查均通过。
- 2 个 vCPU；`lscpu -e` 显示二者属于同一 CORE，逻辑 CPU 分离不能消除物理核共享造成的干扰。
- enrolld 绑定 CPU 1，Prometheus、node_exporter、loadgen 绑定 CPU 0。

## 启动命令

下面命令在云主机上以 root 执行。当前三个服务已经启动，不应在同名服务运行时重复执行。它们由 systemd 托管，SSH 断开后继续运行；使用的是临时 unit，不设置开机自启。重启主机后须重新执行。

```bash
cd /opt/ops-lab2-13
export PATH=/opt/ops-lab2-go1.26.10/go/bin:$PATH
make build test vet fmt-check
scripts/get-tools.sh

systemd-run --unit=ops-lab2-enrolld --collect \
  --property=WorkingDirectory=/opt/ops-lab2-13 \
  --property=CPUAffinity=1 --property=Restart=on-failure \
  /opt/ops-lab2-13/bin/enrolld \
  -addr 127.0.0.1:8080 -work 200000 -pool 4 -db-ms 10 -sync each

systemd-run --unit=ops-lab2-node --collect \
  --property=WorkingDirectory=/opt/ops-lab2-13 \
  --property=CPUAffinity=0 --property=Restart=on-failure \
  /opt/ops-lab2-13/tools/node_exporter --web.listen-address=127.0.0.1:9100

systemd-run --unit=ops-lab2-prometheus --collect \
  --property=WorkingDirectory=/opt/ops-lab2-13 \
  --property=CPUAffinity=0 --property=Restart=on-failure \
  /opt/ops-lab2-13/tools/prometheus \
  --config.file=/opt/ops-lab2-13/deploy/prometheus.yml \
  --web.listen-address=127.0.0.1:9090 \
  --storage.tsdb.path=/dev/shm/ops-lab2-prometheus \
  --storage.tsdb.retention.time=24h --storage.tsdb.retention.size=256MB
```

Prometheus 数据放在内存文件系统，避免其写盘干扰后续磁盘实验；主机重启后历史数据消失。已导出的 CSV、原始日志和指标快照保存在项目 `runs/t1-light/`，不会随内存数据丢失。24 小时保留时间、256 MB 大小限制不是内存使用量的硬上限。

## 检查与低负载复现

先确认三个服务正常、两个抓取目标均为 `up`，再开始压测：

```bash
systemctl is-active ops-lab2-enrolld ops-lab2-node ops-lab2-prometheus
curl -fsS http://127.0.0.1:8080/config
curl -fsS http://127.0.0.1:9090/api/v1/targets

# t1-light 是本次数据；复测须换新名字，run.sh 会拒绝覆盖已有目录。
GEN_CPUS=0 scripts/run.sh t1-light-repeat \
  -url http://127.0.0.1:8080/api/courses/1 -rates 0,50,100 -step 30s

scripts/table.sh runs/t1-light \
  ok_rps mean_ms p99_ms server_rps server_mean_ms server_p99_ms \
  cpu_ms_per_req db_query_mean_ms
```

`run.sh` 默认使用 Poisson 到达过程、随机种子 1、SLO 50 ms。每阶段 Prometheus 查询丢弃前 5 秒，使用剩余 25 秒；客户端表格覆盖完整阶段。因此两端吞吐与分位数不会完全相同，服务端直方图 p99 也有桶插值误差。

纯读实验不会产生 fsync；相关平均值或分位数为 NaN 是预期现象。空载阶段没有请求时，错误率、SLI、每请求 CPU 等比率没有定义，可能为空或 NaN；不要将这些改成虚假的 0。无 5xx 但有请求时，错误率应为 0。

组员离线复核可直接查看 `runs/t1-light/` 中已归档的 CSV、JSON 和日志，无需登录云主机。`verify.py` 是本次在线验收脚本，会访问本机 `127.0.0.1:9090`，依赖 Prometheus 仍保留该次实验的历史数据，并覆盖抓取状态与验证 JSON；请勿直接在原始归档目录重跑它。历史数据过期后，应以已归档证据复核。

## 本机访问与管理

三个 HTTP 端口仅监听云主机回环地址。需要在电脑浏览器查看时，建立 SSH 隧道（密码在提示时输入）：

```bash
ssh -N -L 9090:127.0.0.1:9090 -L 8080:127.0.0.1:8080 root@121.36.249.26
```

然后打开 `http://127.0.0.1:9090`。如果本机端口被占用，可把第一个 `9090` 改为其他空闲端口。

```bash
# 查看日志
journalctl -u ops-lab2-enrolld -u ops-lab2-node -u ops-lab2-prometheus --no-pager -n 100
# 停止本实验服务；不会删除数据
systemctl stop ops-lab2-enrolld ops-lab2-node ops-lab2-prometheus
```
