"""Audit saved raw evidence independently of in-memory run assertions."""
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path


def read_gzip(path):
    with gzip.open(path, 'rt') as f:
        yield from csv.DictReader(f)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    out = args.directory
    cfg = json.loads((out / 'config.json').read_text())
    with (out / 'network_results.csv').open() as f:
        summary = list(csv.DictReader(f))
    assert len(summary) == 432
    assert len({(r['scenario'], r['load'], r['seed'], r['scheme']) for r in summary}) == 432
    checked = 0
    for m in summary:
        tag = f'{m["scenario"]}_{m["load"]}_{m["seed"] or "deterministic"}'
        arrivals = [(int(r['command_id']), int(r['arrival_ns']))
                    for r in read_gzip(out / 'traffic' / f'{tag}.csv.gz')]
        delivered = expired = received = 0
        free = 0
        q_changes = {}
        size = cfg['sizes_bytes'][m['scheme']]
        duration = size * 8 * 10**9 // cfg['bandwidth_bps']
        period = cfg['contact_ns'] + cfg['gap_ns']
        for i, r in enumerate(read_gzip(out / 'events' / f'{tag}_{m["scheme"]}.csv.gz')):
            a = int(r['arrival_ns'])
            assert (int(r['command_id']), a) == arrivals[i]
            decision = int(r['decision_ns'])
            assert decision == max(a, free)
            # Independent arithmetic: enumerate candidate contacts from the
            # decision's cycle, using explicit interval endpoints.
            cycle = decision // period
            contact_begin = cycle * period
            start = max(decision, contact_begin)
            if start + duration > contact_begin + cfg['contact_ns']:
                start = contact_begin + period
            expected_receive = start + duration + cfg['propagation_ns']
            q_changes[a] = q_changes.get(a, 0) + 1
            if r['status'] == 'delivered':
                s, f, receive = (int(r[k]) for k in ['start_ns', 'finish_ns', 'receive_ns'])
                assert s == start and f == s + duration and receive == expected_receive
                assert receive <= a + cfg['deadline_ns']
                assert a <= s and s >= free
                delivered += 1
                received += receive < cfg['observation_ns']
                free = f
                leave = s
            else:
                assert r['status'] == 'expired'
                assert expected_receive > a + cfg['deadline_ns']
                assert all(r[k] == '' for k in ['start_ns', 'finish_ns', 'receive_ns'])
                expired += 1
                free = decision
                leave = decision
            q_changes[leave] = q_changes.get(leave, 0) - 1
            checked += 1
        assert delivered + expired == len(arrivals) == int(m['generated'])
        assert delivered == int(m['delivered']) and expired == int(m['expired'])
        assert received == int(m['received_24h'])
        assert abs(float(m['delivery_ratio']) - delivered / len(arrivals)) < 1e-12
        assert abs(float(m['throughput_bps']) - received * 8 * cfg['payload_bytes'] /
                   (cfg['observation_ns'] / 10**9)) < 1e-12
        q = 0
        expected_q = {0: 0}
        for time, delta in sorted(q_changes.items()):
            q += delta
            assert q >= 0
            expected_q[time] = q
        stored_q = {int(r['time_ns']): int(r['waiting'])
                    for r in read_gzip(out / 'queues' / f'{tag}_{m["scheme"]}.csv.gz')}
        assert expected_q == stored_q and q == 0
    hashes = []
    for path in sorted(out.rglob('*')):
        if not path.is_file() or '.mpl-cache' in path.parts or path.name in ['audit.json', 'audit_manifest_sha256.csv']:
            continue
        hashes.append({'file': str(path.relative_to(out)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    with (out / 'audit_manifest_sha256.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['file', 'sha256'])
        writer.writeheader()
        writer.writerows(hashes)
    result = {'status': 'passed', 'runs_checked': len(summary), 'command_records_checked': checked,
              'hashed_files': len(hashes), 'checks': ['shared arrival manifests and command IDs',
              'FCFS decisions and contact feasibility', 'predictive expiry and arrival deadlines',
              'delivery/expiry conservation', '24-hour reception counts and payload throughput',
              'complete queue traces and empty drained queues']}
    (out / 'audit.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
