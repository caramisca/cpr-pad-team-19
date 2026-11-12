"""Scoped acceptance through a real Gateway/broker and Mihai's published services.

Run inside the broker container (its app.generated protobuf modules are required).
Use a dedicated test stack. The test creates synthetic data and publishes session.closed
itself: it does not certify the real Session publisher or University Record adapter.
The API key is read only from LAB4_TEST_API_KEY and is never written to evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import time
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import grpc
from app.generated import messaging_pb2 as pb, messaging_pb2_grpc as rpc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gateway-url', default='http://gateway-owned-check:8080')
    parser.add_argument('--broker-url', default='http://message-broker:8091')
    parser.add_argument('--discovery-url', default='http://service-discovery:8089')
    args = parser.parse_args()
    key = os.environ['LAB4_TEST_API_KEY']
    trace = 'owned-check-' + str(uuid.uuid4())
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    checks = []

    def request(base, path, method='GET', body=None, auth=False):
        headers = {'X-Request-Id': trace}
        if auth:
            headers['Authorization'] = 'Bearer ' + key
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
        try:
            response = opener.open(req, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        raw = response.read()
        return response.status, response.headers, json.loads(raw) if raw else None

    def gateway(path, method='GET', body=None):
        status, headers, data = request(args.gateway_url, path, method, body, auth=True)
        assert headers.get('Content-Type', '').startswith('application/json'), (path, status)
        assert headers.get('X-Request-Id') == trace, (path, status)
        assert headers.get('X-Instance-Id'), (path, status)
        return status, headers, data

    def eventually(action, seconds=30):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if action():
                return
            time.sleep(.25)
        raise AssertionError('Expected committed effect did not become visible')

    def event(topic, payload):
        return {'messageId': str(uuid.uuid4()), 'source': 'server-moderation-session-service',
                'topic': topic, 'occurredAt': datetime.now(timezone.utc).isoformat(),
                'schemaVersion': 1, 'requestId': trace, 'payload': payload}

    # Invalid/unavailable registry calls cannot fabricate a successful legitimate lookup.
    record_status, _, _ = gateway('/credentials/issue', 'POST', {
        'applicantId': str(uuid.uuid4()), 'isLegitimate': True,
        'seed': {'studentId': '1234567890', 'faculty': 'FAF', 'year': 3}})

    created = []
    sessions = [str(uuid.uuid4()), str(uuid.uuid4())]
    try:
        for session in sessions:
            for _ in range(12):
                status, headers, data = gateway('/applicants/generate', 'POST',
                                               {'sessionId': session, 'difficulty': 'HARD'})
                if status == 201:
                    assert headers.get('Location') == '/applicants/' + data['id']
                    created.append(data)
                    break
                assert status == 503, status
            else:
                raise AssertionError('No synthetic applicant generated; dependency is unavailable')
        checks.append('Real Gateway -> broker -> Applicant -> broker -> Credential creates two isolated session datasets')
        for applicant, session in zip(created, sessions):
            status, _, data = gateway('/applicants?sessionId=' + session)
            assert status == 200 and [a['id'] for a in data['applicants']] == [applicant['id']]
            status, _, data = gateway('/credentials?applicantId=' + applicant['id'])
            assert status == 200 and [c['id'] for c in data['credentials']] == [applicant['credentialId']]
        checks.append('Gateway retains JSON Content-Type, Location, request/instance IDs and both query filters with distractor data')
        for path, expected in [('/applicants?sessionId=invalid', 400),
                               ('/credentials?applicantId=invalid', 400),
                               ('/applicants/' + str(uuid.uuid4()), 404),
                               ('/credentials/' + str(uuid.uuid4()), 404)]:
            assert gateway(path)[0] == expected
        checks.append('JSON 400/404 errors retain content type and correlation headers through Gateway')

        closed = event('session.closed', {'sessionId': sessions[0]})
        status, _, queued = request(args.broker_url, '/events', 'POST', closed)
        assert status == 202 and 'applicant-service' in queued['queuedServices']
        eventually(lambda: gateway('/applicants/' + created[0]['id'])[0] == 404)
        eventually(lambda: gateway('/credentials/' + created[0]['credentialId'])[0] == 404)
        assert gateway('/applicants/' + created[1]['id'])[0] == 200
        assert gateway('/credentials/' + created[1]['credentialId'])[0] == 200
        checks.append('session.closed commits Applicant cleanup and Credential cleanup while preserving the other session')

        message = pb.Event(message_id=closed['messageId'], source=closed['source'], topic=closed['topic'],
                           occurred_at=closed['occurredAt'], schema_version=1, request_id=trace,
                           payload=json.dumps(closed['payload']).encode())
        replicas = request(args.discovery_url, '/services/applicant-service/instances')[2]['instances']
        assert len(replicas) == 2
        replica_ids = []
        for replica in replicas:
            url = urlsplit(replica['url'])
            with grpc.insecure_channel(f'{url.hostname}:{url.port + 1000}') as channel:
                reply = rpc.ServiceEndpointStub(channel).Deliver(message, timeout=5)
                assert reply.outcome == pb.DeliveryReply.COMMITTED
            replica_ids.append(replica['instanceId'])
        checks.append('Duplicate delivery to both physical Applicant replicas returns COMMITTED using the shared inbox')

        invalid = event('session.closed', {})
        assert request(args.broker_url, '/events', 'POST', invalid)[0] == 202
        def dead_letter():
            data = request(args.broker_url, '/dead-letters?service=applicant-service&limit=100')[2]
            return any(e['messageId'] == invalid['messageId'] and e['reason'] for e in data['deadLetters'])
        eventually(dead_letter)
        checks.append('Real Applicant REJECTED payload is transferred to the integrated broker DLC with its reason')
        result = {'timestamp': datetime.now(timezone.utc).isoformat(), 'passed': True, 'checks': checks,
                  'scope': 'Real Gateway + broker + Applicant/Credential/Redis/SD; manual session publisher; no Record fixture',
                  'legitimateRecordRequestStatus': record_status,
                  'realUniversityRecordVerified': record_status == 201,
                  'applicantReplicaIds': replica_ids, 'invalidMessageId': invalid['messageId']}
        print(json.dumps(result, indent=2))
    finally:
        for session in sessions:
            request(args.broker_url, '/events', 'POST', event('session.closed', {'sessionId': session}))


if __name__ == '__main__':
    main()
