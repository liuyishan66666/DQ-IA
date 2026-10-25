"""Statistics and publication figures from the actual run, never preset results."""
import csv
import gzip
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import scipy
from scipy.stats import t as student_t

from .simulation import NS, SIZES

LABELS = {'B': 'B: per-bundle signature', 'C': 'C: DQ-IA', 'D': 'D: symmetric AEAD'}
COLORS = {'B': '#c44e52', 'C': '#0072b2', 'D': '#009e73'}
METRICS = ['generated', 'delivered', 'expired', 'received_24h', 'delivery_ratio',
           'expiry_ratio', 'throughput_bps', 'wait_median_s', 'wait_p95_s',
           'delay_median_s', 'delay_p95_s', 'queue_max']


def ci95(values):
    values = np.asarray(values, dtype=float)
    mean = float(values.mean())
    half = float(student_t.ppf(.975, len(values)-1) * values.std(ddof=1) / np.sqrt(len(values)))
    return mean, mean-half, mean+half


def save_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def save_figure(fig, out, name):
    fig.tight_layout()
    for ext in ['png', 'pdf', 'svg']:
        fig.savefig(out / 'figures' / f'{name}.{ext}', dpi=220)
    plt.close(fig)


def make_report(out, rows, cfg):
    capacity = []
    for scheme, size in SIZES.items():
        duration_ns = 8 * size * NS // cfg.bandwidth_bps
        maximum = cfg.contact_ns // duration_ns
        capacity.append({'scheme': scheme, 'bundle_bytes': size,
                         'security_overhead_bytes': size - cfg.payload_bytes,
                         'transmission_s': duration_ns / NS,
                         'full_window_capacity': maximum,
                         'payload_bytes_per_full_window': maximum * cfg.payload_bytes,
                         'ideal_period_capacity_per_hour': maximum * 3600 * NS / cfg.period_ns})
    save_csv(out / 'analytical_capacity.csv', capacity)
    continuous = [r for r in rows if r['scenario'] == 'continuous']
    rates = sorted({r['load'] for r in continuous})
    summary = []
    for scheme in SIZES:
        for rate in rates:
            group = [r for r in continuous if r['scheme'] == scheme and r['load'] == rate]
            for metric in METRICS:
                mean, low, high = ci95([r[metric] for r in group])
                summary.append({'scheme': scheme, 'rate_per_hour': rate, 'metric': metric,
                                'n': len(group), 'mean': mean, 'ci95_low': low, 'ci95_high': high})
    save_csv(out / 'continuous_summary.csv', summary)
    lookup = {(r['scheme'], r['rate_per_hour'], r['metric']): r for r in summary}
    paired = []
    for a, b in [('C', 'B'), ('D', 'B'), ('C', 'D')]:
        for rate in rates:
            ga = {r['seed']: r for r in continuous if r['scheme'] == a and r['load'] == rate}
            gb = {r['seed']: r for r in continuous if r['scheme'] == b and r['load'] == rate}
            assert ga.keys() == gb.keys() and len(ga) == 20
            for metric in METRICS:
                factor = 100 if metric in ['delivery_ratio', 'expiry_ratio'] else 1
                values = [(ga[seed][metric] - gb[seed][metric]) * factor for seed in sorted(ga)]
                mean, low, high = ci95(values)
                paired.append({'comparison': f'{a}-{b}', 'rate_per_hour': rate,
                               'metric': metric, 'unit': 'percentage_points' if factor == 100 else 'native',
                               'n_pairs': len(values), 'mean_difference': mean,
                               'ci95_low': low, 'ci95_high': high})
    save_csv(out / 'paired_differences.csv', paired)
    bursts = [r for r in rows if r['scenario'] == 'burst']
    save_csv(out / 'burst_results.csv', bursts)
    # All three controls plotted with seed-level t intervals, not pooled packets.
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False,
                         'axes.spines.right': False, 'pdf.fonttype': 42})
    for metric, ylabel, scale, name in [
        ('delivery_ratio', 'On-time delivery (%)', 100, 'load_delivery'),
        ('throughput_bps', 'Payload throughput in [0, 24 h) (bit/s)', 1, 'load_throughput')]:
        fig, ax = plt.subplots(figsize=(7.2, 4.5))
        for scheme in SIZES:
            data = [lookup[scheme, rate, metric] for rate in rates]
            mean = np.array([r['mean'] for r in data]) * scale
            low = np.array([r['ci95_low'] for r in data]) * scale
            high = np.array([r['ci95_high'] for r in data]) * scale
            style = {'B': ('o', '-'), 'C': ('s', '--'), 'D': ('^', ':')}[scheme]
            ax.errorbar(rates, mean, yerr=[mean-low, high-mean], label=LABELS[scheme],
                        color=COLORS[scheme], marker=style[0], linestyle=style[1], capsize=3)
        ax.set(xlabel='Command generation rate (commands/h)', ylabel=ylabel)
        if metric == 'delivery_ratio':
            ax.set_ylim(0, 104)
        ax.grid(alpha=.2)
        ax.legend()
        save_figure(fig, out, name)
    first_seed = min(r['seed'] for r in continuous)
    for rate in [120, 300]:
        fig, axes = plt.subplots(3, 1, figsize=(10, 7), sharex=True)
        plot_end = 24.5
        for ax, scheme in zip(axes, SIZES):
            path = out / 'queues' / f'continuous_{rate}_{first_seed}_{scheme}.csv.gz'
            with gzip.open(path, 'rt') as f:
                trace = [(int(r['time_ns']) / NS / 3600, int(r['waiting'])) for r in csv.DictReader(f)]
            x, y = zip(*trace)
            plot_end = max(plot_end, max(x) + .1)
            ax.step(x, y, where='post', color=COLORS[scheme], linewidth=.8, label=LABELS[scheme])
            # Contacts continue through drain; the grey boundary marks end of generation.
            end_hour = max(24, max(x))
            for start in range(0, int(end_hour * 3600 * NS)+1, cfg.period_ns):
                ax.axvspan(start / NS / 3600, (start + cfg.contact_ns) / NS / 3600,
                           color='#999999', alpha=.15)
            ax.axvline(24, color='black', linestyle=':', linewidth=.8)
            ax.set_ylabel('Waiting queue')
            ax.legend(loc='upper left')
            ax.grid(alpha=.15)
        axes[-1].set_xlabel('Time (h); shaded = ground contact, dotted = generation ends')
        axes[-1].set_xlim(0, plot_end)
        fig.suptitle(f'{rate} commands/h, preselected seed {first_seed}')
        save_figure(fig, out, f'queue_{rate}')
    config = json.loads((out / 'config.json').read_text())
    config['analysis_versions'] = {'numpy': np.__version__, 'scipy': scipy.__version__,
                                   'matplotlib': matplotlib.__version__}
    (out / 'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    lines = [
        '# 第六章：已运行的本机网络仿真实验', '',
        '本报告由实际输出自动生成；运行位置为云工作区，程序可在普通电脑复跑。',
        '本次完成 7 种连续负载 × 20 个固定种子 × 3 个方案，以及 4 种突发批量 × 3 个方案，共 432 组运行。',
        '所有生成清单跨方案复用；采用整数纳秒计时，整束发送，FCFS，不跨接触窗口分段。',
        '期限为生成起 5400 s 内到达（含边界），传播为 780 s；生成区间和吞吐量接收观察区间均为 [0,86400 s)。',
        '24 h 后停止生成并继续排空；期限不可满足的队首在决策时提前移除，过期不占用链路。', '',
        '## 连续生成结果', '',
        '下表是逐种子指标的均值。完整均值和双侧 95% Student t 置信区间见 continuous_summary.csv。', '',
        '|负载/条·h⁻¹|B 交付率/%|C 交付率/%|D 交付率/%|C−B 交付率/百分点（95% CI）|B 吞吐/bit·s⁻¹|C 吞吐/bit·s⁻¹|D 吞吐/bit·s⁻¹|',
        '|---:|---:|---:|---:|---:|---:|---:|---:|']
    for rate in rates:
        delivery = [lookup[s, rate, 'delivery_ratio']['mean'] * 100 for s in SIZES]
        throughput = [lookup[s, rate, 'throughput_bps']['mean'] for s in SIZES]
        diff = next(r for r in paired if r['comparison'] == 'C-B' and
                    r['rate_per_hour'] == rate and r['metric'] == 'delivery_ratio')
        lines.append(f'|{rate}|' + '|'.join(f'{x:.3f}' for x in delivery) +
                     f'|{diff["mean_difference"]:.3f} [{diff["ci95_low"]:.3f}, {diff["ci95_high"]:.3f}]|' +
                     '|'.join(f'{x:.3f}' for x in throughput) + '|')
    lines += ['', '## 突发结果（确定性，不构造置信区间）', '',
              '生成时段内共有 20 个接触起点；每个起点注入一批。首窗口比例仅统计 t=0 的首批。等待时延仅对最终交付样本计算。', '',
              '|每批条数|方案|生成总数|首窗口发完/首批|最终交付数|过期/%|等待中位/s|等待 P95/s|端到端 P95/s|',
              '|---:|:---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in bursts:
        lines.append(f'|{r["load"]}|{r["scheme"]}|{r["generated"]}|{100*r["first_window_ratio"]:.2f}%|'
                     f'{r["delivered"]}|{100*r["expiry_ratio"]:.3f}|{r["wait_median_s"]:.3f}|'
                     f'{r["wait_p95_s"]:.3f}|{r["delay_p95_s"]:.3f}|')
    lines += ['', '## 可用于第六章的结果描述', '']
    for rate in [30, 120, 300, 600]:
        b = lookup['B', rate, 'delivered']['mean']
        c = lookup['C', rate, 'delivered']['mean']
        p_b = lookup['B', rate, 'delivery_ratio']['mean']
        p_c = lookup['C', rate, 'delivery_ratio']['mean']
        lines.append(f'在 {rate} 条/h 下，B 与 DQ-IA 的平均最终交付数分别为 {b:.2f} 和 {c:.2f} 条，'
                     f'DQ-IA 平均多交付 {c-b:.2f} 条，过期比例减少 {(p_c-p_b)*100:.3f} 个百分点。')
        lines.append('')
    high = lookup['C', 600, 'expiry_ratio']['mean'] * 100
    lines += [f'当负载达到 600 条/h，DQ-IA 的平均过期比例为 {high:.3f}%，说明其容量同样有限。',
              '450 条/h 略高于 DQ-IA 的理想长期能力 446.4 条/h，但有限 24 h 生成时段加排空及 90 min 期限允许本次样本全部及时交付，不能据此声称无限时域队列稳定。',
              '120 条/h 的 C−B 配对交付率差值区间包含零；这一负载下不宣称存在统计显著的交付率提升。',
              '低负载下如三组均为 100% 交付，应说明交付率无差异；吞吐量只计 24 h 内实际到达的业务明文字节，因此仍有观察边界效应。',
              '队列图使用预先固定的第一个种子，并对 B/C/D 复用相同生成清单。阴影为地面接触窗口，竖虚线为停止生成时刻。',
              '时延为已交付样本的条件统计，必须与交付率同时解读；不能把不同方案剩余样本的较低时延直接视为整体更好。', '',
              '## 证据文件与边界', '',
              '- network_results.csv：全部 432 组逐运行指标。',
              '- continuous_summary.csv / paired_differences.csv：逐种子汇总和配对差值及 95% CI；交付率和过期比例差值单位为百分点。',
              '- burst_results.csv：确定性突发场景。',
              '- events/*.csv.gz：每条指令的生成、决策、发送开始/完成、星上到达及最终状态；空时间表示未发送。',
              '- traffic/*.csv.gz / queues/*.csv.gz：可复用生成清单及不含发送中指令的事件后队长；同一时刻事件合并。',
              '- figures/：交付率、吞吐量、120 与 300 条/h 队列图，均含 PNG/PDF/SVG。',
              '- config.json：参数、全部固定种子、软件版本、源文件和 PDF 校验摘要。', '',
              'H=40 B 为解析假设，非实际 BPSec 封装测量；没有运行真实密码算法、ProVerif、Ubuntu 网络栈、QEMU 或星载硬件。',
              '结果不证明密码安全性、互操作性、RAM、能耗、掉电恢复或真实链路性能。B 与 C 的认证信任条件不同。',
              '纯对称 D 的字节成本最低，不将 DQ-IA 表述为在带宽上优于 D。',
              '本稿并没有要求 Ubuntu 专属主实验；若后续开展 ProVerif，应独立建模并保留工具运行记录。', '']
    (out / '实验结果说明.md').write_text('\n'.join(lines), encoding='utf-8')
