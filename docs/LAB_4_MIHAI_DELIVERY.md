# Lab 4: partea lui Mihai / caramisca, 9 noiembrie 2026

## Identitate si repartizare verificate

Contul GitHub autentificat este `caramisca`; identitatea Git globala este tot `caramisca`.
In conversatia Telegram apari drept **Mihai Caraman**, iar README-ul CPR iti atribuie
`applicant-service` si `credential-service`. Randul **Mihai** din tabel este partea ta;
randul **You** este al Dariei, autoarea repartizarii.

PDF-ul Lab 4 stabileste cerintele laboratorului; tabelul transmis de echipa le imparte pe persoane.
Nu am tratat mesajele colegilor drept autorizatie de a le aproba sau integra automat PR-urile.

Verificare GitHub: [CPR #228](https://github.com/caramisca/cpr-pad-team-19/pull/228) este merged
din 4 noiembrie. Cele trei PR-uri recente cerute de Daria sunt toate merged in `dev`, pe 9 noiembrie:
[SD #11](https://github.com/DariaRateeva/service-discovery/pull/11),
[Broker #5](https://github.com/DariaRateeva/message-broker/pull/5),
[CPR #244](https://github.com/caramisca/cpr-pad-team-19/pull/244).
La inceputul auditului, codul de topics/gRPC al lui Mihai nu exista in ramurile lor `dev`.

## PR-uri livrate

| Repository | PR catre dev |
|---|---|
| Message Broker | [#6](https://github.com/DariaRateeva/message-broker/pull/6) |
| Applicant | [#11](https://github.com/caramisca/applicant-service/pull/11) |
| Credential | [#12](https://github.com/caramisca/credential-service/pull/12) |
| CPR | [#271](https://github.com/caramisca/cpr-pad-team-19/pull/271) |

Contractul este pregatit pentru review; fiecare PR contine numai partea implementata de Mihai.
Nu au fost integrate automat PR-uri si nu s-au facut push-uri directe pe dev/main.

## Ce am implementat

| Partea ta | Livrabil |
|---|---|
| CPR: envelope, topic names, `.proto` | Contract v1, schema comuna si copii identice in cele trei implementari |
| Broker G6b | Fan-out catre serviciile abonate din SD, o coada/copie per serviciu logic, leasing, FIFO, confirmare dupa COMMITTED |
| Broker G7b | HTTP `GET /topics` si gRPC `ListTopics`, bazate pe abonamentele live din SD |
| Broker G8a | gRPC Call/Publish/Deliver, deadline si request ID, cate un thread nou per RPC, puncte de integrare pentru Diana/Andi |
| CPR G3a | README actualizat, diagrama Mermaid, documentatie de integrare si status explicit |
| CPR G10c | Prometheus, descoperirea tuturor replicilor, trei reguli de alerta si query-uri pentru Grafana Dianei |
| Applicant + Credential G3/G4 | Sectiuni README, doua colectii Postman, `/internal/logs` NDJSON pentru colectorul lui Andi |
| Applicant + Credential G5/G8 | Mod `Grpc`: apelurile de business trec prin broker; serverele gRPC invoca direct handler-ele existente |
| Applicant + Credential G6 | Abonamente SD si evenimente reale: session.closed -> applicant.deleted -> credential cleanup |
| Applicant + Credential G9 | Redis outbox atomic cu create/delete, inbox comun replicilor, cleanup idempotent, COMMITTED/RETRY/REJECTED distincte |
| Applicant + Credential G10 | Contoare requests/errors, durata cumulata si active requests la `/metrics` |

Noile versiuni ale celor doua servicii sunt pregatite ca **0.5.0**, inclusiv tagurile workflow-ului.
Nu suprascriu release-ul 0.4.0. Comportamentul Lab 4 se activeaza explicit prin
`Messaging__Enabled=true`, `Messaging__BrokerUrl` si modul dependentei `Grpc`.
Niciun `/internal/mock-events` nu exista in cele doua servicii ale tale; adaptoarele vechi ale
celorlalti autori se retrag in PR-urile lor.

Detaliile API si punctele concrete de integrare sunt in
[MESSAGE_BROKER_CONTRACT.md](MESSAGE_BROKER_CONTRACT.md).

## Dovezi si verificari

- Broker: **97 teste** trecute, inclusiv HTTP/2 real, fan-out, duplicate concurente, capacitate
  atomica, confirmare dupa commit, handoff DLC si thread separat per RPC.
- Applicant: **111 teste**, fara skip; coverage aproximativ **90%**, peste pragul CI de 80%.
- Credential: **134 teste**, fara skip; coverage aproximativ **90.7%**.
- CPR: **6 teste** existente trecute si verificarea configuratiei Lab 3 trecuta.
- Cele patru copii ale proto sunt identice; **57 scripturi Postman** au sintaxa JavaScript valida.
- Toate cele trei imagini modificate au fost construite local pentru Linux/amd64, cu utilizatori
  non-root. Nu sunt prezentate drept imagini publicate pe DockerHub sau dovada pentru ARM64.
- `promtool check config`: configuratie valida, toate cele **3 reguli** valide.
- Prometheus a avut **6 targeturi UP**: doua Applicant, doua Credential, broker si el insusi.

[Smoke nativ](evidence/lab4-mihai-smoke-2026-11-09.json): .NET 8.0.33, doua replici per serviciu,
Redis real, Service Discovery real, gRPC fara Gateway, cleanup prin evenimente, duplicate la alta
replica si outbox pastrat dupa restart si trimis dupa revenirea brokerului. University Record este
un **receptor gRPC de test explicit**, nu implementarea Dianei.

[Smoke containere](evidence/lab4-mihai-containers-2026-11-09.json): gRPC intre containere Linux,
citire din ambele replici Credential, o singura copie de topic per serviciu si stergere verificata
dupa commit; inventarul Prometheus include adresele fizice.

## Ce mai necesita integrarea echipei

Aceste puncte sunt dependente reale, nu parti declarate gata prin faptul ca testele tale trec:

1. **Review comun** pentru contract si broker. PR-urile merg catre `dev`, fara merge automat.
2. **Diana:** cozile request/reply, rutarea Gateway, load balancing/rerutare, adaptorul gRPC al
   serviciilor ei, retragerea rutelor private din Gateway si dashboard-urile Grafana.
   `broker.request_dispatch`, `broker.selector` si query-urile Prometheus sunt pregatite.
3. **Andi:** circuit breakers, store durabil pentru broker, DLC si colectorul de loguri Gateway.
   `topic_store=` si `topic_bus.on_rejected` sunt punctele pregatite; `/internal/logs` este disponibil.
4. **Daria:** integrarea brokerului in Compose, adaptoarele serviciilor ei si release check/runbook
   comun. SD cu topics este deja integrat in `dev`.
5. **Fiecare autor:** implementarea aceluiasi `ServiceEndpoint` in serviciile proprii si expunerea
   metricilor; acum sunt instrumentate brokerul si cele doua servicii ale lui Mihai.
6. Dupa review si integrare: release-uri 0.5.0, verificarea manifestelor publice amd64/arm64,
   pointere de submodule, configuratia Compose comuna si demonstratia E2E a tuturor serviciilor.

**Limita Grade 9:** store-ul implicit al brokerului este in memorie. Outbox-ul serviciilor este
durabil, dar un eveniment acceptat de broker poate fi pierdut la restartul brokerului pana cand
Andi conecteaza store-ul durabil. Nu se poate declara inca fiabilitatea end-to-end pentru toata echipa.

## Repetarea verificarii tale

Pastreaza patru checkout-uri cu numele `broker`, `applicant`, `credential`, `discovery`, in acelasi
director de lucru, fiecare la PR-ul corespunzator sau la `dev` dupa integrare. Instaleaza dependentele
din `scripts/requirements-lab4-smoke.txt` intr-un venv si compileaza cele doua servicii in Release.
Ai nevoie de runtime .NET 8 si un Redis separat pentru test, implicit pe localhost:16394.

```powershell
dotnet build <workspace>/applicant/ApplicantService.sln -c Release
dotnet build <workspace>/credential/CredentialService.sln -c Release
python scripts/lab4_mihai_smoke.py --workspace <workspace> --dotnet <dotnet8-runtime> --evidence <evidence.json>
```

Scriptul porneste numai procesele lui, foloseste prefix Redis unic si le curata la final.
Pentru verificarea containerelor, ruleaza `scripts/lab4_container_probe.py` in containerul brokerului.
Configuratia Prometheus se porneste cu overlay-ul descris in [monitoring/README.md](../monitoring/README.md).

In Postman, folderele noi de diagnostic intern sunt **dezactivate implicit**:
`runInternalDiagnostics=false`. Activeaza-le doar cu un port-forward de test si `internalBaseUrl`
potrivit. Cererile publice de business continua sa foloseasca `baseUrl` al Gateway-ului.

Modificarile locale existente pentru Lab 3 au fost pastrate in directorul principal. Toata
implementarea Lab 4 este in checkout-urile separate din `.local/lab4-mihai`.
