"""Unit tests without networking / provider quota."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

P = Path(__file__).resolve().parents[1] / 'automation' / 'opencode' / 'jira_gate.py'
spec = importlib.util.spec_from_file_location('jira_gate', P)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def issue(key, status='Ready', labels=None, description=None, links=None):
    if labels is None:
        labels=['agent-ready','engine-opencode']
    if description is None:
        description = 'Repository: owner/repo\n## Diseño técnico aprobado\nImplementar la feature con casos de aceptación y pruebas.\n## Dependencias\nNinguna'
    return {'key':key,'fields':{'status':{'name':status},'labels':labels,'description':description,'issuelinks': links or [], 'summary':'Test'}}


class JiraGateTests(unittest.TestCase):
    def setUp(self):
        self.e = patch.dict(os.environ, {'JIRA_PROJECT_KEY':'KAN', 'GITHUB_REPOSITORY':'owner/repo',
                                       'JIRA_READY_STATUS':'Ready', 'JIRA_DONE_STATUS':'Done'}, clear=False)
        self.e.start()
    def tearDown(self): self.e.stop()

    def test_inspect_checks_stale_github_branch(self):
        with patch.object(mod, "github_existing", side_effect=mod.GateError("Remote branch already exists")) as check:
            with self.assertRaisesRegex(mod.GateError, "already exists"):
                mod.validate('KAN-9','inspect',lambda k: issue(k),check_github=True)
            check.assert_called_once_with('KAN-9', 'agent/kan-9')

    def test_no_dep(self):
        x=mod.validate('KAN-9','inspect',lambda k: issue(k),check_github=False)
        self.assertEqual(x['blockers'],[])

    def test_inward_blocks_is_real_blocker(self):
        links=[{'type':{'name':'Blocks','inward':'is blocked by','outward':'blocks'}, 'inwardIssue':{'key':'KAN-8'}}]
        src=issue('KAN-9',links=links)
        get=lambda k: src if k=='KAN-9' else issue('KAN-8',status='Done')
        self.assertEqual(mod.validate('KAN-9','inspect',get,False)['blockers'],['KAN-8'])

    def test_outward_blocks_not_prerequisite(self):
        links=[{'type':{'name':'Blocks','inward':'is blocked by','outward':'blocks'}, 'outwardIssue':{'key':'KAN-8'}}]
        x=mod.validate('KAN-9','inspect',lambda k: issue(k,links=links),False)
        self.assertEqual(x['blockers'],[])

    def test_blocked_in_human_review(self):
        links=[{'type':{'name':'Blocks','inward':'is blocked by','outward':'blocks'}, 'inwardIssue':{'key':'KAN-8'}}]
        get=lambda k: issue(k,links=links) if k=='KAN-9' else issue('KAN-8',status='Human Review')
        with self.assertRaisesRegex(mod.GateError,'not exact'):
            mod.validate('KAN-9','inspect',get,False)

    def test_from_text_dependencies(self):
        desc='Repository: owner/repo\n## Design\nDetailed instructions and acceptance criteria.\n## Dependencias\n- KAN-4\n- KAN-5'
        get=lambda k: issue('KAN-9',description=desc) if k=='KAN-9' else issue(k,status='Done')
        self.assertEqual(mod.validate('KAN-9','inspect',get,False)['blockers'],['KAN-4','KAN-5'])

    def test_stuck_in_progress(self):
        with self.assertRaisesRegex(mod.GateError,'expected Ready'):
            mod.validate('KAN-9','inspect',lambda k:issue(k,status='En curso'),False)

    def test_labels_exclusive(self):
        with self.assertRaisesRegex(mod.GateError,'exactly one'):
            mod.validate('KAN-9','inspect',lambda k:issue(k,labels=['agent-ready','engine-claude','engine-opencode']),False)

    def test_repo_mismatch(self):
        with self.assertRaisesRegex(mod.GateError,'Repository'):
            mod.validate('KAN-9','inspect',lambda k:issue(k,description='Repository: other/foreign\nDetailed approved specification and acceptance tests.'),False)

    def test_project_key_conflict(self):
        with self.assertRaisesRegex(mod.GateError,'not in configured'):
            mod.validate('ABC-2','inspect',lambda k:issue(k),False)

    def test_missing_link_data(self):
        with self.assertRaisesRegex(mod.GateError,'links'):
            mod.blocking_links(None)

    def test_explicit_text_blocker(self):
        self.assertIn('KAN-20', mod.extract_text_blockers('Blocked by KAN-20'))

    def test_never_emit_fake_token_usage(self):
        self.assertEqual(mod.flatten_adf({'type':'doc','content':[{'type':'paragraph','content':[{'type':'text','text':'Repository: owner/repo'}]}]}), 'Repository: owner/repo')

    # Álvaro's KAN board: Ready = Listo, Done = Finalizada (equivalent names).
    def test_listo_equals_ready(self):
        x=mod.validate('KAN-9','inspect',lambda k: issue(k,status='Listo'),False)
        self.assertEqual(x['status'],'Listo')

    def test_finalizada_equals_done(self):
        links=[{'type':{'name':'Blocks','inward':'is blocked by','outward':'blocks'}, 'inwardIssue':{'key':'KAN-8'}}]
        get=lambda k: issue('KAN-9',status='Listo',links=links) if k=='KAN-9' else issue('KAN-8',status='Finalizada')
        self.assertEqual(mod.validate('KAN-9','inspect',get,False)['blockers'],['KAN-8'])

    def test_equivalence_holds_with_spanish_env(self):
        with patch.dict(os.environ, {'JIRA_READY_STATUS':'Listo','JIRA_DONE_STATUS':'Finalizada'}):
            links=[{'type':{'name':'Blocks','inward':'is blocked by','outward':'blocks'}, 'inwardIssue':{'key':'KAN-8'}}]
            get=lambda k: issue('KAN-9',status='Ready',links=links) if k=='KAN-9' else issue('KAN-8',status='Done')
            self.assertEqual(mod.validate('KAN-9','inspect',get,False)['blockers'],['KAN-8'])

    def test_comma_separated_extra_status(self):
        # Claude/Cursor contract rule: "Any other name is not Ready/Done". The
        # variables can no longer widen the accepted names.
        with patch.dict(os.environ, {'JIRA_READY_STATUS':'Listo, Selected for Development'}):
            with self.assertRaisesRegex(mod.GateError,'expected Ready'):
                mod.validate('KAN-9','inspect',lambda k: issue(k,status='Selected for Development'),False)

    def test_en_curso_still_blocked_with_spanish_env(self):
        with patch.dict(os.environ, {'JIRA_READY_STATUS':'Listo','JIRA_DONE_STATUS':'Finalizada'}):
            with self.assertRaisesRegex(mod.GateError,'expected Ready'):
                mod.validate('KAN-9','inspect',lambda k:issue(k,status='En curso'),False)
            links=[{'type':{'name':'Blocks','inward':'is blocked by','outward':'blocks'}, 'inwardIssue':{'key':'KAN-8'}}]
            get=lambda k: issue(k,links=links) if k=='KAN-9' else issue('KAN-8',status='Human Review')
            with self.assertRaisesRegex(mod.GateError,'not exact'):
                mod.validate('KAN-9','inspect',get,False)


CLAUDE_RULE = ('**Localized status names:** Jira may return translated `status.name` values depending on the '
               'account language. Treat `Ready` and `Listo` as the same status, and `Done` and `Finalizada` as the '
               'same status, in every check of this contract (candidate selection, dependency gate and re-checks). '
               'Any other name is not `Ready`/`Done`.')
ROOT = Path(__file__).resolve().parents[1]
NO_VARS = ('JIRA_READY_STATUS', 'JIRA_DONE_STATUS', 'JIRA_HUMAN_REVIEW_STATUS', 'JIRA_PROJECT_KEY',
           'JIRA_REPOSITORY_FIELD_ID', 'JIRA_DEPENDENCIES_FIELD_ID', 'ENABLE_OPENCODE_FACTORY_PILOT')
BLOCKS = {'name':'Blocks','inward':'is blocked by','outward':'blocks'}
PLAIN = 'Diseño técnico aprobado: implementar la feature con criterios de aceptación y pruebas unitarias.'


def no_vars_env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in NO_VARS}
    env.update({'GITHUB_REPOSITORY': 'owner/repo'}, **extra)
    return patch.dict(os.environ, env, clear=True)


class ZeroConfigTests(unittest.TestCase):
    """Works like the previous pilot: no GitHub Variables, no issue_key, no story edits."""

    def setUp(self):
        self.enterContext(patch.object(mod, 'open_pull_requests', return_value=[]))

    def test_without_any_variable(self):
        with no_vars_env():
            links=[{'type':BLOCKS,'inwardIssue':{'key':'KAN-8'}}]
            get=lambda k: issue('KAN-9',status='Listo',links=links) if k=='KAN-9' else issue('KAN-8',status='Finalizada')
            x=mod.validate('KAN-9','inspect',get,False)
            self.assertEqual((x['status'],x['blockers']),('Listo',['KAN-8']))
            self.assertEqual(mod.project_key(), 'KAN')
            self.assertEqual(mod.project_key('ABC-3'), 'ABC')

    def test_status_rule_is_exactly_the_claude_rule(self):
        self.assertEqual(mod.STATUS_EQUIVALENTS, {'ready':('Ready','Listo'),'done':('Done','Finalizada')})
        for name in ('ready','READY',' Listo ','listo'):
            self.assertTrue(mod.status_is(name,'ready'))
        for name in ('En curso','In Progress','Selected for Development','Human Review'):
            self.assertFalse(mod.status_is(name,'ready'))
        for name in ('Human Review','Resolved','Cerrada','AI Review'):
            self.assertFalse(mod.status_is(name,'done'))
        with no_vars_env(JIRA_DONE_STATUS='Resolved'):
            links=[{'type':BLOCKS,'inwardIssue':{'key':'KAN-8'}}]
            get=lambda k: issue('KAN-9',links=links) if k=='KAN-9' else issue('KAN-8',status='Resolved')
            with self.assertRaisesRegex(mod.GateError,'not exact'):
                mod.validate('KAN-9','inspect',get,False)

    def test_contracts_copy_claude_rule_verbatim(self):
        for rel in ('.opencode/agents/factory-orchestrator.md', 'automation/opencode/pilot-prompt.md'):
            self.assertIn(CLAUDE_RULE, (ROOT/rel).read_text(encoding='utf-8'), rel)
            self.assertNotIn('En curso', (ROOT/rel).read_text(encoding='utf-8'), rel)

    def test_repo_defaults_to_current_repo(self):
        with no_vars_env():
            x=mod.validate('KAN-9','inspect',lambda k: issue(k,description=PLAIN),False)
            self.assertEqual((x['repo'],x['repo_source']),('owner/repo','default GITHUB_REPOSITORY'))

    def test_repositorio_destino_line(self):
        with no_vars_env():
            d='**Repositorio destino:** `owner/repo` (rama base `master`)\n'+PLAIN
            self.assertEqual(mod.validate('KAN-9','inspect',lambda k: issue(k,description=d),False)['repo_source'],'story')
            d='Repositorio: https://github.com/owner/repo.git\n'+PLAIN
            mod.validate('KAN-9','inspect',lambda k: issue(k,description=d),False)

    def test_repositorio_destino_mismatch_fails(self):
        with no_vars_env():
            for d in ('Repositorio destino: other/foreign\n'+PLAIN, 'Repositorio: other/foreign\n'+PLAIN):
                with self.assertRaisesRegex(mod.GateError,'does not match'):
                    mod.validate('KAN-9','inspect',lambda k: issue(k,description=d),False)

    def test_kan_adf_first_paragraph(self):
        adf={'type':'doc','content':[{'type':'paragraph','content':[
            {'type':'text','text':'Repositorio destino:','marks':[{'type':'strong'}]},{'type':'text','text':' '},
            {'type':'text','text':'owner/repo','marks':[{'type':'code'}]},{'type':'text','text':' (rama base '},
            {'type':'text','text':'master','marks':[{'type':'code'}]},{'type':'text','text':')'},{'type':'hardBreak'},
            {'type':'text','text':'Dependencias (is blocked by):','marks':[{'type':'strong'}]},{'type':'text','text':' KAN-8, KAN-7'}]},
            {'type':'paragraph','content':[{'type':'text','text':PLAIN}]}]}
        text=mod.flatten_adf(adf)
        self.assertIn('Repositorio destino: owner/repo (rama base master)\n', text)
        self.assertEqual(mod.declared_repositories(text), ['owner/repo'])
        self.assertEqual(mod.extract_text_blockers(text), {'KAN-7','KAN-8'})
        with no_vars_env():
            get=lambda k: issue('KAN-9',status='Listo',description=adf) if k=='KAN-9' else issue(k,status='Finalizada')
            self.assertEqual(mod.validate('KAN-9','inspect',get,False)['blockers'],['KAN-7','KAN-8'])

    def _backlog(self):
        return {
            'KAN-1': issue('KAN-1', status='En curso'),
            'KAN-2': issue('KAN-2', labels=['agent-ready','engine-claude']),
            'KAN-3': issue('KAN-3', links=[{'type':BLOCKS,'inwardIssue':{'key':'KAN-90'}}]),
            'KAN-90': issue('KAN-90', status='Human Review'),
            'KAN-4': issue('KAN-4', status='Listo', description=PLAIN),
            'KAN-5': issue('KAN-5'),
        }

    def test_without_issue_key_selects_first_eligible_by_rank(self):
        data=self._backlog(); seen=[]
        def search(jql, limit=50):
            seen.append(jql); return ['KAN-1','KAN-2','KAN-3','KAN-4','KAN-5']
        with no_vars_env():
            chosen, skipped = mod.select('inspect', data.__getitem__, search, check_github=False)
        self.assertEqual([c['issue'] for c in chosen], ['KAN-4', 'KAN-5'])
        self.assertEqual(chosen[0]['branch'], 'agent/kan-4')
        self.assertEqual([s['issue'] for s in skipped], ['KAN-1','KAN-2','KAN-3'])
        self.assertIn('project = "KAN"', seen[0]); self.assertIn('engine-opencode', seen[0])
        self.assertIn('agent-ready', seen[0]); self.assertTrue(seen[0].endswith('ORDER BY Rank ASC'))

    def test_max_issues_one_stops_at_first_eligible(self):
        data=self._backlog()
        with no_vars_env():
            chosen, skipped = mod.select('inspect', data.__getitem__, lambda j,l=50: ['KAN-1','KAN-2','KAN-3','KAN-4','KAN-5'], check_github=False, max_issues=1)
        self.assertEqual([c['issue'] for c in chosen], ['KAN-4'])
        self.assertEqual([s['issue'] for s in skipped], ['KAN-1','KAN-2','KAN-3'])

    def test_max_issues_three_keeps_rank_order(self):
        keys=['KAN-1','KAN-2','KAN-3','KAN-4']
        data={k: issue(k, status='Listo', description=PLAIN) for k in keys}
        data['KAN-1']=issue('KAN-1', status='En curso')
        with no_vars_env():
            chosen, skipped = mod.select('inspect', data.__getitem__, lambda j,l=50: keys, check_github=False, max_issues=3)
        self.assertEqual([c['issue'] for c in chosen], ['KAN-2','KAN-3','KAN-4'])
        self.assertEqual(skipped[0]['issue'], 'KAN-1')
        with self.assertRaisesRegex(mod.GateError, '1 to 3'):
            mod.select('inspect', data.__getitem__, lambda j,l=50: keys, check_github=False, max_issues=4)

    def test_selection_skips_existing_agent_branch(self):
        data=self._backlog()
        def existing(key, branch):
            if key=='KAN-4': raise mod.GateError('Remote branch agent/kan-4 already exists')
        with no_vars_env(), patch.object(mod,'github_existing',side_effect=existing):
            chosen, skipped = mod.select('inspect', data.__getitem__, lambda j,l=50: ['KAN-4','KAN-5'])
        self.assertEqual([c['issue'] for c in chosen], ['KAN-5']); self.assertEqual(skipped[0]['issue'],'KAN-4')

    def test_selection_infra_error_fails_closed(self):
        data=self._backlog()
        with no_vars_env(), patch.object(mod,'github_existing',side_effect=mod.GateInfraError('gh down')):
            with self.assertRaises(mod.GateInfraError):
                mod.select('inspect', data.__getitem__, lambda j,l=50: ['KAN-4'])

    def test_no_eligible_is_green_no_work(self):
        import tempfile
        data=self._backlog()
        with tempfile.NamedTemporaryFile('r', delete=False) as out, no_vars_env(GITHUB_OUTPUT=out.name), \
                patch.object(mod,'jira_client',return_value=data.__getitem__), \
                patch.object(mod,'jira_search_client',return_value=lambda j,l=50: ['KAN-1','KAN-2','KAN-3']):
            self.assertEqual(mod.main(['--issue','','--mode','build']), 0)
            self.assertEqual(mod.main(['--mode','inspect']), 0)
            txt=Path(out.name).read_text()
            self.assertIn('has_work=false', txt)
            self.assertIn('issues=[]', txt)
        os.unlink(out.name)

    def test_main_with_explicit_key_still_works(self):
        import tempfile
        with tempfile.NamedTemporaryFile('r', delete=False) as out, no_vars_env(GITHUB_OUTPUT=out.name), \
                patch.object(mod,'jira_client',return_value=lambda k: issue(k,status='Listo')), \
                patch.object(mod,'github_existing',return_value=None):
            self.assertEqual(mod.main(['--issue','kan-9','--mode','inspect','--max-issues','3']), 0)
            txt=Path(out.name).read_text()
        os.unlink(out.name)
        self.assertIn('issue=KAN-9', txt); self.assertIn('branch=agent/kan-9', txt); self.assertIn('has_work=true', txt)
        self.assertIn('issues=["KAN-9"]', txt)

    def test_explicit_key_does_not_search(self):
        import tempfile
        def boom(*_a, **_k):
            raise AssertionError('search must not run when issue_key is set')
        with tempfile.NamedTemporaryFile('r', delete=False) as out, no_vars_env(GITHUB_OUTPUT=out.name), \
                patch.object(mod,'jira_client',return_value=lambda k: issue(k,status='Listo')), \
                patch.object(mod,'jira_search_client',side_effect=boom), \
                patch.object(mod,'github_existing',return_value=None):
            self.assertEqual(mod.main(['--issue','KAN-9','--max-issues','9','--mode','build']), 0)
        os.unlink(out.name)

    def test_max_issues_out_of_range_blocks_before_jira(self):
        self.assertEqual(mod.main(['--issue','','--max-issues','4','--mode','inspect']), 2)
        self.assertEqual(mod.main(['--issue','','--max-issues','0','--mode','inspect']), 2)
        self.assertEqual(mod.main(['--issue','','--max-issues','nope','--mode','inspect']), 2)


class DependencyWaitTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(no_vars_env())
        self.data = {}
        self.keys = []
        self.enterContext(patch.object(mod, 'jira_client', return_value=self.data.__getitem__))
        self.enterContext(patch.object(mod, 'jira_search_client', return_value=lambda *_: self.keys))
        self.github = self.enterContext(patch.object(mod, 'github_existing'))
        self.prs = self.enterContext(patch.object(mod, 'open_pull_requests', return_value=[]))
        self.sleep = self.enterContext(patch.object(mod.time, 'sleep'))
        self.now = self.enterContext(patch.object(mod.time, 'time', return_value=100))

    def candidate(self, key, blockers=()):
        links = [{'type': BLOCKS, 'inwardIssue': {'key': blocker}} for blocker in blockers]
        self.keys.append(key)
        self.data[key] = issue(key, links=links)

    def test_three_admissions_across_waves_without_duplicate_or_fourth(self):
        self.candidate('KAN-1', ['KAN-8'])
        self.candidate('KAN-2', ['KAN-9'])
        self.candidate('KAN-3')
        for key in ('KAN-8', 'KAN-9'):
            self.data[key] = issue(key, status='En curso', labels=['agent-ready', 'engine-cursor'])
        admitted = []
        for expected, just_finished in [('KAN-3', None), ('KAN-1', 'KAN-8'), ('KAN-2', 'KAN-9')]:
            if just_finished:
                self.data[just_finished] = issue(just_finished, status='Finalizada')
            chosen, _, more = mod.select_wave('build', 3, admitted, 1900)
            self.assertEqual([item['issue'] for item in chosen], [expected])
            admitted.append(expected)
            self.assertEqual(more, len(admitted) < 3)
        self.candidate('KAN-4')
        self.assertEqual(mod.select_wave('build', 3, admitted, 1900), ([], [], False))
        self.sleep.assert_not_called()

    def test_all_blocked_then_one_unlocks(self):
        self.candidate('KAN-1', ['KAN-8'])
        self.data['KAN-8'] = issue('KAN-8', status='In Progress')
        self.sleep.side_effect = lambda _: self.data.update({'KAN-8': issue('KAN-8', status='Done')})
        chosen, _, more = mod.select_wave('build', 1, [], 1900)
        self.sleep.assert_called_once_with(600)
        self.assertEqual([item['issue'] for item in chosen], ['KAN-1'])
        self.assertFalse(more)

    def test_mixed_blockers_never_trigger_sleep(self):
        self.candidate('KAN-1', ['KAN-8', 'KAN-9'])
        self.data['KAN-8'] = issue('KAN-8', status='AI Review')
        for labels in ([], ['agent-ready'], ['engine-claude'], ['agent-ready', 'engine-cursor', 'engine-claude']):
            with self.subTest(labels=labels):
                self.data['KAN-9'] = issue('KAN-9', labels=labels)
                chosen, skipped, more = mod.select_wave('build', 3, [], 1900)
                self.assertEqual(chosen, [])
                self.assertFalse(more)
                self.assertIn('KAN-9', skipped[0]['reason'])
        self.sleep.assert_not_called()

    def test_human_work_does_not_hold_up_lower_ranked_ready_keys(self):
        self.candidate('KAN-1', ['KAN-8'])
        self.candidate('KAN-2')
        self.candidate('KAN-3')
        self.candidate('KAN-4')
        self.data['KAN-8'] = issue('KAN-8', status='In Progress', labels=[])
        chosen, _, more = mod.select_wave('build', 3, [], 1900)
        self.assertEqual([r['issue'] for r in chosen], ['KAN-2', 'KAN-3', 'KAN-4'])
        self.assertFalse(more)
        self.sleep.assert_not_called()

    def test_human_review_without_parent_pr_does_not_wait_for_human_close(self):
        self.candidate('KAN-1', ['KAN-8', 'KAN-9'])
        self.data['KAN-8'] = issue('KAN-8', status='Human Review')
        self.data['KAN-9'] = issue('KAN-9', status='Finalizada', labels=[])
        chosen, _, more = mod.select_wave('build', 1, [], 1900)
        self.sleep.assert_not_called()
        self.assertFalse(more)
        self.assertEqual(chosen, [])

    def parent(self, key, engine, sha='a' * 40):
        branch = f'{engine}/{key.lower()}-implementation'
        return {'body': f'Factory Jira: {key}\nFactory Engine: {engine}',
                'head': {'ref': branch, 'sha': sha, 'repo': {'full_name': 'owner/repo'}},
                'html_url': 'https://github.com/owner/repo/pull/7'}

    def test_published_parent_immediately_unlocks_child_across_engines(self):
        self.candidate('KAN-1', ['KAN-8', 'KAN-9'])
        self.data['KAN-9'] = issue('KAN-9', status='Finalizada', labels=[])
        for engine in ('claude', 'cursor', 'opencode'):
            for status in ('In Progress', 'AI Review', 'Human Review'):
                with self.subTest(engine=engine, status=status):
                    self.data['KAN-8'] = issue('KAN-8', status=status, labels=['agent-ready', 'engine-' + engine])
                    pr = self.parent('KAN-8', engine)
                    self.prs.return_value = [pr]
                    chosen, _, more = mod.select_wave('build', 1, [], 1900)
                    self.assertFalse(more)
                    self.assertEqual(chosen[0]['base_branch'], pr['head']['ref'])
                    self.assertEqual(chosen[0]['base_sha'], pr['head']['sha'])
                    self.assertEqual(chosen[0]['parents'][0]['pr'], pr['html_url'])
        self.sleep.assert_not_called()

    def test_refresh_after_publication_without_waiting_for_jira_done(self):
        self.candidate('KAN-1', ['KAN-8'])
        self.data['KAN-8'] = issue('KAN-8', status='En curso', labels=['agent-ready', 'engine-cursor'])
        self.prs.side_effect = [[], [self.parent('KAN-8', 'cursor')]]
        chosen, _, _ = mod.select_wave('build', 1, [], 100 + mod.WAIT_SECONDS)
        self.sleep.assert_called_once_with(600)
        self.assertEqual(chosen[0]['parents'][0]['issue'], 'KAN-8')
        self.assertEqual(mod.WAIT_SECONDS, 340 * 60)

    def test_independent_parents_require_a_single_head_containing_both(self):
        self.candidate('KAN-1', ['KAN-8', 'KAN-9'])
        for key in ('KAN-8', 'KAN-9'):
            self.data[key] = issue(key, status='AI Review')
        self.prs.return_value = [self.parent('KAN-8', 'opencode'), self.parent('KAN-9', 'opencode', 'b'*40)]
        with patch.object(mod, 'github_api', return_value={'status': 'diverged'}):
            chosen, skipped, _ = mod.select_wave('build', 1, [], 1900)
            self.assertEqual(chosen, [])
            self.assertIn('independent heads', skipped[0]['reason'])
        with patch.object(mod, 'github_api', side_effect=[{'status': 'behind'}, {'status': 'ahead'}]):
            chosen, _, _ = mod.select_wave('build', 1, [], 1900)
            self.assertEqual(chosen[0]['base_sha'], 'b' * 40)

    def test_legacy_pr_requires_exact_url_and_key_and_same_repository(self):
        pr = self.parent('KAN-8', 'claude')
        with patch.dict(os.environ, {'JIRA_URL': 'https://board.example'}):
            pr['body'] = 'Implements https://board.example/browse/KAN-80'
            self.assertIsNone(mod.parent_pr([pr], 'owner/repo', 'KAN-8', 'claude'))
            pr['body'] = 'Implements https://board.example/browse/KAN-8'
            self.assertEqual(mod.parent_pr([pr], 'owner/repo', 'KAN-8', 'claude')['sha'], 'a' * 40)
            pr['head']['repo']['full_name'] = 'fork/repo'
            self.assertIsNone(mod.parent_pr([pr], 'owner/repo', 'KAN-8', 'claude'))

    def test_cli_carries_shared_budget_and_deadline_between_jobs(self):
        self.candidate('KAN-1', ['KAN-8'])
        self.candidate('KAN-2')
        self.data['KAN-8'] = issue('KAN-8', status='En curso')
        outputs = self.enterContext(patch.object(mod, 'write_outputs'))
        args = ['--mode', 'build', '--max-issues', '2', '--wait']
        self.assertEqual(mod.main(args), 0)
        first = outputs.call_args.args[0]
        self.assertEqual(first['can_wait'], 'true')
        self.assertEqual(first['issues'], '["KAN-2"]')
        self.data['KAN-8'] = issue('KAN-8', status='Done')
        self.candidate('KAN-3')
        self.assertEqual(mod.main(args + ['--admitted', first['admitted'],
                                          '--deadline', str(first['deadline'])]), 0)
        second = outputs.call_args.args[0]
        self.assertEqual(second['issues'], '["KAN-1"]')
        self.assertEqual(second['admitted'], '["KAN-2", "KAN-1"]')
        self.assertEqual(second['can_wait'], 'false')
        self.assertEqual(second['deadline'], first['deadline'])

    def test_wait_stops_on_changed_routing(self):
        self.candidate('KAN-1', ['KAN-8'])
        self.data['KAN-8'] = issue('KAN-8', status='En curso')
        self.sleep.side_effect = lambda _: self.data.update({'KAN-8': issue('KAN-8', labels=[])})
        chosen, skipped, more = mod.select_wave('build', 3, [], 1900)
        self.assertFalse(more)
        self.assertFalse(skipped[0]['waitable'])
        self.assertEqual(chosen, [])
        self.sleep.assert_called_once()

    def test_deadline_bounds_sleep_and_rechecks_all_gates(self):
        self.candidate('KAN-1', ['KAN-8'])
        self.data['KAN-8'] = issue('KAN-8', status='In Progress')
        self.now.side_effect = [100, 112]
        chosen, skipped, more = mod.select_wave('build', 2, [], 112)
        self.sleep.assert_called_once_with(12)
        self.assertTrue(skipped[0]['waitable'])
        self.assertEqual(chosen, [])
        self.assertFalse(more)

    def test_existing_branch_is_not_a_reason_to_wait(self):
        self.candidate('KAN-1', ['KAN-8'])
        self.data['KAN-8'] = issue('KAN-8', status='En curso')
        self.github.side_effect = mod.GateError('existing branch')
        chosen, _, more = mod.select_wave('build', 2, [], 1900)
        self.assertEqual(chosen, [])
        self.assertFalse(more)
        self.sleep.assert_not_called()

    def test_inspect_never_waits(self):
        self.candidate('KAN-1', ['KAN-8'])
        self.data['KAN-8'] = issue('KAN-8')
        self.assertEqual(mod.main(['--mode', 'inspect', '--wait']), 0)
        self.sleep.assert_not_called()

    def test_plain_dependencies_field_participates_in_wait(self):
        self.assertEqual(mod.extract_text_blockers('Dependencies: KAN-8, KAN-9'), {'KAN-8', 'KAN-9'})

    def test_existing_stories_with_empty_or_technical_prerequisites_are_admitted(self):
        self.candidate('KAN-1')
        fields = self.data['KAN-1']['fields']
        for line in ('Dependencias: ninguna.', 'Dependencies: N/A', 'Dependencies: -',
                     'Dependencias: —', 'Prerequisites: Python 3.12'):
            with self.subTest(line=line):
                fields['description'] = PLAIN + '\n' + line
                chosen, _, _ = mod.select_wave('build', 3, [], 1900)
                self.assertEqual([r['issue'] for r in chosen], ['KAN-1'])
        for value in ('ninguna.', 'N/A', '-', '—'):
            self.assertEqual(mod.dependency_field_keys(value), set())
        with self.assertRaisesRegex(mod.GateError, 'Ambiguous'):
            mod.extract_text_blockers('Prerequisites: blocked by an unspecified Jira issue')
        self.assertEqual(mod.extract_text_blockers('Prerequisites: Python 3.12 and KAN-8.'), {'KAN-8'})

    def test_ready_dependency_cycle_is_reported_without_polling(self):
        self.sleep.side_effect = AssertionError("unexpected poll")
        for count in (1, 2, 4):
            with self.subTest(count=count):
                self.keys.clear()
                keys = [f'KAN-{i + 1}' for i in range(count)]
                for i, key in enumerate(keys):
                    self.candidate(key, [keys[(i + 1) % count]])
                chosen, skipped, more = mod.select_wave('build', 3, [], 1900)
                self.assertEqual(chosen, [])
                self.assertFalse(more)
                self.assertEqual(len(skipped), count)
                for entry in skipped:
                    self.assertIn('Dependency cycle:', entry['reason'])
                    self.assertFalse(entry['waitable'])
        self.sleep.assert_not_called()

    def test_transitive_human_blocker_skips_chain_and_admits_other_work(self):
        self.sleep.side_effect = AssertionError("unexpected poll")
        self.candidate('KAN-1', ['KAN-2'])
        self.candidate('KAN-2', ['KAN-3'])
        self.candidate('KAN-3', ['KAN-4'])
        self.data['KAN-2']['fields']['labels'] = ['agent-ready', 'engine-cursor']
        self.data['KAN-4'] = issue('KAN-4', status='In Progress', labels=[])
        self.candidate('KAN-5')
        chosen, skipped, more = mod.select_wave('build', 3, [], 1900)
        self.assertEqual([r['issue'] for r in chosen], ['KAN-5'])
        self.assertFalse(more)
        self.assertIn('KAN-4', skipped[0]['reason'])
        self.sleep.assert_not_called()

    def test_ready_blocker_must_be_runnable_now(self):
        self.sleep.side_effect = AssertionError("unexpected poll")
        self.candidate('KAN-1', ['KAN-2'])
        self.candidate('KAN-2', ['KAN-3'])
        self.data['KAN-2']['fields']['labels'] = ['agent-ready', 'engine-claude']
        self.data['KAN-3'] = issue('KAN-3', status='En curso')
        chosen, skipped, more = mod.select_wave('build', 3, [], 1900)
        self.assertEqual(chosen, [])
        self.assertFalse(more)
        self.assertIn('KAN-2 cannot start', skipped[0]['reason'])
        self.sleep.assert_not_called()
        # The same Ready blocker can start on a published agent PR.
        self.prs.return_value = [self.parent('KAN-3', 'opencode')]
        self.candidate('KAN-5')
        chosen, skipped, more = mod.select_wave('build', 3, [], 1900)
        self.assertEqual([r['issue'] for r in chosen], ['KAN-5'])
        self.assertTrue(more)
        self.assertTrue(skipped[0]['waitable'])

    def test_custom_dependency_field_includes_human_blocker(self):
        self.enterContext(patch.dict(os.environ, {'JIRA_DEPENDENCIES_FIELD_ID': 'customfield_100'}))
        self.candidate('KAN-1')
        self.data['KAN-1']['fields']['customfield_100'] = [{'key': 'KAN-8'}, 'KAN-9']
        self.data['KAN-8'] = issue('KAN-8', status='In Progress')
        self.data['KAN-9'] = issue('KAN-9', labels=[])
        chosen, skipped, more = mod.select_wave('build', 3, [], 1900)
        self.assertEqual(chosen, [])
        self.assertFalse(more)
        self.assertIn('KAN-9', skipped[0]['reason'])
        self.sleep.assert_not_called()


class SearchPaginationTests(unittest.TestCase):
    def test_ranked_search_continues_past_first_page(self):
        from io import BytesIO
        replies = [BytesIO(b'{"issues":[{"key":"KAN-1"}],"nextPageToken":"next"}'),
                   BytesIO(b'{"issues":[{"key":"KAN-2"}],"isLast":true}')]
        get = Mock(side_effect=replies)
        with no_vars_env(JIRA_URL='https://example.test', JIRA_USERNAME='user', JIRA_API_TOKEN='test'), \
                patch.object(mod.urllib.request, 'urlopen', get):
            self.assertEqual(list(mod.jira_search_client()('ORDER BY Rank ASC', 1)), ['KAN-1', 'KAN-2'])
        self.assertIn('nextPageToken=next', get.call_args.args[0].full_url)


class WorkflowZeroConfigTests(unittest.TestCase):
    wf = (ROOT/'.github'/'workflows'/'opencode-factory.yml').read_text(encoding='utf-8')

    def test_issue_key_optional(self):
        block = self.wf.split('issue_key:',1)[1].split('mode:',1)[0]
        self.assertIn('required: false', block)
        self.assertNotIn('required: true', block)

    def test_no_mandatory_pilot_variable(self):
        self.assertNotIn('!= "true"', self.wf)
        self.assertIn('if [ "$ENABLE_PILOT" = "false" ]', self.wf)

    def test_defaults_without_variables(self):
        self.assertIn("vars.JIRA_PROJECT_KEY || 'KAN'", self.wf)
        self.assertIn("vars.JIRA_HUMAN_REVIEW_STATUS || 'Human Review'", self.wf)
        self.assertNotIn('JIRA_READY_STATUS', self.wf)
        self.assertNotIn('JIRA_DONE_STATUS', self.wf)

    def test_quota_controls_kept(self):
        for needle in ('timeout-minutes: 355', '--no-edit-seconds 900', '--total-seconds 20400',
                       '--max-reported-input-tokens 5000000', 'postflight.py', 'check_config.py',
                       'git fetch origin "$DEFAULT_BRANCH"', 'DEFAULT_BRANCH="master"', '- inspect', '- build'):
            self.assertIn(needle, self.wf)
        self.assertEqual(self.wf.count("steps.gate.outputs.has_work == 'true'"), 5)


    def test_diff_artifact_step(self):
        steps = self.wf.split('\n      - name: ')
        guarded = next(i for i, s in enumerate(steps) if s.startswith('One guarded'))
        save_i = next(i for i, s in enumerate(steps) if s.startswith('Save working-tree diff'))
        up_i = next(i for i, s in enumerate(steps) if s.startswith('Upload diff artifact'))
        self.assertTrue(guarded < save_i < up_i)
        save, up = steps[save_i], steps[up_i]
        for s in (save, up):
            self.assertIn('if: always()', s)
            self.assertIn('continue-on-error: true', s)
        self.assertIn('git add -A', save)
        self.assertIn('git diff --cached --binary "$BASE_SHA"', save)
        self.assertIn('.patch', save)
        self.assertIn('exit 0', save)
        self.assertNotIn('set -e\n', save)
        self.assertNotIn('git push', save)
        self.assertNotIn('git commit', save)
        self.assertNotIn('gh pr', save)
        self.assertIn('uses: actions/upload-artifact@v4', up)
        self.assertIn('name: opencode-factory-diff-${{ matrix.issue }}', up)
        self.assertIn('name: opencode-factory-summary-${{ matrix.issue }}', self.wf)
        self.assertIn('retention-days: 7', up)
        self.assertIn('if-no-files-found: ignore', up)
        self.assertNotIn('--total-seconds 1800', self.wf)
        # Line-anchored so 'timeout-minutes: 355' does not match the old 35/50.
        self.assertNotRegex(self.wf, r'(?m)timeout-minutes: (35|50)\s*$')
        for old in ('--total-seconds 2700', '--no-edit-seconds 360'):
            self.assertNotIn(old, self.wf)
        self.assertNotRegex(self.wf, r'--max-reported-input-tokens 800000\b')

    def test_parallel_selection_and_pinned_cli(self):
        self.assertIn('OPENCODE_VERSION: 1.19.4', self.wf)
        self.assertNotIn('@latest', self.wf)
        self.assertNotIn('opencode-ai@latest', self.wf)
        self.assertIn('opencode-ai@${OPENCODE_VERSION}', self.wf)
        self.assertIn('max-parallel: 3', self.wf)
        self.assertIn('fail-fast: false', self.wf)
        self.assertIn("cron: '0 23 * * *'", self.wf)
        self.assertIn('DEFAULT_BRANCH="master"', self.wf)
        self.assertRegex(self.wf, r'(?m)^  select:\s*$')
        self.assertRegex(self.wf, r'(?m)^  factory:\s*$')
        self.assertIn('concurrency:', self.wf)
        self.assertIn('group: opencode-factory-${{ github.repository }}', self.wf)
        for name in ('opencode-factory-PILOT.yml', 'opencode-connectivity.yml'):
            text = (ROOT/'.github'/'workflows'/name).read_text(encoding='utf-8')
            self.assertIn('OPENCODE_VERSION: 1.19.4', text, name)
            self.assertNotIn('@latest', text, name)

if __name__=='__main__': unittest.main()
