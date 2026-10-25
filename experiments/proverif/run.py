"""Run installed ProVerif, retain full logs, distinguish expectations from results."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys


def parse_results(output):
    parsed = {}
    for line in output.splitlines():
        if not line.startswith('RESULT '):
            continue
        # ProVerif 2.05 supplements injective results with parenthesized notes
        # about a weaker non-injective query. They are not separate results.
        # In particular, a TRUE weaker query must never replace an unresolved
        # injective query. Standalone query lines remain authoritative.
        if re.match(r'^RESULT \((?:but|even) ', line):
            continue
        if re.search(r' is true\.?$', line):
            value = True
        elif re.search(r' is false\.?$', line):
            value = False
        else:
            value = None  # "cannot be proved" is unresolved, never success.
        if 'accepted_both' in line:
            key = 'both_acceptances_unreachable'
        elif 'accepted_any' in line:
            key = 'acceptance_unreachable'
        elif 'attacker(secretCommand' in line:
            key = 'secrecy'
        elif 'inj-event(accepted(' in line:
            key = 'injective_authentication'
        elif 'event(accepted(' in line:
            key = 'authentication'
        else:
            raise ValueError('Unrecognized RESULT line: ' + line)
        # Some tool modes can repeat identical summary lines. Conflicts fail.
        if key in parsed and parsed[key]['observed'] != value:
            raise ValueError('Conflicting results for ' + key)
        parsed[key] = {'observed': value, 'tool_result': line}
    return parsed


def judge(expected, parsed, returncode, timed_out=False):
    checks = {key: {'expected': value, 'observed': parsed.get(key,{}).get('observed'),
                    'matches': key in parsed and parsed[key]['observed'] is value}
              for key,value in expected.items()}
    passed = (returncode == 0 and not timed_out and set(parsed) == set(expected)
              and all(c['matches'] for c in checks.values()))
    return passed, checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proverif', default='proverif', help='Executable name or absolute path')
    parser.add_argument('--output', type=Path, default=Path('experiments/proverif/results_ubuntu'))
    parser.add_argument('--timeout', type=int, default=180, help='Seconds per model')
    args = parser.parse_args()
    executable = shutil.which(args.proverif)
    if not executable:
        parser.error('ProVerif not found. Activate your existing opam environment or supply --proverif PATH.')
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Output directory is nonempty. Use a new --output directory.')
    args.output.mkdir(parents=True, exist_ok=True)
    models = Path(__file__).parent/'models'
    specifications = json.loads((models/'manifest.json').read_text())
    try:
        help_result = subprocess.run([executable,'-help'],capture_output=True,text=True,timeout=10)
        help_text = help_result.stdout + help_result.stderr
    except (OSError,subprocess.TimeoutExpired) as exc:
        help_text = f'Unable to collect help/version: {exc}'
    # The version banner can include a person's name; no environment/secret dump.
    banner = next((line for line in help_text.splitlines() if 'proverif' in line.lower()), 'unknown')
    (args.output/'tool_version.txt').write_text(banner+'\n',encoding='utf-8')
    results = []
    for specification in specifications:
        model = models/specification['model']
        command = [executable,'-in','pitype',str(model.resolve())]
        timed_out = False
        try:
            outcome = subprocess.run(command,capture_output=True,text=True,timeout=args.timeout)
            output, errors, returncode = outcome.stdout,outcome.stderr,outcome.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            output = exc.stdout or b''
            errors = exc.stderr or b''
            if isinstance(output,bytes): output=output.decode(errors='replace')
            if isinstance(errors,bytes): errors=errors.decode(errors='replace')
            errors += '\nRUNNER: model exceeded timeout; results incomplete.\n'
            returncode = None
        except OSError as exc:
            output,errors,returncode = '',str(exc),None
        log = output + ('\nSTDERR:\n'+errors if errors else '')
        log_name = model.stem+'.log'
        (args.output/log_name).write_text(log,encoding='utf-8')
        tool_error = next((line.strip() for line in log.splitlines()
                           if 'Error:' in line or 'RUNNER:' in line), None)
        parse_error = None
        try:
            parsed = parse_results(output)
        except ValueError as exc:
            parsed,parse_error = {},str(exc)
        passed, checks = judge(specification['expected'],parsed,returncode,timed_out)
        if parse_error:
            passed = False
        result = {**specification, 'status': 'matched_expectations' if passed else 'needs_investigation',
                  'returncode': returncode, 'timed_out': timed_out, 'parse_error': parse_error,
                  'tool_error': tool_error,
                  'observed_results': parsed, 'checks': checks, 'log': log_name,
                  'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest()}
        results.append(result)
        print(model.name+': '+result['status'],flush=True)
        for line in output.splitlines():
            if line.startswith('RESULT '):print('  '+line,flush=True)
        if parse_error:
            print('  Result parsing error: '+parse_error,flush=True)
        if not parsed:
            print('  No recognized query result. Read '+str(args.output/log_name),flush=True)
            # Display the initial diagnostic, so users need not locate a log
            # just to identify a parser error. Full output remains in the log.
            for line in log.splitlines()[:12]:
                print('  '+line,flush=True)
            if timed_out:
                print('  Model timed out; no completed conclusion.',flush=True)
    complete = all(r['status']=='matched_expectations' for r in results)
    summary = {'status': 'matched_expectations' if complete else 'needs_investigation',
               'timestamp_utc': datetime.now(timezone.utc).isoformat(),
               'tool_version': banner, 'python':sys.version, 'platform':platform.platform(),
               'models_run':len(results), 'models':results,
               'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'manifest_sha256':hashlib.sha256((models/'manifest.json').read_bytes()).hexdigest(),
               'interpretation':'Expected FALSE in reachability and attack controls is not a failure. Unknown, missing, timeout or parse failure is unresolved.',
               'scope':'Unbounded cryptographic core + bounded 2-slot/3-attempt replay model; not a proof of the complete 64-bit implementation.'}
    (args.output/'validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':summary['status'],'models_run':len(results),'output':str(args.output)},indent=2))
    return 0 if complete else 1


if __name__ == '__main__':
    raise SystemExit(main())
