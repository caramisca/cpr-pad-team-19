# Lab 4: integrarea finala si prezentarea

Repartizare: screenshoturile Dariei din 3 noiembrie, randul Mihai plus tabelul
"Everyone, in their own two services". Cerintele oficiale sunt in `PAD_LAB_4_V1.pdf`.
Documentul separa o demonstratie a partii lui Mihai de demonstrarea tuturor cerintelor echipei.

## Ordinea de finalizare

| Cine | Livrabil necesar pentru stack-ul comun | Criteriu de acceptare |
|---|---|---|
| Mihai | Topics/fan-out, lista topics, transport gRPC; Applicant/Credential; contract si Prometheus | Livrabile integrate, teste proprii verzi, imagini publice si pointere la main; metrici de la ambele replici |
| Diana | Subscriber request/reply queues; Gateway, load balancing/rerutare, Grafana; serviciile ei | Cererile trec efectiv prin cozi; filtrele URL ajung intacte; gRPC/JSON compatibile; rerutare demonstrata; dashboard pentru toate serviciile |
| Andi | Breaker in broker, durable queues, DLC si listare; download loguri in Gateway; serviciile lui | Restart broker fara pierderi; mesaj invalid vizibil in DLC; endpoint de loguri utilizabil; probe cu eroare/trip |
| Daria | Broker/SD, propriile servicii, Compose si release check/runbook comun | Imagini publicate; broker real in Compose; toate adaptoarele activate si gitlink-uri la release-uri; full-stack smoke |
| Fiecare | README/Postman, loguri colectabile, mesaje prin broker, SD topics, gRPC, ACK dupa commit, metrici | Proba cu serviciul real al autorului, fara fixture ascuns |

1. Diana finalizeaza request/reply queues si corecteaza Gateway: query string, dependentele
   gRPC/protobuf, testele rutelor eliminate si versiunea noua a imaginii.
2. Andi conecteaza breaker-ul si store-ul durabil/DLC la extensiile brokerului si adauga download
   loguri. Validati impreuna cu Diana rerutarea si actualizarea load-ului din health/SD.
3. Fiecare autor publica adaptoarele reale si confirma porturile/proto, topics, ACK si metrici.
   Credential trebuie testat cu University Record real; un receptor de test nu demonstreaza asta.
4. Daria integreaza brokerul, SD si release-urile colegilor in Compose. Partea de configurare a
   serviciilor lui Mihai este pregatita in `docker-compose.lab4-mihai.yml`; se aplica numai cand
   exista brokerul si University Record real cu gRPC. Nu porniti overlay-ul singur ca dovada E2E.
5. CPR se integreaza prin PR cu peer approval; dupa verificarea publica a imaginilor si proba
   comuna se face release-ul CPR dev -> main prin merge commit. Nu mutati pointere la dev.

## Verificarea publica a release-urilor

Pentru fiecare aplicatie: CI de publicare reusit pentru commitul main final, tag nou de versiune,
manifest public linux/amd64 si linux/arm64, `latest` cu acelasi digest. Tagul dintr-un README sau
un build local nu confirma publicarea. Actualizati IMAGES in checker si tagul Compose impreuna.

`python scripts/check_lab3_release.py --require-published` continua sa verifice versiunile
independente ale aplicatiilor din Compose. Integrarea/checker-ul Lab 4 al Dariei trebuie sa adauge
brokerul si sa verifice activarea comunicarii Lab 4; checker-ul vechi singur nu probeaza aceasta.

## Proba comuna obligatorie inainte de prezentare

Folositi un proiect Docker Compose separat pentru demonstratie si date de test unice. Pastrati
`.env` local si nu includeti chei API, parole, corpuri sensibile sau configuratia rezolvata in dovezi.

| Proba | Rezultat asteptat | Cerinta |
|---|---|---|
| Pornire si health | Toate replicile reale in SD, fiecare cu adresa/instanceId propriu | Baza integrarii |
| Client -> Gateway -> broker queue -> serviciu | Status, JSON, Content-Type, requestId; corelatie request/reply verificabila | G5/G6 |
| Generare Applicant -> Credential -> University Record | Lookup real prin gRPC, fara hop REST business ascuns | G5/G8 |
| GET /applicants?sessionId=... si /credentials?applicantId=... | Liste contin numai obiectele cerute, inclusiv prin Gateway | Contract |
| Publish session.closed | Applicant sters dupa commit, apoi applicant.deleted curata Credential | G6 |
| Publish duplicate pe alta replica | ACK dupa commit, fara repetarea efectelor | G9 serviciu |
| ListTopics + o cerere concurenta | Topics corecte, thread-per-request in broker | G7 |
| /internal/mock-events/* pe Gateway | 404 ROUTE_NOT_FOUND | G8 |
| Download loguri | Fisier utilizabil, corelat prin requestId/instanceId | G4 |
| Restart broker cu mesaje acceptate/neconfirmate | Mesajele sunt recuperate si procesate dupa restart | G9 broker |
| Mesaj imposibil de procesat | Persista in DLC si apare in endpointul de listare | G9 DLC |
| Oprire replica in timpul cererii | Circuit trip, cererea eligibila rerutata fara pierdere | G10 HA |
| Load CRITICAL pe o replica | Date de load reale alimenteaza selectorul, traficul evita replica | G10 LB |
| Prometheus/Grafana | Doua targeturi UP per serviciu, metrici si panouri reale, fara No data ascuns | G10 monitoring |

In cele doua colectii Postman ale lui Mihai setati `runLab4GatewayChecks=true` pentru verificarea
Content-Type si a filtrelor pe Gateway-ul final. Folositi un dataset care include si obiecte
din alta sesiune/ale altui applicant; o lista goala singura nu dovedeste pastrarea filtrului.

Pentru monitorizare:

```powershell
python scripts/check_lab4_monitoring.py --scope team --evidence docs/evidence/lab4-team-monitoring.json
```

G9/G10 nu pot fi declarate complete prin faptul ca interfelele/extensiile exista. Pentru POST-uri,
retry dupa un rezultat ambiguu trebuie sa respecte idempotenta domeniului, conform contractului.

## Cum isi prezinta Mihai partea

1. **Arhitectura si contract (aproximativ un minut):** arata `contracts/messaging.proto` si
   `docs/architecture-diagram-lab4.mmd`. Separa `Call` request/reply de `Publish`/`Deliver` pentru
   topics. Explica faptul ca producatorul publica topicul fara lista consumatorilor.
2. **Broker (aproximativ un minut):** in broker arata `app/topics.py` (o copie per serviciu logic,
   leasing, FIFO, ACK dupa COMMITTED) si `app/grpc_transport.py` (HTTP/2, deadline, thread per RPC).
   Arata lista topics din instanta demonstratiei.
3. **Cele doua servicii (aproximativ doua minute):** arata `Messaging/ServiceRpc.cs`,
   `Messaging/BrokerHttpHandler.cs`, `Messaging/MessageState.cs` si tranzactiile Redis din repository.
   Explica inbox comun replicilor si outbox atomic cu mutatia; demonstreaza filtre/headere si
   session.closed -> applicant.deleted -> cleanup Credential.
4. **Observabilitate (aproximativ un minut):** arata /metrics si logurile NDJSON private,
   ambele replici in Prometheus, apoi panourile Grafana comune. Durata medie calculata din
   duration_sum/request_count nu este P95; nu o prezenta drept percentila.
5. **Dovezi si limite:** arata CI, manifestele publice si JSON-urile de smoke. Daca proba foloseste
   University Record fixture, spune asta explicit. Separat, Andi demonstreaza persistenta/DLC,
   Diana cozile/rerutarea, iar Daria pornirea si release-ul comun.

## Intrebari probabile

- **De ce o coada per serviciu, nu per replica?** Fiecare serviciu interesat primeste evenimentul;
  replicile lui concureaza pentru aceeasi copie, evitand multiplicarea efectelor.
- **Cand se confirma un mesaj?** Dupa commitul mutatiei si al markerului inbox; pentru un mesaj
  invalid, numai dupa handoff durabil in DLC. Erorile temporare cer RETRY.
- **De ce outbox?** Mutatia si intentia de publicare se scriu atomic, iar publisher-ul poate relua
  acelasi messageId dupa restart. Outbox-ul singur nu face brokerul durabil.
- **De ce gRPC?** Contract protobuf tipizat si transport HTTP/2 cu deadline/requestId; handler-ele
  de business sunt reutilizate direct, fara REST loopback in adaptoarele lui Mihai.
- **Cum dovedesti replica folosita?** SD expune adrese fizice distincte; raspunsul/logurile includ
  X-Instance-Id si requestId, iar Prometheus scrapeaza fiecare adresa.

Decizia de prezentare completa se ia dupa toate probele comune. Daca lipsesc, prezentati exact
ce functioneaza si cerintele ramase, fara a declara Grade 9/10 integral indeplinite.
