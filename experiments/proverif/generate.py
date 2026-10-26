"""Generate auditable ProVerif 2.05 models; no tool outcomes are pre-filled.

Unbounded core intentionally omits replay state. The finite state model uses
two fixed unique public sequence identifiers and three sequential input trials.
Replay tests are thus bounded, not a proof of arbitrary uint64 sliding windows.
"""
import json
from pathlib import Path

COMMON = r'''
(* DQ-IA chapter 5, ideal symbolic primitives, fixed trusted context/epoch.
   See README.md for assumptions and the bounded replay-state abstraction. *)
type skey.
type pkey.
type coins.
type flag.
free net: channel.
free ctx, epoch, seq0, seq1, zeroSalt, forgedCommand: bitstring.
free attackerCoins: coins.
free no, yes: flag.
free secretCommand: bitstring [private].

fun pk(skey): pkey.
fun kemct(pkey, coins): bitstring.
fun kemss(pkey, coins): bitstring.
reduc forall sk: skey, z: coins;
  decap(kemct(pk(sk),z),sk) = kemss(pk(sk),z).

(* Extract/Expand are one-way ideal constructors. No numerical security claim. *)
(* Use prefixed identifiers: "expand" is reserved by the ProVerif grammar. *)
fun hkdf_extract(bitstring,bitstring): bitstring.
fun hkdf_expand(bitstring,bitstring): bitstring.
fun sessionInfo(bitstring,pkey,bitstring,bitstring,bitstring): bitstring.
fun macInfo(bitstring,bitstring,bitstring): bitstring.
fun nonce(bitstring,bitstring): bitstring.
fun ad(bitstring,bitstring,bitstring,bitstring,bitstring): bitstring.
fun command(bitstring,bitstring,bitstring,bitstring,bitstring,bitstring): bitstring.
fun mac(bitstring,bitstring): bitstring.
fun aenc(bitstring,bitstring,bitstring,bitstring): bitstring.
reduc forall m:bitstring,k:bitstring,n:bitstring,a:bitstring;
  adec(aenc(m,k,n,a),k,n,a) = m.

event sent(bitstring,bitstring,bitstring,bitstring).
event accepted(bitstring,bitstring,bitstring,bitstring).
event accepted_any().
event accepted_both().

query attacker(secretCommand).
query c:bitstring,e:bitstring,s:bitstring,m:bitstring;
  event(accepted(c,e,s,m)) ==> event(sent(c,e,s,m)).
query c:bitstring,e:bitstring,s:bitstring,m:bitstring;
  inj-event(accepted(c,e,s,m)) ==> inj-event(sent(c,e,s,m)).
(* FALSE is the desired reachability result: acceptance is NOT unreachable. *)
query event(accepted_any()).
'''

SENDER = r'''
let Send(pub:pkey,root:bitstring,s:bitstring) =
  new z:coins;
  new r:bitstring;
  let ct = kemct(pub,z) in
  let ss = kemss(pub,z) in
  let ks = hkdf_expand(hkdf_extract(r,ss),sessionInfo(ctx,pub,ct,epoch,s)) in
  let km = hkdf_expand(hkdf_extract(zeroSalt,root),macInfo(ctx,epoch,s)) in
  let ciphertext = aenc(secretCommand,ks,nonce(epoch,s),ad(ctx,epoch,s,r,ct)) in
  let tag = mac(km,command(ctx,epoch,s,r,ct,ciphertext)) in
  event sent(ctx,epoch,s,secretCommand);
  out(net,(r,ct,epoch,s,ciphertext,tag)).
'''


def auth_body(success, failure, precise=False):
    input_option = ' [precise]' if precise else ''
    return f'''
  in(net,wire:bitstring){input_option};
  let (r:bitstring,ct:bitstring,=epoch,s:bitstring,ciphertext:bitstring,tag:bitstring) = wire in
  let km = hkdf_expand(hkdf_extract(zeroSalt,root),macInfo(ctx,epoch,s)) in
  if tag = mac(km,command(ctx,epoch,s,r,ct,ciphertext)) then
    (let ss = decap(ct,sk) in
     (let ks = hkdf_expand(hkdf_extract(r,ss),sessionInfo(ctx,pk(sk),ct,epoch,s)) in
     (let m = adec(ciphertext,ks,nonce(epoch,s),ad(ctx,epoch,s,r,ct)) in
       ({success})
     else ({failure})))
     else ({failure}))
  else ({failure})
  else ({failure})
'''


def bounded_receiver(replay_guard, precise=False):
    pieces = ['let Receive0(sk:skey,root:bitstring,b0:flag,b1:flag) = 0.\n']
    for attempt in range(1, 4):
        next_name = f'Receive{attempt-1}'
        unchanged = f'{next_name}(sk,root,b0,b1)'
        def accept(other, b0, b1):
            cont = f'{next_name}(sk,root,{b0},{b1})'
            return (f'event accepted(ctx,epoch,s,m); event accepted_any(); '
                    f'if {other}=yes then (event accepted_both(); {cont}) else {cont}')
        accept0, accept1 = accept('b1','yes','b1'), accept('b0','b0','yes')
        if replay_guard:
            accept0 = f'if b0=no then ({accept0}) else {unchanged}'
            accept1 = f'if b1=no then ({accept1}) else {unchanged}'
        success = (f'if s=seq0 then ({accept0}) '
                   f'else if s=seq1 then ({accept1}) else {unchanged}')
        pieces.append(f'let Receive{attempt}(sk:skey,root:bitstring,b0:flag,b1:flag) =\n'
                      + auth_body(success, unchanged, precise) + '.\n')
    return '\n'.join(pieces)


def generate_variant(precise=False):
    directory = Path(__file__).parent/('models_precise' if precise else 'models')
    directory.mkdir(exist_ok=True)
    scenarios = [
        ('bounded_secure', True, None, True, True, True),
        ('bounded_no_replay', False, None, True, True, False),
        ('bounded_root_leak', True, 'root', True, False, False),
        ('bounded_kem_key_leak', True, 'sk', False, True, True),
        ('unbounded_core', None, None, True, True, False),
    ]
    manifest = []
    for name, guard, leak, secrecy, authentication, injective in scenarios:
        expected = {'secrecy': secrecy, 'authentication': authentication,
                    'injective_authentication': injective, 'acceptance_unreachable': False}
        if guard is None:
            receiver = 'let Receive(sk:skey,root:bitstring) =\n' + auth_body(
                'event accepted(ctx,epoch,s,m); event accepted_any(); 0', '0', precise) + '.\n'
            processes = '(! (new s:bitstring; Send(pk(sk),root,s))) | (! Receive(sk,root))'
            extra_query = ''
        else:
            receiver = bounded_receiver(guard, precise)
            processes = 'Send(pk(sk),root,seq0) | Send(pk(sk),root,seq1) | Receive3(sk,root,no,no)'
            extra_query = 'query event(accepted_both()).\n'
            expected['both_acceptances_unreachable'] = False
        exposure = f'out(net,{leak});\n' if leak else ''
        text = (COMMON + extra_query + SENDER + receiver +
                f'\nprocess\n new sk:skey;\n new root:bitstring;\n out(net,pk(sk));\n {exposure}'
                f' ({processes})\n')
        (directory/f'{name}.pv').write_text(text.lstrip(), encoding='utf-8')
        manifest.append({'model': f'{name}.pv', 'expected': expected,
                         'scope': 'unbounded sessions, NO replay state' if guard is None
                         else '2 symbolic sequence slots, 3 sequential reception attempts'})
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return len(manifest)


def main():
    count=generate_variant(False)+generate_variant(True)
    print(f'Generated {count} model specifications (baseline + precise). No ProVerif execution performed.')


if __name__ == '__main__':
    main()
