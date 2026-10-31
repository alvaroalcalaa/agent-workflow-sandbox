"""Deterministic virtual-time sandbox for agent workflow failure scenarios."""
import argparse
import heapq
import html
import json
from pathlib import Path
import re
import sys


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label} debe ser entero entre {low} y {high}')
    return value


def validate(data):
    if not isinstance(data, dict) or not isinstance(data.get('tasks'), list) or not 1 <= len(data['tasks']) <= 100:
        raise ValueError('Se requieren entre 1 y 100 tareas')
    parallel = integer(data.get('max_parallel', 2), 1, 16, 'max_parallel')
    tasks = {}
    for item in data['tasks']:
        if not isinstance(item, dict):
            raise ValueError('Tarea no válida')
        key = item.get('id')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', key) or key in tasks:
            raise ValueError('ID inválido o duplicado')
        deps = item.get('depends_on', [])
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps):
            raise ValueError('depends_on debe ser una lista de IDs únicos')
        outcomes = item.get('outcomes', ['success'])
        if not isinstance(outcomes, list) or not 1 <= len(outcomes) <= 5 or any(x not in ('success', 'error') for x in outcomes):
            raise ValueError('outcomes debe tener de 1 a 5 resultados success/error')
        tasks[key] = {'depends_on': sorted(deps), 'outcomes': list(outcomes),
            'duration': integer(item.get('duration', 1), 1, 3600, 'duration'),
            'max_attempts': integer(item.get('max_attempts', 1), 1, 5, 'max_attempts'),
            'retry_delay': integer(item.get('retry_delay', 0), 0, 3600, 'retry_delay')}
    for key, task in tasks.items():
        if any(d not in tasks for d in task['depends_on']):
            raise ValueError('Dependencia inexistente en ' + key)
    visited, active = set(), set()
    def visit(key):
        if key in active:
            raise ValueError('El grafo contiene un ciclo')
        if key in visited:
            return
        active.add(key)
        for dep in tasks[key]['depends_on']:
            visit(dep)
        active.remove(key)
        visited.add(key)
    for key in tasks:
        visit(key)
    return tasks, parallel


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('Clave JSON repetida: ' + key)
        obj[key] = value
    return obj


def load_workflow(path):
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('La entrada supera 1 MiB')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)


def simulate(data):
    tasks, parallel = validate(data)
    state = {key: {'status': 'pending', 'attempts': 0, 'first_start': None, 'finished_at': None}
             for key in sorted(tasks)}
    eligible_at = {key: 0 for key in tasks}
    running, events = [], []
    now = 0
    def emit(key, event, **extra):
        events.append({'time': now, 'task': key, 'event': event, **extra})
    while True:
        # Complete all simultaneous attempts before deciding which tasks to start.
        while running and running[0][0] == now:
            _, key = heapq.heappop(running)
            task, s = tasks[key], state[key]
            outcome = task['outcomes'][min(s['attempts'] - 1, len(task['outcomes']) - 1)]
            emit(key, outcome, attempt=s['attempts'])
            if outcome == 'success':
                s.update(status='success', finished_at=now)
            elif s['attempts'] < task['max_attempts']:
                s['status'] = 'pending'
                eligible_at[key] = now + task['retry_delay']
                emit(key, 'retry_scheduled', eligible_at=eligible_at[key])
            else:
                s.update(status='failed', finished_at=now)
        changed = True
        while changed:
            changed = False
            for key in state:
                s = state[key]
                failed = [d for d in tasks[key]['depends_on'] if state[d]['status'] in ('failed', 'blocked')]
                if s['status'] == 'pending' and failed:
                    s.update(status='blocked', finished_at=now)
                    emit(key, 'blocked', dependencies=failed)
                    changed = True
        for key in state:  # IDs sorted lexicographically: deterministic tie-breaking.
            s, task = state[key], tasks[key]
            ready = all(state[d]['status'] == 'success' for d in task['depends_on'])
            if s['status'] == 'pending' and ready and eligible_at[key] <= now and len(running) < parallel:
                s['status'] = 'running'
                s['attempts'] += 1
                if s['first_start'] is None:
                    s['first_start'] = now
                heapq.heappush(running, (now + task['duration'], key))
                emit(key, 'start', attempt=s['attempts'])
        future = [running[0][0]] if running else []
        if len(running) < parallel:
            future += [eligible_at[key] for key, s in state.items()
                       if s['status'] == 'pending' and eligible_at[key] > now
                       and all(state[d]['status'] == 'success' for d in tasks[key]['depends_on'])]
        if not future:
            break
        now = min(future)
    ok = all(s['status'] == 'success' for s in state.values())
    assert all(s['status'] in ('success', 'failed', 'blocked') for s in state.values())
    return {'all_succeeded': ok, 'makespan': now, 'max_parallel': parallel, 'tasks': state,
            'events': events, 'notice': 'Simulación de tiempo virtual; no ejecuta herramientas, modelos ni llamadas de red.'}


def render_html(report):
    rows = []
    colors = {'success': '#7ee3a2', 'failed': '#ff8d8d', 'blocked': '#ffd77a'}
    for key, task in report['tasks'].items():
        values = (key, task['status'], task['attempts'], task['first_start'], task['finished_at'])
        rows.append('<tr style="color:' + colors[task['status']] + '">' + ''.join('<td>' + html.escape(str(v)) + '</td>' for v in values) + '</tr>')
    return ('<!doctype html><html lang="es"><meta charset="utf-8"><title>Agent Workflow Sandbox</title>'
            '<style>body{font:16px system-ui;background:#111827;color:#e5e7eb;max-width:1000px;margin:40px auto;padding:20px}'
            'table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #475569}pre{white-space:pre-wrap}</style>'
            '<h1>Agent Workflow Sandbox</h1><p>Duración virtual: ' + str(report['makespan']) + '</p><p>' + html.escape(report['notice'])
            + '</p><table><tr><th>Tarea</th><th>Estado</th><th>Intentos</th><th>Inicio</th><th>Fin / bloqueo</th></tr>'
            + ''.join(rows) + '</table><h2>Traza cronológica</h2><pre>' + html.escape(json.dumps(report['events'], ensure_ascii=False, indent=2)) + '</pre></html>')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workflow', type=Path)
    parser.add_argument('--json', dest='json_path', type=Path)
    parser.add_argument('--html', dest='html_path', type=Path)
    args = parser.parse_args(argv)
    try:
        outputs = [p.resolve() for p in (args.json_path, args.html_path) if p]
        if args.workflow.resolve() in outputs or len(set(outputs)) != len(outputs):
            raise ValueError('Las salidas deben ser distintas y no sobrescribir la entrada')
        report = simulate(load_workflow(args.workflow))
        encoded = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        if args.json_path:
            args.json_path.write_text(encoded, encoding='utf-8')
        if args.html_path:
            args.html_path.write_text(render_html(report), encoding='utf-8')
        print(encoded, end='')
        return 0 if report['all_succeeded'] else 1
    except (ValueError, OSError, RecursionError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
