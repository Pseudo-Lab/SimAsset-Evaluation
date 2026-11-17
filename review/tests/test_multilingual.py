import json
import unicodedata

import pytest
from fastapi.testclient import TestClient

from simasset_review.api import create_app
from simasset_review.db import import_bundle


SAMPLES = [
    ('한국어', '판정 저장\n홈 내부의 접촉을 확인했습니다.'),
    ('English', 'The cup stays upright. A brief contact is visible.'),
    ('日本語', '接触後も姿勢が安定しています。'),
    ('中文', '接触后物体保持稳定，未发现明显穿透。'),
    ('العربية', 'يبقى الجسم مستقراً. depth = 0.25 mm'),
    ('עברית', 'הגוף נשאר יציב. depth = 0.25 mm'),
    ('हिन्दी', 'वस्तु स्थिर है। संपर्क की जाँच की गई।'),
    ('Français', 'Le café reste stable. Cafe\u0301, naïve, Straße, Ελληνικά.'),
    ('Emoji', '확인 ✅ 👩🏽‍💻 👨‍👩‍👧‍👦 🧪\n<script>alert("text only")</script>'),
    ('Decomposed', unicodedata.normalize('NFD', '한글 조합 원문과 é를 그대로 보관합니다.')),
]


@pytest.mark.parametrize('reviewer,rationale', SAMPLES)
def test_unicode_roundtrip_and_revision(database, bundle, namespace, reviewer, rationale):
    run = import_bundle(database, bundle, namespace, 'fixture')['run_id']
    with database.connect() as conn:
        assert conn.execute('SHOW server_encoding').fetchone()['server_encoding'] == 'UTF8'
    with TestClient(create_app(database)) as client:
        artifacts = client.get('/api/runs/' + run).json()['artifacts']
        payload = dict(outcome='inconclusive', reviewer=reviewer, rationale=rationale,
                       criterion_key='多言語_관찰', protocol_version='검토-é-🧪-1',
                       evidence_ids=[artifacts[0]['artifact_id']])
        first = client.post(f'/api/runs/{run}/judgments', json=payload)
        assert first.status_code == 201
        saved = client.get('/api/runs/' + run).json()['judgments'][0]
        for field in ('reviewer', 'rationale', 'criterion_key', 'protocol_version', 'evidence_ids'):
            assert saved[field] == payload[field]
        payload.update(rationale=rationale + '\nRevision / 수정 / تعديل ✅',
                       supersedes_judgment_id=first.json()['judgment_id'])
        assert client.post(f'/api/runs/{run}/judgments', json=payload).status_code == 201
        history = client.get('/api/runs/' + run).json()['judgments']
        assert len(history) == 2
        assert next(j for j in history if not j['current'])['rationale'] == rationale
        assert next(j for j in history if j['current'])['rationale'] == payload['rationale']


def test_limits_count_unicode_code_points(database, bundle, namespace):
    run = import_bundle(database, bundle, namespace, 'fixture')['run_id']
    payload = dict(outcome='inconclusive', reviewer='🧪' * 100, rationale='🧪' * 5000,
                   criterion_key='测' * 100, protocol_version='🧪' * 100)
    with TestClient(create_app(database)) as client:
        assert client.post(f'/api/runs/{run}/judgments', json=payload).status_code == 201
        saved = client.get('/api/runs/' + run).json()['judgments'][0]
        assert saved['rationale'] == payload['rationale']
        for field in ('reviewer', 'rationale', 'criterion_key', 'protocol_version'):
            assert client.post(f'/api/runs/{run}/judgments', json={**payload, field:payload[field]+'🧪'}).status_code == 422


@pytest.mark.parametrize('bad', ['\x00', '\ud800', '\udfff'])
@pytest.mark.parametrize('field', ['reviewer', 'rationale', 'criterion_key', 'protocol_version'])
def test_invalid_unicode_is_a_validation_error_not_a_server_error(database, bundle, namespace, bad, field):
    run = import_bundle(database, bundle, namespace, 'fixture')['run_id']
    payload = dict(outcome='inconclusive', reviewer='검토자', rationale='확인',
                   criterion_key='physical_behavior', protocol_version='v1')
    payload[field] = 'invalid' + bad
    with TestClient(create_app(database)) as client:
        response = client.post(f'/api/runs/{run}/judgments',
                               content=json.dumps(payload, ensure_ascii=True),
                               headers={'Content-Type':'application/json'})
        assert response.status_code == 422
        assert all('input' not in item for item in response.json()['detail'])
        assert client.get('/api/runs/' + run).json()['judgments'] == []
