"""Real-primitive tests, no mock KEM and no network/hardware claims."""
from dataclasses import replace
import random
import secrets
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from pqcrypto.kem import ml_kem_768
from experiments.protocol.core import (
    HEADER, MAX_SEQ, Packet, Provision, PublicProvision, Receiver, Rejected,
    Sender, Store, fresh, hkdf, mac_tag, mark, parse, setup,
)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p = setup()
        self.s = self.store('sender.db')
        self.r = self.store('receiver.db')
        self.sender = Sender(self.p, self.s)
        self.receiver = Receiver(self.p, self.r)

    def store(self, name, provision=None):
        store = Store(Path(self.temp.name) / name, provision or self.p)
        self.addCleanup(store.close)
        return store

    def resign(self, wire, **updates):
        packet = replace(parse(wire, self.p.ctx), **updates)
        return replace(packet, tag=mac_tag(self.p, packet)).serialize(self.p.ctx)

    def assert_rejected_unchanged(self, wire, reason=None, receiver=None):
        receiver = receiver or self.receiver
        before = receiver.store.snapshot(), receiver.store.pending()
        with self.assertRaises(Rejected) as cm:
            receiver.receive(wire)
        if reason:
            self.assertEqual(str(cm.exception), reason)
        self.assertEqual((receiver.store.snapshot(), receiver.store.pending()), before)

    def test_real_mlkem_encapsulation(self):
        ct, ss = ml_kem_768.encrypt(self.p.pk)
        self.assertEqual((len(ct), len(ss)), (1088, 32))
        self.assertEqual(ml_kem_768.decrypt(self.p.sk, ct), ss)

    def test_hkdf_rfc5869_vector_prefix(self):
        key = hkdf(bytes.fromhex('0b'*22), bytes(range(13)), bytes(range(240,250)))
        self.assertEqual(key.hex(), '3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf')

    def test_sender_has_no_probe_private_key(self):
        self.assertFalse(hasattr(self.sender.p, 'sk'))

    def test_real_roundtrip_and_1208_byte_wire(self):
        message = bytes(range(32))
        wire = self.sender.send(message)
        self.assertEqual(HEADER.size, 40)
        self.assertEqual(len(wire), 1208)
        self.assertEqual(self.receiver.receive(wire), message)
        self.assertEqual(self.r.pending(), [('0', message)])

    def test_zero_and_max_payload(self):
        for n in [0, 4096]:
            msg = secrets.token_bytes(n)
            wire = self.sender.send(msg)
            self.assertEqual(len(wire), n+1176)
            self.assertEqual(self.receiver.receive(wire), msg)

    def test_oversized_plaintext_does_not_reserve(self):
        before = self.s.snapshot()
        with self.assertRaises(ValueError):
            self.sender.send(bytes(4097))
        self.assertEqual(self.s.snapshot(), before)

    def test_truncated_and_extra_bytes(self):
        wire = self.sender.send(b'test')
        for invalid in [b'', wire[:20], wire[:-1], wire+b'x']:
            self.assert_rejected_unchanged(invalid)
        self.assertEqual(self.receiver.decapsulation_calls, 0)

    def test_header_fields_reject_before_kem(self):
        wire = self.sender.send(b'test')
        for offset in [0, 4, 5, 6, 20, 36]:
            changed = bytearray(wire)
            changed[offset] ^= 1
            self.assert_rejected_unchanged(bytes(changed))
        self.assertEqual(self.receiver.decapsulation_calls, 0)

    def test_tampered_r_ct_cipher_and_tag_reject_before_kem(self):
        wire = self.sender.send(b'test')
        for offset in [40, 56, 1144, len(wire)-1]:
            changed = bytearray(wire)
            changed[offset] ^= 1
            self.assert_rejected_unchanged(bytes(changed), 'mac')
        self.assertEqual(self.receiver.decapsulation_calls, 0)

    def test_tampered_seq_does_not_move_window(self):
        wire = self.sender.send(b'test')
        packet = replace(parse(wire, self.p.ctx), seq=MAX_SEQ)
        self.assert_rejected_unchanged(packet.serialize(self.p.ctx), 'mac')
        self.assertEqual(self.r.snapshot()[1], -1)
        self.assertEqual(self.receiver.decapsulation_calls, 0)

    def test_wrong_root(self):
        bad = Receiver(replace(self.p, root=secrets.token_bytes(32)), self.r)
        self.assert_rejected_unchanged(self.sender.send(b'test'), 'mac', bad)
        self.assertEqual(bad.decapsulation_calls, 0)

    def test_wrong_context(self):
        bad = Receiver(replace(self.p, ctx=b'other-mission'), self.r)
        self.assert_rejected_unchanged(self.sender.send(b'test'), 'context', bad)

    def test_wrong_epoch_even_valid_mac_cannot_install_epoch(self):
        wire = self.resign(self.sender.send(b'test'), epoch=1)
        self.assert_rejected_unchanged(wire, 'epoch')
        self.assertEqual(self.p.epoch, 0)
        self.assertEqual(self.receiver.decapsulation_calls, 0)

    def test_wrong_kem_private_key(self):
        _, other_sk = ml_kem_768.generate_keypair()
        bad = Receiver(replace(self.p, sk=other_sk), self.r)
        self.assert_rejected_unchanged(self.sender.send(b'test'), 'aead', bad)
        self.assertEqual(bad.decapsulation_calls, 1)

    def test_authenticated_malformed_kem_implicit_rejection(self):
        wire = self.resign(self.sender.send(b'test'), ct=bytes(1088))
        self.assert_rejected_unchanged(wire, 'aead')
        self.assertEqual(self.receiver.decapsulation_calls, 1)

    def test_authenticated_aead_tamper(self):
        wire = self.sender.send(b'test')
        cipher = bytearray(parse(wire, self.p.ctx).cipher)
        cipher[0] ^= 1
        self.assert_rejected_unchanged(self.resign(wire, cipher=bytes(cipher)), 'aead')

    def test_duplicate_is_rejected_before_kem(self):
        wire = self.sender.send(b'test')
        self.receiver.receive(wire)
        self.assert_rejected_unchanged(wire, 'replay')
        self.assertEqual(self.receiver.decapsulation_calls, 1)

    def test_unseen_in_window_out_of_order(self):
        wires = [self.sender.send(bytes([i])) for i in range(4)]
        for i in [3, 1, 0, 2]:
            self.assertEqual(self.receiver.receive(wires[i]), bytes([i]))
        self.assertEqual(self.r.snapshot()[1:], (3, 15))

    def test_window_lower_boundary_and_one_below(self):
        wires = [self.sender.send(b'x') for _ in range(66)]
        self.receiver.receive(wires[65])
        self.assertEqual(self.receiver.receive(wires[2]), b'x')
        self.assert_rejected_unchanged(wires[1], 'replay')

    def test_large_jump_resets_bitmap(self):
        wire = self.sender.send(b'x')
        self.receiver.receive(wire)
        jump = self.resign(self.sender.send(b'x'), seq=MAX_SEQ)
        # Re-signing does not reencrypt nonce/AD, so this must fail AEAD.
        self.assert_rejected_unchanged(jump, 'aead')
        self.assertEqual(mark(MAX_SEQ, 0, 1, 64), (MAX_SEQ, 1))

    def test_business_failure_does_not_consume_seq(self):
        wire = self.sender.send(b'not-authorized')
        with self.assertRaisesRegex(Rejected, 'business'):
            self.receiver.receive(wire, lambda plaintext: False)
        self.assertEqual(self.r.snapshot()[1:], (-1, 0))
        self.assertEqual(self.r.pending(), [])
        self.assertEqual(self.receiver.receive(wire), b'not-authorized')

    def test_business_callback_exception_rolls_back(self):
        wire = self.sender.send(b'x')
        def fail(_):
            raise ValueError('application error')
        with self.assertRaises(ValueError):
            self.receiver.receive(wire, fail)
        self.assertEqual(self.r.snapshot()[1:], (-1, 0))
        self.assertEqual(self.r.pending(), [])

    def test_pending_write_failure_rolls_back_bitmap(self):
        wire = self.sender.send(b'x')
        self.r.db.execute("CREATE TRIGGER fail_pending BEFORE INSERT ON pending BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            self.receiver.receive(wire)
        self.assertEqual(self.r.snapshot()[1:], (-1, 0))
        self.assertEqual(self.r.pending(), [])
        self.r.db.execute('DROP TRIGGER fail_pending')
        self.assertEqual(self.receiver.receive(wire), b'x')

    def test_commit_failure_does_not_return_accept(self):
        wire = self.sender.send(b'x')
        self.r.db.set_authorizer(lambda action, arg1, *_:
                                sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and arg1 == 'COMMIT'
                                else sqlite3.SQLITE_OK)
        with self.assertRaises(sqlite3.DatabaseError):
            self.receiver.receive(wire)
        # Python 3.10 does not support disabling an authorizer with None.
        self.r.db.set_authorizer(lambda *_: sqlite3.SQLITE_OK)
        self.assertEqual(self.r.snapshot()[1:], (-1, 0))
        self.assertEqual(self.r.pending(), [])
        self.assertEqual(self.receiver.receive(wire), b'x')

    def test_reserved_sequence_is_not_reused_after_crypto_failure(self):
        with patch('experiments.protocol.core.ml_kem_768.encrypt', side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                self.sender.send(b'x')
        self.assertEqual(self.s.snapshot()[0], 1)
        self.assertEqual(parse(self.sender.send(b'x'), self.p.ctx).seq, 1)

    def test_reservation_failure_does_not_encapsulate(self):
        self.s.db.execute("CREATE TRIGGER fail_reserve BEFORE UPDATE ON state BEGIN SELECT RAISE(ABORT, 'injected'); END")
        with patch('experiments.protocol.core.ml_kem_768.encrypt') as kem:
            with self.assertRaises(sqlite3.DatabaseError):
                self.sender.send(b'x')
            kem.assert_not_called()
        self.assertEqual(self.s.snapshot()[0], 0)

    def test_uint64_last_value_and_no_wrap(self):
        self.s.db.execute('UPDATE state SET q=?', (str(MAX_SEQ),))
        wire = self.sender.send(b'last')
        self.assertEqual(parse(wire, self.p.ctx).seq, MAX_SEQ)
        self.assertEqual(self.receiver.receive(wire), b'last')
        with self.assertRaisesRegex(Rejected, 'counter_exhausted'):
            self.sender.send(b'wrap')
        self.assertEqual(self.s.snapshot()[0], MAX_SEQ+1)

    def test_epoch_range_validation(self):
        for invalid in [-1, 1 << 32]:
            with self.assertRaises(ValueError):
                replace(self.p, epoch=invalid)

    def test_reopen_preserves_counter_and_replay(self):
        wire = self.sender.send(b'x')
        self.receiver.receive(wire)
        # Additional connections simulate graceful reopen with the same keys.
        s2 = self.store('sender.db')
        r2 = self.store('receiver.db')
        self.assertEqual(parse(Sender(self.p,s2).send(b'y'),self.p.ctx).seq, 1)
        self.assert_rejected_unchanged(wire, 'replay', Receiver(self.p,r2))

    def test_database_rejects_different_public_context(self):
        with self.assertRaises(ValueError):
            Store(Path(self.temp.name)/'receiver.db', replace(self.p,ctx=b'other'))

    def test_parallel_replay_only_one_accept(self):
        wire = self.sender.send(b'x')
        other = Receiver(self.p,self.store('receiver.db'))
        def receive(receiver):
            try:
                receiver.receive(wire)
                return True
            except Rejected:
                return False
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sum(pool.map(receive, [self.receiver,other])), 1)
        self.assertEqual(len(self.r.pending()), 1)

    def test_root_compromise_allows_forgery_without_private_key(self):
        # Expected security boundary, NOT an attack that this protocol prevents.
        public = PublicProvision(self.p.ctx,self.p.epoch,self.p.pk,self.p.root)
        forged = Sender(public,self.store('attacker.db')).send(b'forged')
        self.assertEqual(self.receiver.receive(forged), b'forged')

    def test_bitmap_matches_independent_set_model(self):
        rng = random.Random(1234)
        high, bitmap, accepted = -1, 0, set()
        for _ in range(3000):
            seq = rng.randrange(500)
            expected = seq not in accepted and (high < 0 or seq >= max(0, high-63))
            self.assertEqual(fresh(seq,high,bitmap,64), expected)
            if expected:
                accepted.add(seq)
                high,bitmap = mark(seq,high,bitmap,64)
                self.assertEqual(bitmap, sum(1 << (high-x) for x in accepted if 0 <= high-x < 64))


if __name__ == '__main__':
    unittest.main()
