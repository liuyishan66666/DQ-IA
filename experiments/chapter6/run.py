"""Run with: python -m experiments.chapter6.run [--output DIRECTORY]."""
import argparse
import csv
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import sys

from .simulation import (Config, NS, SIZES, burst_arrivals, metrics,
                         poisson_arrivals, queue_trace, simulate)

RATES = [30, 60, 120, 180, 300, 450, 600]
BATCHES = [100, 180, 300, 600]
SEEDS = list(range(2026102501, 2026102521))


def write_csv(path, rows, fields=None):
    rows = iter(rows)
    first = next(rows, None)
    if first is None:
        raise ValueError(f'No rows for {path}')
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'wt', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields or list(first))
        writer.writeheader()
        writer.writerow(first)
        writer.writerows(rows)


def validate(records, size, cfg):
    previous_finish = 0
    for r in records:
        assert r.arrival_ns < cfg.observation_ns
        if r.status == 'delivered':
            assert r.start_ns >= max(r.arrival_ns, previous_finish)
            assert r.finish_ns - r.start_ns == 8 * size * NS // cfg.bandwidth_bps
            assert r.start_ns % cfg.period_ns + r.finish_ns - r.start_ns <= cfg.contact_ns
            assert r.receive_ns == r.finish_ns + cfg.propagation_ns
            assert r.receive_ns <= r.arrival_ns + cfg.deadline_ns
            previous_finish = r.finish_ns
        else:
            assert r.start_ns is None and r.receive_ns is None
    m = metrics(records, cfg)
    assert m['generated'] == m['delivered'] + m['expired']
    assert m['received_24h'] <= m['delivered']
    return m


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('experiments/chapter6/results'))
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('Output directory is nonempty; select a new path to preserve previous evidence')
    for folder in ['', 'events', 'queues', 'traffic', 'figures']:
        (out / folder).mkdir(parents=True, exist_ok=True)
    cfg = Config()
    config = {**asdict(cfg), 'sizes_bytes': SIZES, 'rates_per_hour': RATES,
              'burst_batches': BATCHES, 'seeds': SEEDS, 'python': sys.version,
              'platform': platform.platform(), 'time_unit': 'integer nanoseconds',
              'observation_interval': '[0, 86400 seconds)',
              'queue_policy': 'FCFS, predictive head expiry, nonpreemptive, no segmentation',
              'random_generator': 'Python random.Random(seed).expovariate(rate/3600)',
              'arrival_rounding': 'round absolute seconds to integer nanoseconds',
              'confidence_interval': 'two-sided Student t, df=19, across seed metrics',
              'source_document': 'DQIA_chapter6_revised.pdf',
              'source_pdf_sha256': '7e5fcfffb73f066b7f8add5e1185b0e2cda267edb64748d63a3edc0c017ce83f',
              'assumptions': ['H=40 bytes is assumed, not measured BPSec encoding',
                              'No bit errors, retransmissions, crypto cost, or buffer limit'],
              'code_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in Path(__file__).parent.glob('*.py')}}
    (out / 'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    rows = []
    scenarios = [('continuous', rate, seed) for rate in RATES for seed in SEEDS]
    scenarios += [('burst', batch, None) for batch in BATCHES]
    for scenario, load, seed in scenarios:
        tag = f'{scenario}_{load}_{seed if seed is not None else "deterministic"}'
        arrivals = (poisson_arrivals(load, seed, cfg) if scenario == 'continuous'
                    else burst_arrivals(load, cfg))
        write_csv(out / 'traffic' / f'{tag}.csv.gz',
                  ({'command_id': i, 'arrival_ns': a} for i, a in enumerate(arrivals)))
        for scheme, size in SIZES.items():
            records = simulate(arrivals, size, cfg)
            row = {'scheme': scheme, 'scenario': scenario, 'load': load,
                   'seed': seed if seed is not None else '', **validate(records, size, cfg)}
            rows.append(row)
            write_csv(out / 'events' / f'{tag}_{scheme}.csv.gz', (asdict(r) for r in records))
            write_csv(out / 'queues' / f'{tag}_{scheme}.csv.gz',
                      ({'time_ns': t, 'waiting': q} for t, q in queue_trace(records)))
        if scenario == 'burst' or seed == SEEDS[-1]:
            print(f'Completed {scenario} load={load}', flush=True)
    write_csv(out / 'network_results.csv', rows)
    # Set before importing matplotlib, so no writes are attempted in a read-only HOME.
    os.environ.setdefault('MPLCONFIGDIR', str(out / '.mpl-cache'))
    from .report import make_report
    make_report(out, rows, cfg)
    print(f'Validated {len(rows)} runs. Results: {out}', flush=True)


if __name__ == '__main__':
    main()
