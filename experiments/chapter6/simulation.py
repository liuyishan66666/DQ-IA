"""Chapter 6 model. Integer nanoseconds avoid contact/deadline boundary drift.

FCFS with deterministic nonpreemptive service needs no per-packet time stepping:
the next decision is at max(arrival, previous finish). If a contact must be
awaited, all subsequent arrivals join behind that head packet. Infeasible heads
are discarded at the decision time, without consuming link capacity.
"""
from dataclasses import dataclass
from collections import defaultdict
import math
import random

NS = 1_000_000_000
SIZES = {'B': 4485, 'C': 1208, 'D': 104}


@dataclass(frozen=True)
class Config:
    bandwidth_bps: int = 2000
    contact_ns: int = 2700 * NS
    gap_ns: int = 1800 * NS
    propagation_ns: int = 780 * NS
    deadline_ns: int | None = 5400 * NS
    observation_ns: int = 86400 * NS
    payload_bytes: int = 32

    @property
    def period_ns(self):
        return self.contact_ns + self.gap_ns


@dataclass(frozen=True)
class Record:
    command_id: int
    arrival_ns: int
    decision_ns: int
    start_ns: int | None
    finish_ns: int | None
    receive_ns: int | None
    status: str


def service_ns(size, cfg):
    value, remainder = divmod(8 * size * NS, cfg.bandwidth_bps)
    if remainder:
        raise ValueError('Transmission time must be exactly representable in ns')
    if not 0 < value <= cfg.contact_ns:
        raise ValueError('Bundle must fit in a complete contact')
    return value


def earliest_start(t, duration, cfg):
    phase = t % cfg.period_ns
    if phase + duration <= cfg.contact_ns:
        return t
    return t + cfg.period_ns - phase


def simulate(arrivals, size, cfg=Config()):
    duration = service_ns(size, cfg)
    free = 0
    records = []
    previous = -1
    for i, arrival in enumerate(arrivals):
        if arrival < 0 or arrival < previous:
            raise ValueError('Arrivals must be nonnegative, sorted integer ns')
        previous = arrival
        decision = max(free, arrival)
        start = earliest_start(decision, duration, cfg)
        finish = start + duration
        receive = finish + cfg.propagation_ns
        if cfg.deadline_ns is not None and receive > arrival + cfg.deadline_ns:
            records.append(Record(i, arrival, decision, None, None, None, 'expired'))
            # Preserve elapsed decision time when multiple packets expire.
            free = decision
        else:
            records.append(Record(i, arrival, decision, start, finish, receive, 'delivered'))
            free = finish
    return records


def poisson_arrivals(rate_per_hour, seed, cfg=Config()):
    rng = random.Random(seed)
    t = 0.0
    arrivals = []
    horizon = cfg.observation_ns / NS
    while True:
        t += rng.expovariate(rate_per_hour / 3600)
        if t >= horizon:
            break
        timestamp = round(t * NS)
        if timestamp < cfg.observation_ns:
            arrivals.append(timestamp)
    return arrivals


def burst_arrivals(batch, cfg=Config()):
    return [t for t in range(0, cfg.observation_ns, cfg.period_ns)
            for _ in range(batch)]


def quantile(values, p):
    """Linear interpolation at (n-1)*p, matching NumPy's default method."""
    if not values:
        return math.nan
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    lo = math.floor(index)
    hi = math.ceil(index)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def queue_trace(records):
    """Post-event queue length; aggregate simultaneous changes, omit in-service.

    Expiration is predictive removal when an FCFS head cannot arrive in time,
    not necessarily removal at the wall-clock deadline itself.
    """
    changes = defaultdict(int)
    changes[0] = 0
    for r in records:
        changes[r.arrival_ns] += 1
        departure = r.start_ns if r.status == 'delivered' else r.decision_ns
        changes[departure] -= 1
    q = 0
    trace = []
    for t, delta in sorted(changes.items()):
        q += delta
        assert q >= 0
        trace.append((t, q))
    assert q == 0
    return trace


def metrics(records, cfg=Config()):
    delivered = [r for r in records if r.status == 'delivered']
    generated = len(records)
    received_24h = sum(r.receive_ns < cfg.observation_ns for r in delivered)
    waits = [(r.start_ns - r.arrival_ns) / NS for r in delivered]
    delays = [(r.receive_ns - r.arrival_ns) / NS for r in delivered]
    first_batch = [r for r in records if r.arrival_ns == 0]
    first_sent = sum(r.finish_ns is not None and r.finish_ns <= cfg.contact_ns
                     for r in first_batch)
    return {
        'generated': generated, 'delivered': len(delivered),
        'expired': generated - len(delivered), 'received_24h': received_24h,
        'delivery_ratio': len(delivered) / generated if generated else math.nan,
        'expiry_ratio': (generated - len(delivered)) / generated if generated else math.nan,
        'throughput_bps': 8 * cfg.payload_bytes * received_24h / (cfg.observation_ns / NS),
        'wait_median_s': quantile(waits, .5), 'wait_p95_s': quantile(waits, .95),
        'delay_median_s': quantile(delays, .5), 'delay_p95_s': quantile(delays, .95),
        'first_window_sent': first_sent,
        'first_window_ratio': first_sent / len(first_batch) if first_batch else math.nan,
        'last_receive_s': max((r.receive_ns / NS for r in delivered), default=math.nan),
        'queue_max': max((q for _, q in queue_trace(records)), default=0),
    }
