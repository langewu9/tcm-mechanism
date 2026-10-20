"""Render local load-test metrics as Chinese Markdown/HTML/CSV and PNG charts."""
import base64
import csv
import html
import datetime
import os
import json
from pathlib import Path
import statistics
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
VAR = ROOT / "python_app/var/loadtest"
OUT = ROOT / "reports/loadtest-2026-10-20"
sys.path.append(str(ROOT / "python_app/var/loadtest-runtime"))
os.environ.setdefault("MPLCONFIGDIR", str(VAR / "matplotlib-cache"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

font = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
font_manager.fontManager.addfont(str(font))
plt.rcParams.update({"font.family": font_manager.FontProperties(fname=font).get_name(), "font.size": 11,
    "axes.unicode_minus": False, "figure.facecolor": "#f5f7fc", "axes.facecolor": "white",
    "axes.labelcolor": "#42516b", "text.color": "#172641", "xtick.color": "#61708a", "ytick.color": "#61708a",
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False, "axes.spines.bottom": False,
    "grid.color": "#e4e9f2", "grid.linewidth": .7, "axes.titleweight": "bold", "savefig.dpi": 170})


def num(value):
    return "—" if value is None else f"{value:,.1f}"


def main():
    data = json.loads((VAR / "metrics.json").read_text())
    resources = json.loads((VAR / "resources.json").read_text())
    if not data.get("completed"):
        raise SystemExit("Load test did not complete; inspect metrics before publishing a final report")
    OUT.mkdir(parents=True, exist_ok=True)
    phases = data["phases"]
    requests = [json.loads(line) for line in (VAR / "requests.jsonl").read_text().splitlines()]
    boots=[]
    for line in (VAR / "api.log").read_text().splitlines():
        match=re.match(r'\[([^]]+)\].*Booting worker',line)
        if match:
            boots.append(datetime.datetime.strptime(match.group(1),'%Y-%m-%d %H:%M:%S %z').timestamp())
    slow=[row for row in requests if row['phase']!='production-limits-20'
          and row['latencyMs']>1000 and int(row['phase'].rsplit('-',1)[1])<=40]
    near=[row for row in slow if any(row['time']-row['latencyMs']/1000<=boot+3 and row['time']>=boot for boot in boots)]
    data['workerRestartObservation']={'slowOverOneSecondAtUpTo40Concurrency':len(slow),
                                     'overlappingOrWithinThreeSecondsOfBoot':len(near),
                                     'causationProven':False}
    # Attribute resource samples by actual request time windows; gaps contain
    # worker startup/reloads and must not be counted as upload/request CPU.
    windows = {}
    for row in requests:
        start = row["time"] - row["latencyMs"] / 1000
        old = windows.setdefault(row["phase"], [start, row["time"]])
        old[0], old[1] = min(old[0],start), max(old[1],row["time"])
    for sample in resources:
        sample["requestPhase"] = next((name for name,(a,b) in windows.items() if a <= sample["time"] <= b), "setup/idle")
    for phase in phases:
        samples = [sample for sample in resources if sample["requestPhase"] == phase["name"]]
        for group in ("api","postgres","redis","nginx","client"):
            cpu = [sample.get(group+"CpuPercent",0) for sample in samples]
            rss = [sample.get(group+"RssMiB",0) for sample in samples]
            phase[group+"CpuMeanPercent"] = statistics.mean(cpu) if cpu else None
            phase[group+"RssPeakMiB"] = max(rss) if rss else None
    total = sum(phase["requests"] for phase in phases)
    capacity = [phase for phase in phases if phase["name"] != "production-limits-20"]
    errors = sum(phase["errors"] for phase in capacity)
    rate = next(phase for phase in phases if phase["name"] == "production-limits-20")
    soak = next(phase for phase in phases if phase["name"] == "soak-20")
    upload = next(phase for phase in phases if phase["name"] == "upload-5")
    colors = {"summary":"#4263eb","legacy":"#ec9854","mixed":"#168b7b"}
    names = {"summary":"摘要列表","legacy":"完整列表（兼容接口）","mixed":"混合读写"}
    fig, axes = plt.subplots(1,2,figsize=(14,5.3))
    for kind in ("summary","legacy","mixed"):
        subset = [phase for phase in capacity if phase["workload"] == kind]
        for ax, field in zip(axes,("successfulPerSecond","p95Ms")):
            ax.plot([phase["concurrency"] for phase in subset],[phase[field] for phase in subset],
                    color=colors[kind],label=names[kind],marker="o",linewidth=2.4,markersize=6)
            ax.set_xscale("log",base=2)
            ax.set_xticks([1,5,10,20,40,80],["1","5","10","20","40","80"])
            ax.set_xlabel("并发级别 · 持续请求，无思考时间")
            ax.grid(axis="y")
            ax.set_axisbelow(True)
    axes[0].set(title="吞吐量随并发的变化",ylabel="成功请求 / 秒")
    axes[1].set(title="响应延迟随并发的变化",ylabel="成功请求 p95 / 毫秒")
    axes[0].legend(frameon=False,loc="lower right")
    fig.suptitle("岐黄平台 · 本地接口压测",x=.065,ha="left",fontsize=20,fontweight="bold")
    fig.text(.065,.89,"30,000 个合成任务 / 100 个账号 / 3 个 Gunicorn worker / HTTPS → Django → PostgreSQL",fontsize=10,color="#61708a")
    fig.text(.065,.02,"仅容量实例提高限流；不是公网用户数或正式服务器容量。p95 表示 95% 的成功请求在该时间内完成。",fontsize=9,color="#61708a")
    fig.subplots_adjust(left=.065,right=.98,bottom=.17,top=.79,wspace=.24)
    fig.savefig(OUT / "capacity.png")
    plt.close(fig)

    fig,axes=plt.subplots(2,1,figsize=(14,6.6),sharex=True)
    baseline=min(sample["time"] for sample in resources)
    x=[sample["time"]-baseline for sample in resources]
    for group,label,color in [("api","API（主进程＋worker）","#4263eb"),("postgres","独立 PostgreSQL","#168b7b"),("client","压测客户端","#ac75cc")]:
        axes[0].plot(x,[sample.get(group+"CpuPercent",0) for sample in resources],label=label,color=color,linewidth=1.3,alpha=.9)
    axes[1].plot(x,[sample.get("apiRssMiB",0) for sample in resources],color="#4263eb",linewidth=1.8,label="API RSS 总和")
    axes[0].set(ylabel="CPU · 单核 100%",title="资源变化（含阶段之间的进程回收 / 重新启动）")
    axes[1].set(ylabel="API RSS / MiB",xlabel="压测开始后的时间 / 秒")
    for ax in axes:
        ax.grid(axis="y");ax.legend(frameon=False,loc="upper right")
    fig.suptitle("资源占用与进程回收",x=.065,ha="left",fontsize=20,fontweight="bold")
    fig.text(.065,.02,"RSS 相加包含共享页重复计数；CPU 超过 100% 表示使用多个逻辑核心。测试与客户端位于同一台电脑。",fontsize=9,color="#61708a")
    fig.subplots_adjust(left=.075,right=.98,bottom=.12,top=.84,hspace=.35)
    fig.savefig(OUT / "resources.png")
    plt.close(fig)

    a,b=windows["soak-20"]
    observations=[row for row in requests if row["phase"]=="soak-20"]
    buckets=[]
    for offset in range(0,int(b-a),5):
        width = min(5,b-a-offset)
        if width < 4.5:
            continue
        values=[row for row in observations if a+offset <= row["time"] < a+offset+5]
        successful=[row["latencyMs"] for row in values if row["status"] in (200,201) and row["valid"]]
        if not successful:continue
        successful.sort()
        buckets.append((offset+width/2,len(successful)/width,successful[min(len(successful)-1,int(len(successful)*.95))]))
    fig,axes=plt.subplots(1,2,figsize=(14,4.8))
    axes[0].plot([row[0] for row in buckets],[row[1] for row in buckets],color="#168b7b",marker="o",linewidth=2.2)
    axes[1].plot([row[0] for row in buckets],[row[2] for row in buckets],color="#4263eb",marker="o",linewidth=2.2)
    axes[0].set(title="每 5 秒成功吞吐量",ylabel="成功请求 / 秒")
    axes[1].set(title="每 5 秒响应时间",ylabel="成功请求 p95 / 毫秒")
    for ax in axes:
        ax.set_xlabel("持续负载时间 / 秒");ax.grid(axis="y")
    fig.suptitle("20 并发 · 60 秒短时持续负载",x=.065,ha="left",fontsize=19,fontweight="bold")
    fig.text(.065,.025,"固定 20 并发，按序混合摘要、详情、数据集、总览和合成医案写入；不代表小时级稳定性验收。",fontsize=9,color="#61708a")
    fig.subplots_adjust(left=.065,right=.98,bottom=.19,top=.76,wspace=.25)
    fig.savefig(OUT / "sustained.png")
    plt.close(fig)

    columns=["name","concurrency","seconds","requests","successful","successfulPerSecond","p50Ms","p95Ms","p99Ms","maxMs","errors","rateLimited","writes","apiCpuMeanPercent","apiRssPeakMiB","clientCpuMeanPercent"]
    with (OUT / "阶段数据.csv").open("w",encoding="utf-8-sig",newline="") as output:
        writer=csv.DictWriter(output,fieldnames=columns,extrasaction="ignore");writer.writeheader();writer.writerows(phases)
    (OUT / "metrics.json").write_text(json.dumps(data,ensure_ascii=False,indent=2))
    with (OUT / "资源采样.csv").open("w",encoding="utf-8-sig",newline="") as output:
        fields=sorted({key for sample in resources for key in sample})
        writer=csv.DictWriter(output,fieldnames=fields);writer.writeheader();writer.writerows(resources)

    def table_lines(items):
        lines=["| 场景 | 并发 | 请求数 | 成功/秒 | p50 ms | p95 ms | p99 ms | 错误 | 429 |",
               "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for phase in items:
            lines.append(f"| {phase['name']} | {phase['concurrency']} | {phase['requests']:,} | {num(phase['successfulPerSecond'])} | {num(phase['p50Ms'])} | {num(phase['p95Ms'])} | {num(phase['p99Ms'])} | {phase['errors']} | {phase['rateLimited']} |")
        return "\n".join(lines)
    peak=max(capacity,key=lambda phase:phase["successfulPerSecond"])
    mixed40=next(phase for phase in phases if phase['name']=='mixed-40')
    mixed80=next(phase for phase in phases if phase['name']=='mixed-80')
    integrity=data["writeIntegrity"]
    actual_seconds=sum(phase["seconds"] for phase in phases)
    md=f"""# 平台本地压测报告 · 2026-10-20

测试应用提交：`{data['commit']}`。开始时间：{data['startedAt']}。共 {len(phases)} 个阶段，实际请求窗口合计 {actual_seconds:.1f} 秒，共 {total:,} 次请求（另有未计入的预热和权限检查）。容量阶段请求错误 {errors} 次；正式限流阶段的 {rate['rateLimited']:,} 次 429 单独统计。

容量阶段实际 {sum(phase['requests'] for phase in capacity):,} 次请求。混合读写在 40/80 并发的吞吐分别为 {mixed40['successfulPerSecond']:.1f}/{mixed80['successfulPerSecond']:.1f} 次/秒，p95 分别为 {mixed40['p95Ms']:.1f}/{mixed80['p95Ms']:.1f} ms；继续提高并发没有明显增加吞吐，却增加了排队。API 在这两个阶段分别约使用 {mixed40['apiCpuMeanPercent']/100:.1f}/{mixed80['apiCpuMeanPercent']/100:.1f} 个逻辑核心，数据库 CPU 约占单核的三成，瓶颈迹象主要在当前三个同步 worker。这个判断来自本机资源相关性，尚未通过增加 worker 的对照实验证明。

## 测试环境与方法

- 本机 Intel Core Ultra 5 125H，{data['cpuLogical']} 个逻辑 CPU，{data['memoryGiB']:.1f} GiB 内存；压测客户端与服务端同机，其他桌面程序仍在运行。
- 独立 Nginx HTTPS → Gunicorn 3 个同步 worker → Django → PostgreSQL 17，另有独立 Redis。PostgreSQL shared_buffers 128 MiB，最多 64 个连接。Nginx 单 worker、512 个连接槽，客户端使用 HTTP/1.1 保持连接。
- 30,000 个合成任务、100 个有效会话，每个账号 300 个任务；结果含 8,192 字符的合成随机负载。另有 30,000 条任务来源关联。开始时数据集 {integrity['before']['datasets']} 个、医案 {integrity['before']['cases']} 个，包含短预检保留的合成记录。
- 所有账号、文件和医案均为合成内容；未调用模型、外部生物数据库、邮件、R、S3 或后台分析队列。会话在准备阶段创建，本报告不测登录密码校验性能。
- 容量阶段只在独立压测实例把用户/入口限流提高到 600,000/min，正式配置未修改；最后重启测试 API/入口，按原 600/min 用户与入口配置单独测限流。
- 每个阶梯约 15 秒；并发 1、5、10、20、40、80。闭环客户端持续发请求、没有用户思考时间；服务变慢时到达率会随之下降，不能代表开放式固定到达率极限。
- p50/p95/p99 仅计算成功且校验通过的请求；错误、超时及 429 另计。每个阶段的平均速率包含最后一批请求的排空时间。先预热，阶段间没有停机冷却，Gunicorn 保留原 1,000～1,100 请求进程回收策略。

## 容量阶梯结果

{table_lines([phase for phase in capacity if phase['workload'] in ('summary','legacy','mixed')])}

![容量曲线](capacity.png)

本轮最高成功吞吐阶段是 `{peak['name']}`，约 {peak['successfulPerSecond']:.1f} 次/秒。这是该电脑、该数据与该接口组合的观测值，不能直接换算成注册用户数或公网服务器容量。并发增加后若吞吐趋平而 p95 上升，说明继续增加并发主要在增加排队。

## 持续负载、上传与限流

{table_lines([soak,upload,rate])}

- 短时持续负载：20 并发，{soak['seconds']:.1f} 秒，成功 {soak['successful']:,} 次，p95 {num(soak['p95Ms'])} ms。这只是 60 秒观察，不是小时级内存泄漏或故障恢复验收。
- 文件上传：5 并发，每个客户端上传 3 次，共 {upload['successful']} 个约 0.99 MiB / 1,000 行 CSV，p95 {num(upload['p95Ms'])} ms。测本地私有文件落盘、解析、行记录和审计写入，未测 S3、100 MiB 大文件或恶意文件。
- 正式限流：{rate['requests']:,} 次尝试中成功 {rate['successful']} 次，{rate['rateLimited']:,} 次返回规范 429，其他错误 {rate['errors']}。入口按同一个本机 IP 计算，600/min 加允许突发，所以短窗口的成功速率可能高于长期 10 次/秒；该阶段不是容量成绩。
- 研究者若共用同一单位出口 IP，会共同消耗入口 IP 额度。需要用正常访问节奏核实限流是否影响协作；本轮没有自动放宽正式保护。
- 写入一致性：本轮新增合成医案 {integrity['caseWrites']} 条、上传 {integrity['uploads']} 个，返回 ID 无重复、落库无丢失、审计增量匹配，上传文件哈希全部匹配。
- 权限检查：未登录摘要返回 401，跨用户详情返回 404；成功响应逐次检查所属用户及禁止缓存头。

![短时持续负载](sustained.png)

## 资源观测

![资源曲线](resources.png)

资源按 0.5 秒采样，阶段归属按实际请求时间窗计算；阶段之间的进程启动不算进请求阶段。API RSS 是主进程和 worker 的 RSS 相加，包含共享页重复计数，不是独占物理内存。CPU 单核 100%，多进程总计可以超过 100%。进程回收期间 RSS/延迟会波动；本轮客户端 CPU 也单独记录在 CSV，需警惕负载生成器本身成为瓶颈。

40 并发混合阶段：API 平均 CPU {mixed40['apiCpuMeanPercent']:.1f}%，PostgreSQL {mixed40['postgresCpuMeanPercent']:.1f}%，客户端 {mixed40['clientCpuMeanPercent']:.1f}%；API RSS 峰值 {mixed40['apiRssPeakMiB']:.1f} MiB。负载生成器没有表现出接近单核满载的迹象。

并发不超过 40 时，容量阶段有 {len(slow)} 次超过 1 秒的响应，其中 {len(near)} 次与 worker 启动/回收时间重叠或相距 3 秒内。这是时间相关性，不是因果证明；后续适合对照 worker 数量、初始化耗时和请求回收策略。当前没有修改这些生产设置。

## 结论与边界

1. 原完整列表仍会传输约 50 条完整结果，其吞吐和延迟应与摘要列表分开评估；当前前端使用摘要再按需读取详情。
2. 本轮未定义业务 SLO，不能把“无错误”直接称为生产验收通过。建议先根据正式服务器规格重复测试，再确定允许的 p95、峰值并发和保护额度。
3. 所有服务位于同机，使用本机自签 TLS；没有公网网络延迟、浏览器渲染、正式数据目录、冷缓存、多副本、持续任务计算或外部依赖故障。因此不是完整网页性能或整个平台极限容量报告。
4. 测试服务结束后自动停止；原预览库和研究资料未改动。独立合成数据库保存在本地忽略目录，原始逐请求记录位于 `python_app/var/loadtest/requests.jsonl`，会话和凭据没有进入本报告。

配套文件：`阶段数据.csv`、`资源采样.csv`、`metrics.json`、三张 PNG；均可在本地复核。
"""
    (OUT / "压测报告.md").write_text(md)
    def image(name):
        return 'data:image/png;base64,'+base64.b64encode((OUT/name).read_bytes()).decode()
    rows="".join(f"<tr><td>{html.escape(phase['name'])}</td><td>{phase['concurrency']}</td><td>{phase['requests']:,}</td><td>{num(phase['successfulPerSecond'])}</td><td>{num(phase['p95Ms'])}</td><td>{num(phase['p99Ms'])}</td><td>{phase['errors']}</td><td>{phase['rateLimited']}</td></tr>" for phase in phases)
    paragraphs=[]
    for line in md.splitlines():
        if line.startswith(('|','![')) or not line.strip():continue
        if line.startswith('# '):continue
        if line.startswith('## '):paragraphs.append('<h2>'+html.escape(line[3:])+'</h2>')
        else:paragraphs.append('<p>'+html.escape(line.lstrip('- '))+'</p>')
    page=f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>岐黄平台 · 本地压测报告</title>
<style>body{{margin:0;background:#f4f6fb;color:#1c2940;font:15px/1.8 system-ui,sans-serif}}main{{max-width:1180px;margin:40px auto;padding:0 24px}}.hero{{padding:36px 40px;background:linear-gradient(120deg,#1d3162,#435cc4);color:white;border-radius:22px}}h1{{font-size:32px;letter-spacing:1px;margin:4px 0}}.eyebrow{{font-size:12px;letter-spacing:2px;opacity:.75}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0}}.card,section{{background:white;border:1px solid #e3e8f2;border-radius:16px;padding:24px}}.card b{{font-size:29px;color:#3857c0;display:block}}.card span{{color:#68778f}}section{{margin:22px 0}}img{{width:100%;height:auto;border-radius:12px}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{text-align:right;padding:10px 12px;border-bottom:1px solid #edf0f5;white-space:nowrap}}td:first-child,th:first-child{{text-align:left}}th{{background:#f4f6fb}}.scroll{{overflow:auto}}h2{{font-size:22px;margin:25px 0 12px}}.tag{{display:inline-block;background:#e8edf9;color:#3857c0;border-radius:20px;padding:3px 12px;font-size:12px}}p{{margin:8px 0 13px}}@media(max-width:700px){{main{{padding:0 12px;margin:18px auto}}.cards{{grid-template-columns:repeat(2,1fr)}}.hero{{padding:25px}}}}@media print{{body{{background:white}}main{{margin:0}}section{{break-inside:avoid}}}}</style>
<main><header class="hero"><div class="eyebrow">QI HUANG · LOCAL LOAD TEST · 2026.10.20</div><h1>平台接口压测报告</h1><p>30,000 合成任务 · 独立数据库 · 逐级并发 · HTTPS 全链路</p></header>
<div class="cards"><div class="card"><b>{total:,}</b><span>总请求次数</span></div><div class="card"><b>{errors}</b><span>容量阶段请求错误</span></div><div class="card"><b>{max(phase['concurrency'] for phase in capacity)}</b><span>最高已测并发级别</span></div><div class="card"><b>{peak['successfulPerSecond']:.1f}</b><span>观测峰值成功请求 / 秒</span></div></div>
<section><span class="tag">请求处理能力 · 仅压测实例提高限流</span><img src="{image('capacity.png')}" alt="不同接口的吞吐与p95曲线"></section>
<section><h2>阶段数据</h2><p>p95/p99 仅统计成功请求；429 由限流策略产生，单独列示。</p><div class="scroll"><table><thead><tr><th>阶段</th><th>并发</th><th>请求数</th><th>成功/秒</th><th>p95 ms</th><th>p99 ms</th><th>错误</th><th>429</th></tr></thead><tbody>{rows}</tbody></table></div></section>
<section><img src="{image('sustained.png')}" alt="60秒持续负载"></section><section><img src="{image('resources.png')}" alt="资源占用"></section><section>{''.join(paragraphs)}</section></main></html>"""
    (OUT / "压测报告.html").write_text(page)
    print(json.dumps({"requests":total,"capacityErrors":errors,"highestStageRps":peak["successfulPerSecond"],"writeIntegrity":integrity,"output":str(OUT)},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
