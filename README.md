# Procore RFI Deadline Monitor

An RFI deadline monitor for the Procore API that notifies **the person who
actually has to act** — not whoever the `ball_in_court` field happens to
point at.

Built by a licensed civil engineer, which is why the business rules are
the interesting part.

---

## The problem

An overdue RFI stalls work, and nobody notices until it's late. The
obvious fix is a daily job that reads open RFIs, checks `due_date`, and
pings `ball_in_court`.

That fix is wrong, and it fails silently.

---

## Four things the Procore API does that the docs don't mention

These cost hours to discover. Written down so you don't have to.

### 1. `403 App is not connected to this company`

`GET /companies` works with nothing but a Client ID and Secret. But
`/projects` and `/rfis` return:

```json
{ "message": "App is not connected to this company" }
```

The Custom App must be **installed on the company** first. The full
sequence:

1. Create the app in the Developer Portal
2. Add a **User Level Authentication** component
3. Create a **Version**
4. Company Tools → Admin → **App Management → Install Custom App**

Skipping step 4 looks like an OAuth problem. It isn't.

### 2. Replying to an RFI does not close it

```
POST /rest/v1.0/rfis/{id}/replies   { "official": true }
→ status stays "open", time_resolved stays null
```

```
PATCH /rest/v1.0/rfis/{id}          { "rfi": { "accepted": true } }
→ status "closed", time_resolved populated
```

Two separate operations. Which means there is a real state of
**answered but not accepted** — common on site: the architect replied,
the manager never formally accepted, and the metric still counts it as
pending.

### 3. `ball_in_court` does not follow the reply

This is the one that matters.

After an official reply, `ball_in_court` **still points to whoever
answered**. Procore does not move it to the RFI manager who has to
accept.

A monitor that trusts that field will:

- chase the person who already did their part
- **never chase the person who has to accept**
- leave the overdue RFI silent

On close, the field empties to `null` — so it's reliable at the start and
at the end, and blind in the middle.

### 4. The list endpoint never tells you a reply exists

`GET /rfis` returns each RFI's `questions[]`, and the obvious place to look
for a reply is `questions[].answers`. It's always empty — confirmed
against a real RFI with a genuine official reply on record, not just in
sandbox theory.

The reply lives behind its own endpoint:

```
GET /rest/v1.0/projects/{project_id}/rfis/{rfi_id}/replies
→ [{ "official": true, "plain_text_body": "...", ... }]
```

One extra call per open RFI, but it's the only way to know "awaiting
reply" just became "awaiting acceptance."

---

## The fix: three states, not two

| State | Condition | Who has to act |
|---|---|---|
| Awaiting reply | `open`, no official reply on `GET .../replies` | `ball_in_court` |
| **Awaiting acceptance** | `open`, an `official: true` reply exists | **`rfi_manager`** |
| Closed | `closed` or `time_resolved` set | nobody |

Urgency from `due_date`: overdue (negative), critical (0–2 days),
attention (3–7), fine (>7, dropped).

Notifications are **grouped by responsible party**, and the two states are
labelled separately — "awaiting your reply" and "awaiting your
acceptance" are different actions. Nobody wants fifteen separate alerts;
they want one that says "three RFIs need you this week".

Nothing to send? Send nothing. Silence when there's no news is a feature.

---

## Repo contents

```
src/                the monitor
docs/api-notes.md   field reference and the undocumented extras
sandbox/            script to recreate a test scenario from scratch
```

### Fields that matter

```
due_date            response deadline
time_resolved       null until accepted
status              open | closed
accepted            true closes the RFI
ball_in_court       NOT reliable after a reply
ball_in_court_role  assignees | rfi_manager | creator — handle all three
rfi_manager         who accepts
GET .../replies     official:true = the real "has a reply" signal
```

### Fields present in responses but absent from the documented schema

`change_events` · `correspondences` · `instructions` ·
`coordination_issues` · `title` (duplicates `subject`) · `location_id` ·
`previous_revision_id`

Empty or null in a fresh sandbox, but they exist. Build your parser
accordingly.

---

## Reproducing the test scenario

`sandbox/recriar_rfis.py` creates six RFIs with dates relative to today —
overdue, due today, due in 2, 5 and 10 days, plus one answered and
accepted. Standard library only, no dependencies.

Credentials come from environment variables. Nothing is committed.

---

## Author

Licensed civil engineer (CREA-MS, Brazil), 15 years in public
infrastructure — procurement, cost estimating, contract management and
site supervision. Procore certified: Project Manager (Core Tools) and
Project Manager (Project Management).

I build automation for construction processes. The value isn't wiring the
endpoints — it's knowing what happens on site when the process stops.

---

## License

MIT

## Antes de publicar este repositorio

O script em `sandbox/` le credenciais e IDs de variavel de ambiente. Nada
e hardcoded. Confirme antes do primeiro push:

```bash
grep -rnE "client_secret[\"=: ]+[a-zA-Z0-9]{10}|[0-9a-f]{32}" .
```

Saida vazia (fora de nomes de variavel) = pode publicar.
