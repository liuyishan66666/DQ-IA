"""Reparse saved real ProVerif logs without executing or changing any model."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from .run import judge, parse_results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    source=args.source.resolve()
    out=args.output.resolve()
    if source==out or (out.exists() and any(out.iterdir())):
        parser.error('Choose a NEW empty output directory; original logs must be preserved.')
    try:
        original_bytes=(source/'validation.json').read_bytes()
        original=json.loads(original_bytes)
        variant=original.get('variant','baseline')
        if variant not in ['baseline','precise']:
            raise ValueError('Unknown model variant')
        model_root=Path(__file__).parent/('models_precise' if variant=='precise' else 'models')
        specs=json.loads((model_root/'manifest.json').read_text())
        records={record['model']:record for record in original['models']}
        if set(records)!={spec['model'] for spec in specs}:
            raise ValueError('Model membership mismatch; do not combine different experiment revisions.')
        prepared=[]
        for spec in specs:
            old=records[spec['model']]
            digest=hashlib.sha256((model_root/spec['model']).read_bytes()).hexdigest()
            if old['model_sha256']!=digest or old['expected']!=spec['expected']:
                raise ValueError('Model/expected-query revision mismatch: '+spec['model'])
            name=old['log']
            if Path(name).name!=name:
                raise ValueError('Log must be a filename inside source directory')
            raw=(source/name).read_bytes()
            stdout=raw.decode('utf-8').split('\nSTDERR:\n',1)[0]
            parsed=parse_results(stdout)
            passed,checks=judge(spec['expected'],parsed,old['returncode'],old['timed_out'])
            prepared.append(({**old,'observed_results':parsed,'checks':checks,'parse_error':None,
                              'status':'matched_expectations' if passed else 'needs_investigation',
                              'log_sha256':hashlib.sha256(raw).hexdigest()},name,raw))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        parser.error(str(exc))
    out.mkdir(parents=True,exist_ok=True)
    for record,name,raw in prepared:
        (out/name).write_bytes(raw)
        print(record['model']+': '+record['status'])
        for key,value in record['observed_results'].items():
            print('  '+key+': '+('unresolved' if value['observed'] is None else str(value['observed'])))
    if (source/'tool_version.txt').exists():
        shutil.copyfile(source/'tool_version.txt',out/'tool_version.txt')
    summary={**original,'status':'matched_expectations' if all(r['status']=='matched_expectations' for r,_,_ in prepared) else 'needs_investigation',
             'models':[r for r,_,_ in prepared], 'operation':'reparse_saved_logs',
             'proverif_executed_by_reparser':False,
             'reparsed_at_utc':datetime.now(timezone.utc).isoformat(),
             'source_validation_sha256':hashlib.sha256(original_bytes).hexdigest(),
             'reparser_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'parser_sha256':hashlib.sha256(Path(__file__).with_name('run.py').read_bytes()).hexdigest()}
    (out/'validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':summary['status'],'operation':summary['operation'],'output':str(out)},indent=2))
    return 0 if summary['status']=='matched_expectations' else 1


if __name__=='__main__':
    raise SystemExit(main())
