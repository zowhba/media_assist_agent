import unittest
from datetime import date
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
import am_client as am


class AMClientTests(unittest.TestCase):
    def test_weekdays_and_year_boundary(self):
        for day in range(21, 26):
            issues = am.build_issues(am.DEFAULTS, date(2026, 9, day))
            self.assertEqual(len(issues), 2)
            for issue in issues:
                self.assertIn(f'2026-09-{day}', issue['description'])
                self.assertIn('2026-09-25', issue['description'])
        self.assertIn('2027-01-01', am.build_issues(am.DEFAULTS, date(2026, 12, 31))[0]['description'])

    def test_weekend(self):
        for day in (26, 27):
            with self.assertRaises(HTTPException):
                am.build_issues(am.DEFAULTS, date(2026, 9, day))

    def test_fixed_targets_and_template(self):
        issues = am.build_issues({**am.DEFAULTS, 'BTVVPN': '기간 {start_date}~{end_date}\n{table}'}, date(2026, 9, 21))
        self.assertIn('2200146|이지영', issues[0]['description'])
        self.assertIn('runa0477|이윤주', issues[0]['description'])
        self.assertNotIn('2200146', issues[1]['description'])
        self.assertEqual(len(issues[0]['components']), 5)
        self.assertNotIn('components', issues[1])
        for issue in issues:
            self.assertEqual(issue['assignee'], {'name': '-1'})
            self.assertEqual(issue['issuetype']['name'], 'AM Client사용 신청서')
        with self.assertRaises(HTTPException):
            am.build_issues({**am.DEFAULTS, 'BTVVPN': 'missing table'}, date(2026, 9, 21))

    def test_submission_partial_failure_and_replay(self):
        app = FastAPI()
        user = {'username': 'test'}
        am.install(app, lambda r: user, lambda r: (user, {'jira_base_url': 'https://jira.example'}), lambda n: n, 'fake')
        sent = []
        def handler(request):
            if request.method == 'GET':
                return httpx.Response(200, json=[{'id': '4', 'name': '낮음'}])
            import json
            payload = json.loads(request.content)['fields']
            sent.append(payload)
            if payload['project']['key'] == 'BTVVPN':
                return httpx.Response(201, json={'key': 'BTVVPN-123'})
            return httpx.Response(400, json={'errors': {'issuetype': 'missing'}})
        real_client = httpx.AsyncClient
        with patch.object(am, 'load_settings', return_value=am.DEFAULTS), patch.object(am, 'today', return_value=date(2026, 9, 21)), patch.object(am.httpx, 'AsyncClient', side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)):
            client = TestClient(app)
            preview = client.post('/api/am-client/preview').json()
            body = {'preview_id': preview['preview_id']}
            self.assertEqual(client.post('/api/am-client/create', json=body).status_code, 400)
            body['drafts'] = {issue['project']['key']: {'summary': issue['summary'], 'description': issue['description']} for issue in preview['issues']}
            body['drafts']['BTVVPN']['summary'] = '수정한 신청 제목'
            body['drafts']['BTVVPN']['description'] += '\n수정한 신청 내용'
            self.assertEqual(client.post('/api/am-client/create', json=body).status_code, 400)
            testbed = {'preview_id': preview['preview_id'], 'drafts': {'TESTBED': body['drafts'].pop('TESTBED')}}
            result = client.post('/api/am-client/create', json=body)
            self.assertEqual(result.status_code, 200)
            self.assertTrue(result.json()['results'][0]['ok'])
            self.assertEqual(len(result.json()['results']), 1)
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0]['project']['key'], 'BTVVPN')
            second = client.post('/api/am-client/create', json=testbed)
            self.assertEqual(second.status_code, 200)
            self.assertFalse(second.json()['results'][0]['ok'])
            self.assertEqual(sent[1]['project']['key'], 'TESTBED')
            self.assertEqual(client.post('/api/am-client/create', json=testbed).status_code, 409)
            self.assertEqual(client.post('/api/am-client/create', json=body).status_code, 409)
            self.assertEqual(len(sent), 2)
            self.assertEqual(sent[0]['summary'], '수정한 신청 제목')
            self.assertTrue(sent[0]['description'].endswith('수정한 신청 내용'))
            self.assertEqual(result.json()['results'][0]['url'], 'https://jira.example/browse/BTVVPN-123')
            self.assertEqual(sent[0]['priority'], {'id': '4'})
            self.assertNotIn('fixVersions', sent[0])
            with patch.object(am, 'today', return_value=date(2026, 9, 22)):
                self.assertEqual(client.post('/api/am-client/create', json=body).status_code, 400)

    def test_auth_required(self):
        app = FastAPI()
        def denied(request):
            raise HTTPException(401, 'login required')
        am.install(app, denied, lambda r: denied(r), lambda n: n, 'fake')
        client = TestClient(app)
        self.assertEqual(client.get('/api/am-client/settings').status_code, 401)
        self.assertEqual(client.post('/api/am-client/preview').status_code, 401)
        self.assertEqual(client.post('/api/am-client/create', json={'preview_id': 'x'}).status_code, 401)

if __name__ == '__main__':
    unittest.main()
