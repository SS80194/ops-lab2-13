import csv
import json
import math
import pathlib
import urllib.parse
import urllib.request

run = pathlib.Path(__file__).resolve().parent

def get(path, params=None):
    url = 'http://127.0.0.1:9090' + path
    if params:
        url += '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=10) as response:
        data = json.load(response)
    assert data['status'] == 'success', data
    return data

def save(name, data):
    (run / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')

targets = get('/api/v1/targets')
save('targets.json', targets)
active = targets['data']['activeTargets']
assert {t['labels']['job'] for t in active} == {'enrolld', 'node'}
assert all(t['health'] == 'up' and not t['lastError'] for t in active)
steps = list(csv.DictReader((run / 'steps.csv').open()))
red = list(csv.DictReader((run / 'red.csv').open()))
use = list(csv.DictReader((run / 'use.csv').open()))
print('steps fields:', ', '.join(steps[0]))
print('red fields:', ', '.join(red[0]))
print('use fields:', ', '.join(use[0]))
checks = {'targets': {t['labels']['job']: t['health'] for t in active}, 'loaded_stages': []}
step_by_id = {r['step']: r for r in steps if r['step'] != 'all'}
use_by_id = {r['step']: r for r in use}
for row in red:
    if float(row['target_rps']) == 0:
        continue
    values = {k: float(row[k]) for k in ['server_rps', 'server_error_rate', 'server_p99_ms', 'server_slo_good', 'cpu_ms_per_req', 'db_query_mean_ms']}
    assert all(math.isfinite(v) for v in values.values()), values
    assert values['server_rps'] > 0
    assert values['server_error_rate'] == 0
    assert 0 <= values['server_slo_good'] <= 1.000001
    assert values['server_p99_ms'] > 0
    assert values['cpu_ms_per_req'] > 0
    assert values['db_query_mean_ms'] >= 10
    client = step_by_id[row['step']]
    assert all(int(client[k]) == 0 for k in ['http_err', 'timeout', 'net_err', 'dropped']), client
    assert int(client['sent']) == int(client['ok'])
    assert not client['warn'], client['warn']
    assert abs(values['server_rps'] - float(client['ok_rps'])) <= max(3, float(client['ok_rps']) * .1)
    assert all(math.isfinite(float(use_by_id[row['step']][k])) for k in ['svc_cpu_busy', 'all_cpu_busy', 'mem_available_min_mb', 'procs_running_avg'])
    checks['loaded_stages'].append({'step': row['step'], 'target_rps': row['target_rps'], **values})
assert len(checks['loaded_stages']) == 2
def request_count(path):
    total = 0
    for line in path.read_text().splitlines():
        if line.startswith('http_requests_total{') and 'route="/api/courses/{id}"' in line:
            total += float(line.rsplit(' ', 1)[1])
    return total
expected = sum(int(r['sent']) for r in step_by_id.values())
delta = request_count(run / 'metrics-end.txt') - request_count(run / 'metrics-start.txt')
assert delta == expected, (delta, expected)
checks['request_counter_delta'] = delta
checks['client_sent_total'] = expected
for filename in ['vmstat.log', 'mpstat.log', 'iostat.log', 'pidstat.log']:
    assert len((run / filename).read_text().splitlines()) > 20, filename
first, last = min(float(r['start_unix']) for r in step_by_id.values()), max(float(r['end_unix']) for r in step_by_id.values())
uptime = get('/api/v1/query_range', {'query': 'up', 'start': first + 5, 'end': last, 'step': 5})
save('up-range.json', uptime)
series = uptime['data']['result']
assert {s['metric']['job'] for s in series} == {'enrolld', 'node'}
assert all(len(s['values']) >= 16 and all(float(v[1]) == 1 for v in s['values']) for s in series)
checks['continuous_up_samples'] = {s['metric']['job']: len(s['values']) for s in series}
save('validation.json', checks)
print(json.dumps(checks, ensure_ascii=False, indent=2))
