import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from sandbox import load_workflow, render_html, simulate


def task(key, **kwargs):
    return {'id': key, **kwargs}


def run(tasks, slots=2):
    return simulate({'tasks': tasks, 'max_parallel': slots})


class WorkflowTests(unittest.TestCase):
    def test_dependency_waits_for_success(self):
        r = run([task('a', duration=3), task('b', duration=2, depends_on=['a'])])
        self.assertEqual(r['tasks']['b']['first_start'], 3)
        self.assertEqual(r['makespan'], 5)
        self.assertTrue(r['all_succeeded'])

    def test_parallel_capacity(self):
        r = run([task(str(i), duration=2) for i in range(5)], 2)
        active = 0
        peak = 0
        for event in r['events']:
            if event['event'] == 'start':
                active += 1
                peak = max(peak, active)
            elif event['event'] in ('success', 'error'):
                active -= 1
            self.assertLessEqual(active, 2)
        self.assertEqual((active, peak, r['makespan']), (0, 2, 6))

    def test_retry_delay_releases_slot(self):
        r = run([task('a', duration=2, outcomes=['error', 'success'], max_attempts=2, retry_delay=3), task('b', duration=3)], 1)
        starts = [(e['time'], e['task']) for e in r['events'] if e['event'] == 'start']
        self.assertEqual(starts, [(0,'a'), (2,'b'), (5,'a')])
        self.assertEqual(r['makespan'], 7)

    def test_zero_delay_retry(self):
        r = run([task('a', outcomes=['error', 'success'], max_attempts=2)])
        self.assertEqual(r['makespan'], 2)
        self.assertEqual(r['tasks']['a']['attempts'], 2)

    def test_retry_cap_and_transitive_block(self):
        r = run([task('a', outcomes=['error'], max_attempts=3), task('b', depends_on=['a']), task('c', depends_on=['b'])])
        self.assertFalse(r['all_succeeded'])
        self.assertEqual(r['tasks']['a']['attempts'], 3)
        self.assertEqual(r['tasks']['c']['status'], 'blocked')
        self.assertEqual(r['tasks']['c']['attempts'], 0)
        self.assertEqual(r['makespan'], 3)

    def test_simultaneous_completion_precedes_start(self):
        r = run([task('a'), task('b'), task('c', depends_on=['a','b'])])
        events = [e['event'] for e in r['events'] if e['time']==1]
        self.assertEqual(events, ['success', 'success', 'start'])
        self.assertEqual(r['tasks']['c']['first_start'], 1)

    def test_independent_branch_continues_after_failure(self):
        r = run([task('a', outcomes=['error']), task('b', duration=5)])
        self.assertEqual(r['tasks']['b']['status'], 'success')
        self.assertEqual(r['makespan'], 5)

    def test_order_independent_and_input_unchanged(self):
        data = {'tasks':[task('b'),task('a')]}
        original = copy.deepcopy(data)
        r = simulate(data)
        self.assertEqual(data, original)
        self.assertEqual(r, simulate({'tasks':list(reversed(data['tasks']))}))
        self.assertEqual(r['events'][0]['task'], 'a')

    def test_missing_dependency(self):
        with self.assertRaises(ValueError):
            run([task('a', depends_on=['missing'])])

    def test_cycle_and_self_cycle(self):
        for tasks in ([task('a', depends_on=['a'])], [task('a',depends_on=['b']), task('b',depends_on=['a'])]):
            with self.assertRaises(ValueError):
                run(tasks)

    def test_bad_ids_and_duplicates(self):
        for tasks in ([task('a'),task('a')], [task('../command')], [task('')]):
            with self.assertRaises(ValueError):
                run(tasks)

    def test_invalid_limits_and_outcomes(self):
        for t in (task('a', duration=True), task('a', duration=0), task('a', max_attempts=6), task('a', retry_delay=-1), task('a', outcomes=['maybe']), task('a', depends_on=['b','b'])):
            with self.assertRaises(ValueError):
                run([t])
        with self.assertRaises(ValueError):
            run([task('a')], 0)

    def test_empty_and_duplicate_json_rejected(self):
        with self.assertRaises(ValueError):
            run([])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'bad.json'
            p.write_text('{"tasks":[],"tasks":[]}')
            with self.assertRaises(ValueError):
                load_workflow(p)

    def test_html_report(self):
        text = render_html(run([task('a',outcomes=['error'])]))
        self.assertIn('failed', text)
        self.assertIn('Traza cronológica', text)
        self.assertNotIn('<script', text)

    def test_cli_exit_codes_and_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, j, h = [Path(tmp)/s for s in ('workflow.json','report.json','report.html')]
            base = [sys.executable, str(Path(__file__).with_name('sandbox.py')), str(p)]
            p.write_text(json.dumps({'tasks':[task('a')]}))
            self.assertEqual(subprocess.run(base, capture_output=True).returncode, 0)
            text = json.dumps({'tasks':[task('a',outcomes=['error'])]})
            p.write_text(text)
            r = subprocess.run(base+['--json',str(j),'--html',str(h)], capture_output=True)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertFalse(json.loads(j.read_text())['all_succeeded'])
            self.assertTrue(h.exists())
            self.assertEqual(subprocess.run(base+['--json',str(p)], capture_output=True).returncode, 2)
            self.assertEqual(p.read_text(), text)


if __name__=='__main__':
    unittest.main()
