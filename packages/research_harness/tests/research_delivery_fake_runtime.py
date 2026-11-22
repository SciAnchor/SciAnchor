"""Offline subprocess fixture for an external delivery runtime: interrupted DEFINE followed by an exact released tree."""

from pathlib import Path

FAKE_START = r"""
import argparse, fcntl, hashlib, json, os
from pathlib import Path
from delivery_runtime import VERSION

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))

parser = argparse.ArgumentParser()
for flag in ('research-binding', 'slug', 'episode-id', 'episodes-root', 'max-rounds'):
    parser.add_argument('--' + flag, required=True)
parser.add_argument('--resume', action='store_true')
args = parser.parse_args()
binding = json.loads(Path(args.research_binding).read_text())
fields = ('contract_version','execution_id','execution_mode','ticket_namespace','public_id','topic_id','title','topic_text','target_journal','rh_db_path')
binding = {key: binding[key] for key in fields}
digest = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
episode = Path(args.episodes_root) / args.episode_id
episode.mkdir(exist_ok=True)
lock = int(os.environ['RH_RESEARCH_EXECUTION_LOCK_FD'])
assert os.fstat(lock).st_ino == (Path(args.research_binding).parent / '.execution.lock').stat().st_ino
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
write(episode / 'child.json', {'version': VERSION, 'cwd': str(Path.cwd()), 'resumed': args.resume})
state = {'schema_version': 'external_runtime.state.v1', 'episode_id': episode.name,
         'research_binding_sha256': digest, 'completed': {}}
runtime = json.loads(Path(os.environ['RH_RESEARCH_RUNTIME_MANIFEST']).read_text())
state = {**state, 'research_runtime_sha256': runtime['manifest_sha256'],
         'research_runtime_manifest': os.environ['RH_RESEARCH_RUNTIME_MANIFEST']}
meta = {'episode_id': episode.name, 'research_binding': binding,
        'research_binding_sha256': digest, 'research_contract_path': args.research_binding}
write(episode / 'episode.json', meta)
if not args.resume:
    write(episode / 'state.json', {**state, 'state': 'awaiting_owner', 'stage': 'DEFINE', 'reason': 'offline interruption'})
    raise SystemExit(1)
root = episode / 'final_release'
entries = [('manuscript/main.tex','manuscript_tex',b'paper'),
           ('manuscript/main.pdf','manuscript_pdf',b'pdf'),
           ('manuscript/styles/custom.sty','manuscript_support',b'style'),
           ('code/method.py','paper_algorithm',b'method'),
           ('code/tests/test_method.py','algorithm_test',b'test'),
           ('code/requirements.txt','environment',b'pytest'),
           ('data/results.csv','released_results',b'score\n1\n')]
rows = []
for name, role, data in entries:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    rows.append({'path':name,'role':role,'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)})
(root / 'MANIFEST.sha256').write_text(''.join(f"{r['sha256']}  {r['path']}\n" for r in sorted(rows,key=lambda r:r['path'])))
receipt = episode / '.private-release-records' / (args.slug + '-final.json')
write(receipt, {'schema_version':'external_runtime.final_release_receipt.v1','status':'released','release_name':args.slug,
    'files':rows, 'research_execution':{'research_binding':binding,'execution_mode':'external_simulated','formal_promotion_allowed':False}})
write(episode / 'local_work/stage_results/001_RELEASE.json', {'stage':'RELEASE','status':'ok',
    'output':{'status':'released','private_receipt_path':str(receipt)}})
write(episode / 'state.json', {**state,'state':'released','stage':'AWAITING_REVIEW','completed':{'RELEASE':'offline'}})
"""


def install_fake_runtime(directory: Path):
    rh, runtime = directory / "rh-source", directory / "runtime-source"
    files = {
        rh / "packages/research_harness/research_harness/__init__.py": "VERSION = 1\n",
        runtime / "delivery_runtime/__init__.py": "VERSION = 1\n",
        runtime / "delivery_runtime/start.py": FAKE_START,
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return rh, runtime
