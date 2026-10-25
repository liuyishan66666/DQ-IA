"""Executable interpretation of chapter 5; wire encoding is a prototype choice.

Provisioned keys are in process memory. SQLite persists sequence reservations,
replay state and accepted pending plaintexts, NOT private keys. Use trusted local
storage. Python cannot promise secret zeroization. This is research software.
"""
from dataclasses import dataclass
import hashlib
import hmac
import secrets
import sqlite3
import struct
import threading

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from pqcrypto.kem import ml_kem_768

MAX_SEQ = (1 << 64) - 1
HEADER = struct.Struct('>4sBBHIQ16sI')
MAX_PLAINTEXT = 4096


class Rejected(Exception):
    """No cryptographic accept event occurred."""


def u32(value):
    return value.to_bytes(4, 'big')


def u64(value):
    return value.to_bytes(8, 'big')


def encode(*fields):
    """Each byte string has a uint32 big-endian length prefix, including labels.

    Integers first become fixed-width big-endian bytes via u32/u64. This is one
    explicit unambiguous encoding consistent with the paper, not a BPv7 codec.
    """
    return b''.join(u32(len(field)) + field for field in fields)


def hkdf(ikm, salt, info):
    # RFC 5869 extract then one SHA-256 expand block for 32 output bytes.
    prk = hmac.digest(salt, ikm, 'sha256')
    return hmac.digest(prk, info + b'\x01', 'sha256')


@dataclass(frozen=True)
class PublicProvision:
    ctx: bytes
    epoch: int
    pk: bytes
    root: bytes

    def __post_init__(self):
        if not 0 <= self.epoch < 1 << 32:
            raise ValueError('Epoch out of uint32 range')
        if (len(self.pk), len(self.root)) != (1184, 32):
            raise ValueError('Invalid provisioned key lengths')
        if not self.ctx:
            raise ValueError('Missing context')


@dataclass(frozen=True)
class Provision(PublicProvision):
    sk: bytes

    def __post_init__(self):
        super().__post_init__()
        if len(self.sk) != 2400:
            raise ValueError('Invalid provisioned private key length')


def setup():
    pk, sk = ml_kem_768.generate_keypair()
    ctx = encode(b'DQIA-v1', b'ground-1', b'probe-1', b'MLKEM768-CHACHA20POLY1305-HMAC128')
    return Provision(ctx, 0, pk, secrets.token_bytes(32), sk)


@dataclass(frozen=True)
class Packet:
    epoch: int
    seq: int
    r: bytes
    ct: bytes
    cipher: bytes
    tag: bytes

    def serialize(self, ctx):
        if len(self.r) != 16 or len(self.ct) != 1088 or len(self.tag) != 16:
            raise ValueError('Invalid fixed field length')
        if not 16 <= len(self.cipher) <= MAX_PLAINTEXT + 16:
            raise ValueError('Invalid ciphertext length')
        header = HEADER.pack(b'DQIA', 1, 1, 0, self.epoch, self.seq,
                             hashlib.sha256(ctx).digest()[:16], len(self.cipher))
        return header + self.r + self.ct + self.cipher + self.tag


def parse(wire, ctx):
    if not isinstance(wire, bytes) or len(wire) < HEADER.size + 16 + 1088 + 16 + 16:
        raise Rejected('parse')
    magic, version, suite, flags, epoch, seq, binding, length = HEADER.unpack_from(wire)
    if (magic, version, suite, flags) != (b'DQIA', 1, 1, 0):
        raise Rejected('header')
    if binding != hashlib.sha256(ctx).digest()[:16]:
        raise Rejected('context')
    if not 16 <= length <= MAX_PLAINTEXT + 16 or len(wire) != HEADER.size + 1120 + length:
        raise Rejected('length')
    body = wire[HEADER.size:]
    return Packet(epoch, seq, body[:16], body[16:1104], body[1104:-16], body[-16:])


def mac_tag(p, packet):
    key = hkdf(p.root, bytes(32), encode(b'mac', p.ctx, u32(packet.epoch), u64(packet.seq)))
    data = encode(b'command', p.ctx, u32(packet.epoch), u64(packet.seq),
                  packet.r, packet.ct, packet.cipher)
    return hmac.digest(key, data, 'sha256')[:16]


def session_key(p, packet, shared):
    return hkdf(shared, packet.r, encode(b'session', p.ctx, p.pk, packet.ct,
                                         u32(packet.epoch), u64(packet.seq)))


def associated_data(p, packet):
    return encode(p.ctx, u32(packet.epoch), u64(packet.seq), packet.r, packet.ct)


class Store:
    """One trusted SQLite DB per endpoint, restartable with the SAME provision.

    BEGIN IMMEDIATE serializes receivers even across connections. Each accepted
    command is stored atomically with the bitmap before receive returns.
    No claim is made for hostile disk rollback or crash recovery testing.
    """
    def __init__(self, path, provision, width=64):
        if not 1 <= width <= 4096:
            raise ValueError('Unsupported replay window')
        self.width = width
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, binding TEXT, q TEXT, h TEXT, bitmap TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS pending (seq TEXT PRIMARY KEY, plaintext BLOB NOT NULL)')
        binding = hashlib.sha256(encode(provision.ctx, u32(provision.epoch), provision.pk, u32(width))).hexdigest()
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('INSERT OR IGNORE INTO state VALUES (1, ?, ?, ?, ?)',
                                (binding, '0', '-1', '0'))
                if self.db.execute('SELECT binding FROM state WHERE id=1').fetchone()[0] != binding:
                    raise ValueError('Database provision mismatch; use trusted new state for a new configuration')
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                self.db.close()
                raise

    def reserve(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                seq = int(self.db.execute('SELECT q FROM state WHERE id=1').fetchone()[0])
                if seq > MAX_SEQ:
                    raise Rejected('counter_exhausted')
                self.db.execute('UPDATE state SET q=? WHERE id=1', (str(seq + 1),))
                self.db.execute('COMMIT')
                return seq
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def snapshot(self):
        row = self.db.execute('SELECT q,h,bitmap FROM state WHERE id=1').fetchone()
        return tuple(map(int, row))

    def pending(self):
        return self.db.execute('SELECT seq,plaintext FROM pending').fetchall()

    def close(self):
        self.db.close()


def fresh(seq, high, bitmap, width):
    return (high < 0 or seq > high or
            (seq >= max(0, high - width + 1) and not bitmap & (1 << (high - seq))))


def mark(seq, high, bitmap, width):
    if high < 0:
        return seq, 1
    if seq > high:
        shift = seq - high
        # Avoid unbounded shifts for attacker-selected 64-bit jumps.
        return seq, ((bitmap << shift) | 1) & ((1 << width)-1) if shift < width else 1
    return high, bitmap | (1 << (high-seq))


class Sender:
    def __init__(self, provision, store):
        self.p = PublicProvision(provision.ctx, provision.epoch, provision.pk, provision.root)
        self.store = store

    def send(self, plaintext):
        if not isinstance(plaintext, bytes) or len(plaintext) > MAX_PLAINTEXT:
            raise ValueError('Invalid plaintext')
        seq = self.store.reserve()  # Commit BEFORE encapsulation or encryption.
        ct, shared = ml_kem_768.encrypt(self.p.pk)
        packet = Packet(self.p.epoch, seq, secrets.token_bytes(16), ct, b'', bytes(16))
        key = session_key(self.p, packet, shared)
        cipher = ChaCha20Poly1305(key).encrypt(u32(packet.epoch) + u64(seq), plaintext,
                                               associated_data(self.p, packet))
        packet = Packet(packet.epoch, seq, packet.r, ct, cipher, bytes(16))
        packet = Packet(packet.epoch, seq, packet.r, ct, cipher, mac_tag(self.p, packet))
        return packet.serialize(self.p.ctx)


class Receiver:
    def __init__(self, provision, store):
        self.p, self.store = provision, store
        self.decapsulation_calls = 0

    def receive(self, wire, business_check=lambda plaintext: True):
        packet = parse(wire, self.p.ctx)
        with self.store.lock:
            db = self.store.db
            db.execute('BEGIN IMMEDIATE')
            try:
                _, high, bitmap = self.store.snapshot()
                if packet.epoch != self.p.epoch:
                    raise Rejected('epoch')
                if not fresh(packet.seq, high, bitmap, self.store.width):
                    raise Rejected('replay')
                if not hmac.compare_digest(packet.tag, mac_tag(self.p, packet)):
                    raise Rejected('mac')
                self.decapsulation_calls += 1
                shared = ml_kem_768.decrypt(self.p.sk, packet.ct)
                key = session_key(self.p, packet, shared)
                try:
                    plaintext = ChaCha20Poly1305(key).decrypt(
                        u32(packet.epoch) + u64(packet.seq), packet.cipher, associated_data(self.p, packet))
                except InvalidTag as exc:
                    raise Rejected('aead') from exc
                if not business_check(plaintext):
                    raise Rejected('business')
                high, bitmap = mark(packet.seq, high, bitmap, self.store.width)
                db.execute('UPDATE state SET h=?,bitmap=? WHERE id=1', (str(high), str(bitmap)))
                db.execute('INSERT INTO pending VALUES (?,?)', (str(packet.seq), plaintext))
                db.execute('COMMIT')
                return plaintext  # accept_cmd only after COMMIT succeeds.
            except BaseException:
                if db.in_transaction:
                    db.execute('ROLLBACK')
                raise
