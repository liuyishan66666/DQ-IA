"""Run real-primitive validation and save shareable evidence (no keys or DBs)."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import io
import json
from pathlib import Path
import platform
import sys
import tempfile
import unittest

from .core import HEADER, Receiver, Rejected, Sender, Store, setup


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes.append({'test': test.id(), 'status': 'passed'})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.outcomes.append({'test': test.id(), 'status': 'failed'})

    def addError(self, test, err):
        super().addError(test, err)
        self.outcomes.append({'test': test.id(), 'status': 'error'})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes.append({'test': test.id(), 'status': 'skipped', 'reason': reason})


def demo():
    p = setup()
    with tempfile.TemporaryDirectory() as temp:
        sender_db = Store(Path(temp)/'ground.db', p)
        receiver_db = Store(Path(temp)/'probe.db', p)
        try:
            sender, receiver = Sender(p, sender_db), Receiver(p, receiver_db)
            plaintext = bytes(range(32))
            wire = sender.send(plaintext)
            recovered = receiver.receive(wire)
            try:
                receiver.receive(wire)
            except Rejected as error:
                replay_rejection = str(error)
            else:
                raise AssertionError('Replay accepted')
            next_wire = bytearray(sender.send(plaintext))
            next_wire[-1] ^= 1
            before = receiver.decapsulation_calls
            try:
                receiver.receive(bytes(next_wire))
            except Rejected as error:
                mac_rejection = str(error)
            else:
                raise AssertionError('Tampering accepted')
            assert recovered == plaintext
            assert replay_rejection == 'replay' and mac_rejection == 'mac'
            assert receiver.decapsulation_calls == before
            return {'plaintext_bytes': len(plaintext), 'wire_bytes': len(wire),
                    'custom_header_bytes': HEADER.size,
                    'roundtrip_matches': recovered == plaintext,
                    'replay_rejected': True, 'invalid_mac_rejected': True,
                    'invalid_mac_decapsulation_calls': receiver.decapsulation_calls-before,
                    'accepted_pending_commands': len(receiver_db.pending())}
        finally:
            sender_db.close()
            receiver_db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('experiments/protocol/results_ubuntu'))
    args = parser.parse_args()
    out = args.output
    if out.exists() and any(out.iterdir()):
        parser.error('Output directory is nonempty. Choose a NEW --output directory to preserve logs.')
    out.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(root/'tests/protocol'))
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=EvidenceResult).run(suite)
    successful = result.testsRun > 0 and result.wasSuccessful() and not result.skipped
    demo_result = None
    demo_error = None
    if successful:
        try:
            demo_result = demo()
        except Exception as exc:
            successful = False
            demo_error = f'{type(exc).__name__}: {exc}'
    log = stream.getvalue()
    (out/'test_run.txt').write_text(log, encoding='utf-8')
    sources = sorted((root/'experiments/protocol').glob('*.py'))
    sources += [root/'experiments/protocol/requirements.txt', root/'tests/protocol/test_protocol.py']
    summary = {
        'status': 'passed' if successful else 'failed',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'runtime': {'python': sys.version, 'platform': platform.platform(),
                    'machine': platform.machine(), 'libc': platform.libc_ver(),
                    'packages': {name: version(name) for name in ['pqcrypto','cryptography','cffi','pycparser','typing_extensions']}},
        'tests_run': result.testsRun,
        'passed': sum(item['status']=='passed' for item in result.outcomes),
        'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'test_outcomes': result.outcomes, 'demo': demo_result, 'demo_error': demo_error,
        'source_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'scope': 'Real ML-KEM/AEAD/MAC protocol functionality and replay-state tests; no formal proof or hardware benchmark',
        'persistent_state': 'Temporary SQLite DBs deleted; no private keys, root keys or DB files in evidence',
    }
    (out/'validation.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(log)
    print(json.dumps({'status': summary['status'], 'tests_run': result.testsRun,
                      'passed': summary['passed'], 'demo': demo_result, 'output': str(out)}, indent=2))
    return 0 if successful else 1


if __name__ == '__main__':
    raise SystemExit(main())
