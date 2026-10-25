import math
import random
import unittest
from dataclasses import replace

from experiments.chapter6.simulation import (
    Config, NS, SIZES, burst_arrivals, earliest_start, metrics,
    poisson_arrivals, queue_trace, simulate,
)


class Chapter6Tests(unittest.TestCase):
    def test_saturated_capacity_without_deadline(self):
        cfg = replace(Config(), deadline_ns=None)
        for scheme, expected in [('B', 150), ('C', 558), ('D', 6490)]:
            records = simulate([0] * (expected + 1), SIZES[scheme], cfg)
            self.assertEqual(sum(r.finish_ns <= cfg.contact_ns for r in records), expected)
            self.assertEqual(records[-1].start_ns, cfg.period_ns)

    def test_single_180_batch(self):
        b = simulate([0] * 180, SIZES['B'])
        c = simulate([0] * 180, SIZES['C'])
        self.assertEqual(sum(r.finish_ns is not None and r.finish_ns <= 2700*NS for r in b), 150)
        self.assertEqual(c[-1].finish_ns, 869760000000)
        self.assertEqual(c[-1].receive_ns, 1649760000000)
        self.assertTrue(all(r.status == 'delivered' for r in c))
        # With the arrival deadline, only six of B's 30 residual packets
        # can arrive by 5400 s after waiting for contact two.
        self.assertEqual(sum(r.status == 'delivered' for r in b), 156)

    def test_contact_finish_boundary(self):
        d = 4832000000
        records = simulate([2700*NS-d, 2700*NS-d+1], SIZES['C'])
        self.assertEqual(records[0].finish_ns, 2700*NS)
        self.assertEqual(records[1].start_ns, 4500*NS)

    def test_deadline_equality_and_one_ns_late(self):
        cfg = replace(Config(), deadline_ns=790*NS)
        # D service 0.416 s: at start of gap, earliest receive is 5280.416 s.
        arrival = 4490416000000
        self.assertEqual(simulate([arrival], 104, cfg)[0].status, 'delivered')
        self.assertEqual(simulate([arrival-1], 104, cfg)[0].status, 'expired')

    def test_receive_can_be_outside_ground_contact(self):
        r = simulate([2600*NS], 104)[0]
        self.assertGreater(r.receive_ns, 2700*NS)
        self.assertEqual(r.status, 'delivered')

    def test_drain_and_observation_are_distinct(self):
        records = simulate([86399*NS], 104)
        m = metrics(records)
        self.assertEqual(m['delivered'], 1)
        self.assertEqual(m['received_24h'], 0)
        self.assertEqual(m['throughput_bps'], 0)

    def test_observation_excludes_exact_24h(self):
        arrival = 86400*NS - 780*NS - 416000000
        r = simulate([arrival], 104)
        self.assertEqual(r[0].receive_ns, 86400*NS)
        self.assertEqual(metrics(r)['received_24h'], 0)

    def test_future_feasibility_drop_consumes_no_service(self):
        cfg = replace(Config(), deadline_ns=1000*NS)
        records = simulate([2700*NS, 4400*NS], 104, cfg)
        self.assertEqual(records[0].status, 'expired')
        self.assertEqual(records[0].decision_ns, 2700*NS)
        self.assertEqual(records[1].start_ns, 4500*NS)

    def test_queues_exclude_in_service(self):
        r = simulate([0, 0, NS], 104)
        self.assertEqual(queue_trace(r), [(0, 1), (416000000, 0), (NS, 0)])

    def test_bursts_retain_backlog_and_have_twenty_batches(self):
        cfg = Config()
        a = burst_arrivals(180)
        self.assertEqual(len(a), 3600)
        self.assertEqual(a[-1], 85500*NS)
        r = simulate(a, SIZES['B'])
        self.assertEqual(r[150].start_ns, 4500*NS)
        self.assertEqual(r[180].start_ns, 4500*NS + 6*17940000000)
        m = metrics(r)
        self.assertEqual(m['generated'], m['delivered'] + m['expired'])

    def test_poisson_reproducibility(self):
        a = poisson_arrivals(30, 99)
        self.assertEqual(a, poisson_arrivals(30, 99))
        self.assertNotEqual(a, poisson_arrivals(30, 100))
        self.assertEqual(a, sorted(a))
        self.assertLess(a[-1], Config().observation_ns)

    def test_fcfs_against_independent_tick_reference(self):
        # Independent small integer-time oracle: explicit arrivals, completions
        # and slot decisions at every tick; no production scheduling functions.
        cfg = Config(bandwidth_bps=8*NS, contact_ns=7, gap_ns=3,
                     propagation_ns=2, deadline_ns=12, observation_ns=40)
        for seed in range(30):
            rng = random.Random(seed)
            arrivals = sorted(rng.randrange(40) for _ in range(30))
            waiting = []
            expected = {}
            busy_until = -1
            next_id = 0
            for tick in range(100):
                while next_id < len(arrivals) and arrivals[next_id] == tick:
                    waiting.append(next_id)
                    next_id += 1
                if tick < busy_until:
                    continue
                while waiting:
                    i = waiting[0]
                    feasible = [s for s in range(tick, arrivals[i]+13)
                                if s % 10 + 3 <= 7 and s+3+2 <= arrivals[i]+12]
                    if not feasible:
                        expected[i] = ('expired', None, None)
                        waiting.pop(0)
                    elif feasible[0] == tick:
                        expected[i] = ('delivered', tick, tick+5)
                        waiting.pop(0)
                        busy_until = tick+3
                        break
                    else:
                        break
            actual = simulate(arrivals, 3, cfg)
            self.assertEqual(len(expected), len(actual))
            self.assertEqual([(r.status, r.start_ns, r.receive_ns) for r in actual],
                             [expected[i] for i in range(len(arrivals))])


if __name__ == '__main__':
    unittest.main()
