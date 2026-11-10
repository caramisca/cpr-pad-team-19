"""Local proof with real .NET 8, Redis, live SD, two replicas and protobuf/HTTP2.

No teammate service implementation is replaced: University Record is an explicitly
labelled gRPC fixture because Diana owns that adapter. All owned child processes
and test Redis keys are cleaned on exit.
"""
import os, sys, json, time, socket, subprocess, threading, uuid, random, argparse, shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
import httpx, grpc, redis

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--workspace',type=Path,required=True,help='Directory containing broker, applicant, credential and discovery checkouts')
parser.add_argument('--dotnet',default=shutil.which('dotnet'),help='Path to .NET 8 runtime executable')
parser.add_argument('--configuration',default='Release')
parser.add_argument('--redis-port',type=int,default=16394)
parser.add_argument('--evidence',type=Path,required=True)
args=parser.parse_args()
BASE=args.workspace.resolve()
sys.path.insert(0,str(BASE/'broker'))
from app.broker import Broker
from app.config import Settings
from app.generated import messaging_pb2 as pb, messaging_pb2_grpc as rpc
from app.grpc_transport import GrpcServer, event_to_proto

def free_pair():
    for _ in range(100):
        port=random.randint(20000,45000)
        with socket.socket() as sock:
            try: sock.bind(('127.0.0.1',port))
            except OSError: continue
        with socket.socket() as sock:
            try: sock.bind(('127.0.0.1',port+1000))
            except OSError: continue
        return port
    raise RuntimeError('No free port pair')

def eventually(action, seconds=20):
    last=None
    for _ in range(seconds*10):
        try:
            value=action()
            if value: return value
        except Exception as error: last=error
        time.sleep(.1)
    raise AssertionError(f'Timed out: {last}')

def main():
    prefix='Lab4Smoke:'+str(uuid.uuid4())+':'
    database=redis.Redis(host='127.0.0.1',port=args.redis_port)
    processes=[]; files=[]; broker=None
    evidence={'startedAt':datetime.now(timezone.utc).isoformat(),'checks':[],
              'scope':'Real Applicant/Credential/Redis/Service Discovery; University Record gRPC fixture; no Gateway',
              'runtime':'\n'.join(line.split(' [')[0] for line in subprocess.check_output([args.dotnet,'--list-runtimes'],text=True).splitlines())}
    http=httpx.Client(trust_env=False,timeout=3)
    sd_port=free_pair(); app_ports=[free_pair(),free_pair()]; cred_ports=[free_pair(),free_pair()]
    broker_port=free_pair()
    def child(short, command, env):
        logfile=open(BASE/(short+str(len(processes))+'.smoke.log'),'w',encoding='utf8'); files.append(logfile)
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        process=subprocess.Popen(command,cwd=BASE/short,env={**os.environ,**env},stdout=logfile,stderr=subprocess.STDOUT,creationflags=flags)
        process.smoke_env=env; process.smoke_command=command; process.smoke_short=short
        processes.append(process); return process
    class Records(rpc.ServiceEndpointServicer):
        def Call(self, request, context):
            assert request.target=='university-record-service' and request.path=='/records/students/lookup'
            seed=json.loads(request.body)
            return pb.ServiceReply(status=200,body=json.dumps({'matches':[{
                'studentId':seed.get('studentId') or '1234567890','fullName':'Diana Popescu',
                'faculty':seed.get('faculty') or 'FAF','studyYear':3,'enrolmentStatus':'ENROLLED'}]}).encode())
    fixture=grpc.server(ThreadPoolExecutor(2)); rpc.add_ServiceEndpointServicer_to_server(Records(),fixture)
    fixture_port=fixture.add_insecure_port('127.0.0.1:0'); fixture.start()
    try:
        child('discovery',[sys.executable,'-m','app'],dict(DISCOVERY_HOST='127.0.0.1',DISCOVERY_PORT=str(sd_port),INSTANCE_TTL_SECONDS='60'))
        sd=f'http://127.0.0.1:{sd_port}'
        # SD's actual configuration names are DISCOVERY_PORT/DISCOVERY_HOST.
        eventually(lambda:http.get(sd+'/health').status_code==200)
        import dataclasses
        broker=Broker(dataclasses.replace(Settings.from_env({'BROKER_HOST':'127.0.0.1','DISCOVERY_URL':sd}),port=broker_port))
        broker.grpc=GrpcServer(broker,broker.delivery,0); broker.start()
        broker_url=f'http://127.0.0.1:{broker.grpc.port}'
        for short,ns,ports in [('credential','CredentialService',cred_ports),('applicant','ApplicantService',app_ports)]:
            for i,port in enumerate(ports):
                env=dict(Messaging__Enabled='true',Messaging__BrokerUrl=broker_url,Messaging__HttpPort=str(port),Messaging__GrpcPort=str(port+1000),
                    ServiceDiscovery__Url=sd,ServiceDiscovery__InstanceUrl=f'http://127.0.0.1:{port}',ServiceDiscovery__InstanceId=f'smoke-{short}-{i}',
                    Storage__Provider='Redis',Redis__ConnectionString=f'127.0.0.1:{args.redis_port}',Redis__InstanceName=prefix+short+':')
                env['Services__'+('CredentialServiceMode' if short=='applicant' else 'UniversityRecordMode')]='Grpc'
                child(short,[args.dotnet,str(BASE/short/'src'/ns/'bin'/args.configuration/'net8.0'/(ns+'.dll'))],env)
                eventually(lambda port=port:http.get(f'http://127.0.0.1:{port}/health').status_code==200)
        for short in ['applicant','credential']:
            eventually(lambda short=short:len(http.get(sd+f'/services/{short}-service/instances').json()['instances'])==2)
        http.post(sd+'/instances',json=dict(serviceName='university-record-service',instanceId='grpc-fixture',url=f'http://127.0.0.1:{fixture_port-1000}',healthUrl=f'http://127.0.0.1:{fixture_port-1000}/health')).raise_for_status()
        evidence['checks'].append('Two live, independently registered replicas of each owned service')
        session=str(uuid.uuid4())
        with grpc.insecure_channel(f'127.0.0.1:{broker.grpc.port}') as channel:
            client=rpc.MessageBrokerStub(channel)
            def call(target,method,path,body=None):
                reply=client.Call(pb.ServiceRequest(message_id=str(uuid.uuid4()),source='smoke',target=target,method=method,path=path,
                    body=b'' if body is None else json.dumps(body).encode(),request_id='lab4-smoke'),timeout=8)
                assert reply.status in (200,201,204), (reply.status,reply.body)
                return json.loads(reply.body) if reply.body else None
            # Explicit legitimate issue proves Credential -> Broker -> University Record fixture.
            issued=call('credential-service','POST','/credentials/issue',dict(applicantId=str(uuid.uuid4()),isLegitimate=True,seed=dict(studentId='1234567890',faculty='FAF',year=3)))
            evidence['checks'].append('Credential -> Broker -> University Record gRPC fixture')
            generated=call('applicant-service','POST','/applicants/generate',dict(sessionId=session,difficulty='EASY'))
            evidence['checks'].append('Applicant -> Broker -> Credential uses real HTTP/2 protobuf, Gateway absent')
            assert http.get(f'http://127.0.0.1:{app_ports[1]}/applicants/'+generated['id']).status_code==200
            evidence['checks'].append('Second replica reads shared Redis state')
            listed=client.ListTopics(pb.Empty(),timeout=3)
            assert {'session.closed','applicant.deleted'} <= {t.name for t in listed.topics}
            message=dict(messageId=str(uuid.uuid4()),source='server-moderation-session-service',topic='session.closed',occurredAt=datetime.now(timezone.utc).isoformat(),schemaVersion=1,payload=dict(sessionId=session))
            queued=client.Publish(event_to_proto(message),timeout=3)
            assert list(queued.queued_services)==['applicant-service']
            eventually(lambda:http.get(f'http://127.0.0.1:{app_ports[0]}/applicants/'+generated['id']).status_code==404)
            eventually(lambda:http.get(f'http://127.0.0.1:{cred_ports[0]}/credentials/'+generated['credentialId']).status_code==404)
            evidence['checks'].append('session.closed -> Applicant commit/outbox -> applicant.deleted -> Credential commit; both entities removed')
            # Same envelope, direct delivery to another replica after successful processing.
            with grpc.insecure_channel(f'127.0.0.1:{app_ports[1]+1000}') as peer:
                answer=rpc.ServiceEndpointStub(peer).Deliver(event_to_proto(message),timeout=3)
                assert answer.outcome==pb.DeliveryReply.COMMITTED
                invalid=event_to_proto(message); invalid.message_id=str(uuid.uuid4()); invalid.payload=b'{}'
                assert rpc.ServiceEndpointStub(peer).Deliver(invalid,timeout=3).outcome==pb.DeliveryReply.REJECTED
            evidence['checks'].append('Duplicate delivery to another replica reads shared durable inbox; poison payload returns REJECTED')
            for port in [*app_ports,*cred_ports]:
                assert 'service_requests_total' in http.get(f'http://127.0.0.1:{port}/metrics').text
                for line in http.get(f'http://127.0.0.1:{port}/internal/logs').text.splitlines():
                    if line.strip(): assert 'requestId' in json.loads(line)
            evidence['checks'].append('Metrics and bounded structured NDJSON logs available on every replica')
            # Stop broker, commit service write, verify Redis outbox persists across service restart.
            grpc_port=broker.grpc.port
            broker.stop(); broker=None
            credential_process=processes[1]
            direct=http.post(f'http://127.0.0.1:{cred_ports[0]}/credentials/issue',json=dict(applicantId=str(uuid.uuid4()),isLegitimate=False,seed=dict(faculty='FAF',year=3)))
            assert direct.status_code==201
            eventually(lambda:database.hlen(prefix+'credential:messaging:outbox')>0)
            evidence['checks'].append('Broker outage retains a committed domain event in Redis outbox')
            credential_process.terminate(); credential_process.wait(8)
            child(credential_process.smoke_short,credential_process.smoke_command,credential_process.smoke_env)
            eventually(lambda:http.get(f'http://127.0.0.1:{cred_ports[0]}/health').status_code==200)
            assert database.hlen(prefix+'credential:messaging:outbox')>0
            assert http.get(f'http://127.0.0.1:{cred_ports[0]}/credentials/'+direct.json()['id']).status_code==200
            evidence['checks'].append('Domain record and pending outbox survive Credential process restart')
            broker=Broker(dataclasses.replace(Settings.from_env({'BROKER_HOST':'127.0.0.1','DISCOVERY_URL':sd}),port=broker_port))
            broker.grpc=GrpcServer(broker,broker.delivery,grpc_port); broker.start()
            eventually(lambda:database.hlen(prefix+'credential:messaging:outbox')==0)
            evidence['checks'].append('Outbox resumes automatically after broker recovery')
        evidence['completedAt']=datetime.now(timezone.utc).isoformat(); evidence['passed']=True
        out=args.evidence; out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(evidence,indent=2)+'\n')
        print(json.dumps(evidence,indent=2))
    finally:
        if broker: broker.stop()
        fixture.stop(0).wait()
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try: process.wait(8)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
        for logfile in files: logfile.close()
        for key in database.scan_iter(prefix+'*'): database.delete(key)
        http.close()

if __name__=='__main__': main()
