"""Run inside the broker container: python - < scripts/lab4_container_probe.py.

Checks real gRPC across containers and topic-triggered cleanup. Only the caller's
fresh test bundle is removed. The university registry is not needed: the issued
bundle is deliberately non-legitimate synthetic data.
"""
import json
import time
import uuid
from datetime import datetime, timezone
from urllib.request import urlopen
from urllib.parse import urlsplit
import grpc
from app.generated import messaging_pb2 as pb, messaging_pb2_grpc as rpc

def main():
    applicant_id = str(uuid.uuid4())
    request_id = 'lab4-container-' + str(uuid.uuid4())
    with grpc.insecure_channel('message-broker:9091') as channel:
        client = rpc.MessageBrokerStub(channel)
        def get(path):
            return client.Call(pb.ServiceRequest(message_id=str(uuid.uuid4()),source='smoke',target='credential-service',method='GET',path=path,request_id=request_id), timeout=5)
        issued = client.Call(pb.ServiceRequest(message_id=str(uuid.uuid4()),source='smoke',target='credential-service',method='POST',path='/credentials/issue',request_id=request_id,
            body=json.dumps(dict(applicantId=applicant_id,isLegitimate=False,seed=dict(faculty='FAF',year=3))).encode()), timeout=5)
        assert issued.status == 201, (issued.status, issued.body)
        bundle = json.loads(issued.body)
        with urlopen('http://service-discovery:8089/services/credential-service/instances',timeout=3) as response:
            replicas=json.load(response)['instances']
        assert len(replicas) == 2
        for instance in replicas:
            address=urlsplit(instance['url'])
            with grpc.insecure_channel(f'{address.hostname}:{address.port+1000}') as peer:
                reply=rpc.ServiceEndpointStub(peer).Call(pb.ServiceRequest(message_id=str(uuid.uuid4()),source='smoke',target='credential-service',method='GET',path='/credentials/'+bundle['id'],request_id=request_id),timeout=3)
                assert reply.status == 200
        queued = client.Publish(pb.Event(message_id=str(uuid.uuid4()),source='applicant-service',topic='applicant.deleted',schema_version=1,
            occurred_at=datetime.now(timezone.utc).isoformat(),payload=json.dumps(dict(applicantId=applicant_id,sessionId=str(uuid.uuid4()))).encode(),request_id=request_id),timeout=3)
        assert list(queued.queued_services) == ['credential-service']
        for _ in range(100):
            if get('/credentials/'+bundle['id']).status == 404: break
            time.sleep(.1)
        else: raise AssertionError('Event cleanup did not commit')
        print(json.dumps(dict(passed=True, timestamp=datetime.now(timezone.utc).isoformat(), checks=[
            'Broker -> Credential uses real gRPC between Linux containers',
            'Both physical Credential replicas read the shared Redis bundle over gRPC',
            'Topic publication creates one service copy despite two replicas',
            'applicant.deleted delivery commits Credential cleanup and GET returns 404'],
            scope='Owned service container integration; no University Record call; no Gateway',
            replicaIds=[r['instanceId'] for r in replicas]),indent=2))

if __name__ == '__main__': main()
