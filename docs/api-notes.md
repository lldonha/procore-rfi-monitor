# Notas da API — Procore RFI

Referência de campos e comportamentos observados em ambiente de
desenvolvimento (sandbox oficial do Procore). Complementa a documentação
oficial em developers.procore.com.

Ver o README na raiz para os três comportamentos não documentados que mais
importam (app não conectado à company, reply não fecha RFI,
`ball_in_court` não segue a resposta).

## Autenticação

Fluxo OAuth2 Authorization Code, variante "installed app" (OOB —
`redirect_uri=urn:ietf:wg:oauth:2.0:oob`), autenticação em nome do usuário
(não Service Account).

Pré-requisitos no Developer Portal, na ordem que realmente funciona:

1. Criar o app (gera Client ID + Client Secret)
2. Adicionar um **Data Connector Component** do tipo **User Level
   Authentication** — sem isso o token OAuth funciona e `GET /companies`
   funciona, mas qualquer endpoint de company/project retorna
   `403 App is not connected to this company`
3. Criar uma **Version** do app (gera a chave usada para instalação)
4. Instalar o app na company: `Company Tools → Admin → App Management →
   Install Custom App`

Token exchange:

```
POST https://login-sandbox.procore.com/oauth/token/
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code=CODIGO_RECEBIDO
&client_id=SEU_CLIENT_ID
&client_secret=SEU_CLIENT_SECRET
&redirect_uri=urn:ietf:wg:oauth:2.0:oob
```

O código de autorização é de uso único e expira rápido — se a troca falhar
com `invalid_grant`, gere um código novo em vez de reusar.

Refresh:

```
grant_type=refresh_token
&refresh_token=SEU_REFRESH_TOKEN
&client_id=SEU_CLIENT_ID
&client_secret=SEU_CLIENT_SECRET
```

## Header obrigatório

Todo endpoint dependente de company/project (praticamente tudo exceto
`/companies`) exige:

```
Procore-Company-Id: <id da company>
```

## Estrutura da resposta de `GET /rfis` (lista)

Cada item vem com o RFI completo (não é uma versão resumida) — os campos
abaixo são os que a lógica de classificação usa:

```json
{
  "id": 111495,
  "number": "4",
  "subject": "...",
  "due_date": "2026-09-04",
  "status": "open",
  "time_resolved": null,
  "ball_in_court": { "id": 99519, "login": "...", "name": "..." },
  "ball_in_courts": [ ... ],
  "rfi_manager": { "id": 99519, "login": "...", "name": "..." },
  "assignee": { "id": 100299, "login": "...", "name": "..." },
  "assignees": [ { "...": "...", "response_required": false } ],
  "questions": [ { "id": 111494, "body": "...", "errors": {} } ]
}
```

Observações práticas:

- `ball_in_court` pode ser `null` (visto em RFIs fechados — o campo esvazia
  no fechamento).
- `ball_in_court_role` (não visto nos dados de teste, mas documentado pela
  API) indica se quem está com a bola é `assignees`, `rfi_manager` ou
  `creator` — tratar os três casos, não assumir sempre `assignees`.
- **`questions[].answers` nunca vem populado por `GET /rfis`, mesmo quando
  existe uma resposta oficial real** (confirmado 2026-09-04 contra um RFI
  do sandbox com resposta oficial gravada — `questions[].answers` continua
  `[]`/ausente). O monitor **não pode** detectar "tem resposta" por esse
  campo. O sinal real é um endpoint separado:
  `GET /rest/v1.0/projects/{project_id}/rfis/{rfi_id}/replies`, que retorna
  uma lista de replies com `official: true` na que foi marcada como
  resposta oficial. O workflow precisa buscar replies por RFI (uma chamada
  extra por RFI aberto) e anexar o resultado como `rfi["replies"]` antes de
  chamar `classify_state()` — ver `src/monitor.py::_has_answer()`.
- `created_by` é o usuário por trás do token OAuth, não o solicitante do
  RFI necessariamente.

## Campos presentes na resposta mas ausentes da doc oficial

`change_events`, `correspondences`, `instructions`, `coordination_issues`,
`title` (duplica `subject`), `location_id`, `previous_revision_id`. Vazios
ou nulos no sandbox testado, mas existem — o parser deve tolerá-los.

## Paginação

Não exercitada nos testes (o cenário de sandbox usado tinha só 6 RFIs, bem
abaixo de qualquer limite de página). A API do Procore segue paginação
baseada em `page`/`per_page` documentada oficialmente — nada de
comportamento surpresa observado aqui. Ajustar esta seção se um projeto
real revelar algo diferente.

## Rate limit

Não observado nos testes — volume baixo demais para atingir qualquer
limite. Sem dado próprio para reportar aqui; seguir o que a documentação
oficial define até haver evidência em contrário.

## Payloads de escrita usados

```
POST /rest/v1.0/rfis?project_id={id}
{ "rfi": { "subject", "due_date", "assignee_ids": [...], "rfi_manager_id", "question": { "body" } } }
```

`assignee_ids` é exigido mesmo a doc não deixando isso óbvio — sem ele o
erro é `{"errors":{"assignees":["required"]}}`.

```
POST /rest/v1.0/rfis/{id}/replies?project_id={id}
{ "reply": { "body", "official": true } }
```

Grava a resposta mas **não** fecha o RFI (`status` continua `open`,
`time_resolved` continua `null`).

```
GET /rest/v1.0/projects/{project_id}/rfis/{rfi_id}/replies
```

Único jeito confiável de saber se um RFI tem resposta oficial (ver nota
acima sobre `questions[].answers`). Retorna uma lista; cada item tem
`id`, `answer_date`, `plain_text_body`, `created_by`, `official` (bool).
Lista vazia = sem replies ainda. `Procore-Company-Id` continua obrigatório
no header.

```
PATCH /rest/v1.0/rfis/{id}?project_id={id}
{ "rfi": { "accepted": true } }
```

Isso sim fecha o RFI: `status` vira `closed` e `time_resolved` é populado.
