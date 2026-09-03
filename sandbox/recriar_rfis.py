#!/usr/bin/env python3
"""
recriar_rfis.py
================

Recria, no sandbox do Procore, o conjunto de 6 RFIs usado para demonstrar o
monitor de prazos (3 estados: pendente de resposta / aguardando aceite / fechado).

As datas de vencimento são calculadas em relação à data de execução do script
(date.today()), então o cenário fica sempre "fresco":

  1. vencido há 3 dias   -> fica em aberto, sem resposta      (pendente de resposta)
  2. vence hoje           -> fica em aberto, sem resposta      (pendente de resposta)
  3. vence em 2 dias      -> fica em aberto, sem resposta      (pendente de resposta / crítico)
  4. vence em 5 dias      -> fica em aberto, sem resposta      (pendente de resposta / atenção)
  5. vence em 10 dias     -> fica em aberto, sem resposta      (pendente de resposta / ok)
  6. vencido há 5 dias    -> recebe resposta oficial + PATCH accepted:true -> FECHADO

Além disso, o RFI #1 (vencido há 3 dias) recebe uma resposta oficial via
POST .../replies (official: true) MAS NÃO é aceito -> fica "aguardando aceite"
(status continua "open", time_resolved continua null). Esse é o caso que
demonstra a diferença entre responder e fechar um RFI na API do Procore.

Só usa biblioteca padrão do Python (urllib), sem dependências externas.

CONFIGURAÇÃO (.env, não versionado):
  PROCORE_CLIENT_ID          - Client ID do app (Developer Portal)
  PROCORE_CLIENT_SECRET      - Client Secret do app
  PROCORE_COMPANY_ID         - id da company no sandbox (ver ambiente.md)
  PROCORE_PROJECT_ID         - id do project no sandbox (ver ambiente.md)

  Opcionais (se ausentes, o script busca os usuários do projeto via API e
  tenta casar pelo prefixo do login; se não conseguir, pede para você
  escolher manualmente):
  PROCORE_USER_DEMO_ID       - id do usuário "API Support" (implementation+demo@...)
  PROCORE_USER_SUB_ID        - id do usuário "Test Subcontractor" (implementation+sub@...)
  PROCORE_USER_ARCH_ID       - id do usuário "Test Architect" (implementation+arch@...)

  Opcionais, com default para o ambiente de sandbox:
  PROCORE_AUTH_BASE          - default: https://login-sandbox.procore.com
  PROCORE_API_BASE           - default: https://sandbox.procore.com

USO:
  python3 recriar_rfis.py

O script imprime a URL de autorização OAuth (fluxo "installed app" / OOB),
você abre no navegador, loga, autoriza, cola o código de volta no terminal.

IMPORTANTE - coisas que descobrimos na prática e que a documentação não deixa
óbvio (ver ambiente.md para o passo a passo completo):
  - O app PRECISA ter um Data Connector Component ("User Level Authentication"),
    uma Version publicada, e precisa estar instalado na company via
    Company Tools > Admin > App Management > Install Custom App. Sem isso,
    /oauth/token funciona e /companies funciona, mas /projects e /rfis
    retornam 403 "App is not connected to this company".
  - POST /rfis exige "assignee_ids" no payload mesmo a doc de campos
    obrigatórios não deixando isso claro (o erro retornado é
    {"errors":{"assignees":["required"]}}).
  - POST /rfis/{id}/replies com official:true NÃO fecha o RFI. Só
    PATCH /rfis/{id} com {"rfi":{"accepted":true}} fecha e popula time_resolved.

Se algum payload abaixo tiver mudado na API real, o script imprime o corpo
de erro retornado pelo Procore para você ajustar rapidamente - não estamos
adivinhando silenciosamente.
"""

import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# .env loader (sem dependências externas)
# ---------------------------------------------------------------------------

def load_dotenv(path=".env"):
    env = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    # variáveis de ambiente reais têm prioridade sobre o .env
    env.update({k: v for k, v in os.environ.items() if k.startswith("PROCORE_")})
    return env


ENV = load_dotenv()

AUTH_BASE = ENV.get("PROCORE_AUTH_BASE", "https://login-sandbox.procore.com")
API_BASE = ENV.get("PROCORE_API_BASE", "https://sandbox.procore.com")
CLIENT_ID = ENV.get("PROCORE_CLIENT_ID")
CLIENT_SECRET = ENV.get("PROCORE_CLIENT_SECRET")
COMPANY_ID = ENV.get("PROCORE_COMPANY_ID")
PROJECT_ID = ENV.get("PROCORE_PROJECT_ID")
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"

REQUIRED = {
    "PROCORE_CLIENT_ID": CLIENT_ID,
    "PROCORE_CLIENT_SECRET": CLIENT_SECRET,
    "PROCORE_COMPANY_ID": COMPANY_ID,
    "PROCORE_PROJECT_ID": PROJECT_ID,
}
missing = [k for k, v in REQUIRED.items() if not v]
if missing:
    sys.exit(
        "Faltam variáveis no .env (veja ambiente.md para o passo a passo): "
        + ", ".join(missing)
    )


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib)
# ---------------------------------------------------------------------------

def _read_error_body(err):
    try:
        return err.read().decode("utf-8", errors="replace")
    except Exception:
        return "<sem corpo>"


def http_form_post(url, fields):
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[erro HTTP {e.code}] POST {url}\n{_read_error_body(e)}", file=sys.stderr)
        raise


def api_request(method, path, token, body=None, query=None):
    url = f"{API_BASE}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Procore-Company-Id", str(COMPANY_ID))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        print(f"[erro HTTP {e.code}] {method} {url}\n{_read_error_body(e)}", file=sys.stderr)
        raise


# ---------------------------------------------------------------------------
# OAuth (fluxo "installed app" / OOB - mesmo usado interativamente no chat)
# ---------------------------------------------------------------------------

def oauth_get_token():
    authorize_url = (
        f"{AUTH_BASE}/oauth/authorize?response_type=code"
        f"&client_id={urllib.parse.quote(CLIENT_ID)}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    )
    print("\n1) Abra esta URL no navegador, faça login no sandbox e autorize o app:\n")
    print(f"   {authorize_url}\n")
    code = input("2) Cole aqui o código retornado: ").strip()

    status, payload = http_form_post(
        f"{AUTH_BASE}/oauth/token/",
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
        },
    )
    return payload["access_token"]


# ---------------------------------------------------------------------------
# Resolução dos 3 usuários do sandbox
# ---------------------------------------------------------------------------

def resolve_users(token):
    demo_id = ENV.get("PROCORE_USER_DEMO_ID")
    sub_id = ENV.get("PROCORE_USER_SUB_ID")
    arch_id = ENV.get("PROCORE_USER_ARCH_ID")

    if demo_id and sub_id and arch_id:
        return int(demo_id), int(sub_id), int(arch_id)

    print("\nBuscando usuários do projeto para identificar os 3 papéis padrão do sandbox...")
    _, users = api_request("GET", f"/rest/v1.0/projects/{PROJECT_ID}/users", token)

    def find(prefix):
        for u in users:
            if u.get("login", "").startswith(prefix):
                return u["id"]
        return None

    demo_id = demo_id or find("implementation+demo@")
    sub_id = sub_id or find("implementation+sub@")
    arch_id = arch_id or find("implementation+arch@")

    if not all([demo_id, sub_id, arch_id]):
        print("\nNão foi possível casar automaticamente os 3 usuários padrão.")
        print("Usuários encontrados no projeto:")
        for u in users:
            print(f"  id={u['id']}  login={u.get('login')}  name={u.get('name')}")
        sys.exit(
            "Defina PROCORE_USER_DEMO_ID / PROCORE_USER_SUB_ID / PROCORE_USER_ARCH_ID"
            " no .env com os ids corretos e rode novamente."
        )

    return int(demo_id), int(sub_id), int(arch_id)


# ---------------------------------------------------------------------------
# RFIs
# ---------------------------------------------------------------------------

def create_rfi(token, subject, question_body, due_date, assignee_id, rfi_manager_id):
    body = {
        "rfi": {
            "subject": subject,
            "due_date": due_date.isoformat(),
            "assignee_ids": [assignee_id],
            "rfi_manager_id": rfi_manager_id,
            "question": {"body": question_body},
        }
    }
    status, payload = api_request(
        "POST", "/rest/v1.0/rfis", token, body=body, query={"project_id": PROJECT_ID}
    )
    return payload


def reply_official(token, rfi_id, reply_body):
    body = {"reply": {"body": reply_body, "official": True}}
    return api_request(
        "POST", f"/rest/v1.0/rfis/{rfi_id}/replies", token, body=body,
        query={"project_id": PROJECT_ID},
    )


def accept_rfi(token, rfi_id):
    body = {"rfi": {"accepted": True}}
    return api_request(
        "PATCH", f"/rest/v1.0/rfis/{rfi_id}", token, body=body,
        query={"project_id": PROJECT_ID},
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    token = oauth_get_token()
    demo_id, sub_id, arch_id = resolve_users(token)
    today = date.today()

    plano = [
        {
            "subject": "Divergência entre projeto estrutural e arquitetônico no eixo B-C, pavimento 2",
            "question": "Viga aparente no forro conflita com a posição de pilar indicada no projeto arquitetônico. Qual documento prevalece?",
            "due_date": today - timedelta(days=3),
            "assignee_id": arch_id,
            "aguardando_aceite": True,   # recebe resposta oficial, mas não é aceito
            "fechar": False,
        },
        {
            "subject": "Especificação de acabamento de piso não localizada no memorial descritivo",
            "question": "A área do hall de entrada do pavimento térreo não possui indicação de revestimento de piso no memorial descritivo. Qual especificação deve ser aplicada?",
            "due_date": today,
            "assignee_id": sub_id,
            "aguardando_aceite": False,
            "fechar": False,
        },
        {
            "subject": "Interferência entre tubulação hidráulica e eletrodutos no forro do 3º pavimento",
            "question": "A prumada de água fria cruza com o eletroduto de alimentação do QDL-03 no forro do 3º pavimento. Como deve ser resolvida essa interferência?",
            "due_date": today + timedelta(days=2),
            "assignee_id": demo_id,
            "aguardando_aceite": False,
            "fechar": False,
        },
        {
            "subject": "Necessidade de detalhamento da fixação da fachada ventilada no encontro com a platibanda",
            "question": "O projeto de fachadas não apresenta detalhe construtivo para a fixação da fachada ventilada no encontro com a platibanda. Poderia fornecer o detalhamento?",
            "due_date": today + timedelta(days=5),
            "assignee_id": arch_id,
            "aguardando_aceite": False,
            "fechar": False,
        },
        {
            "subject": "Confirmação de bitola do cabeamento elétrico do quadro de força QF-01",
            "question": "O memorial de cálculo indica bitola de 25mm² para os condutores do QF-01, enquanto a prancha elétrica indica 35mm². Qual bitola deve ser considerada?",
            "due_date": today + timedelta(days=10),
            "assignee_id": sub_id,
            "aguardando_aceite": False,
            "fechar": False,
        },
        {
            "subject": "Confirmação de especificação do revestimento acústico do forro do auditório",
            "question": "O memorial descritivo não especifica o índice de absorção acústica exigido para o forro do auditório. Qual especificação deve ser adotada?",
            "due_date": today - timedelta(days=5),
            "assignee_id": demo_id,
            "aguardando_aceite": False,
            "fechar": True,   # recebe resposta oficial E é aceito -> fechado
        },
    ]

    criados = []
    for item in plano:
        rfi = create_rfi(
            token,
            item["subject"],
            item["question"],
            item["due_date"],
            item["assignee_id"],
            rfi_manager_id=demo_id,
        )
        rfi_id = rfi["id"]
        print(f"Criado RFI #{rfi.get('number', '?')} (id={rfi_id}): {item['subject']}")

        if item["aguardando_aceite"] or item["fechar"]:
            reply_official(
                token, rfi_id,
                "Utilizar a especificação conforme detalhamento anexo enviado por e-mail."
            )
            print(f"  -> resposta oficial registrada em {rfi_id}")

        if item["fechar"]:
            accept_rfi(token, rfi_id)
            print(f"  -> RFI {rfi_id} aceito e fechado (time_resolved populado)")

        criados.append({
            "id": rfi_id,
            "subject": item["subject"],
            "due_date": item["due_date"].isoformat(),
            "status": "closed" if item["fechar"] else "open",
            "situacao_esperada": (
                "fechado" if item["fechar"]
                else "aguardando aceite" if item["aguardando_aceite"]
                else "pendente de resposta"
            ),
        })

    print("\nResumo dos RFIs criados:")
    for c in criados:
        print(f"  id={c['id']:>7}  due_date={c['due_date']}  status={c['status']:<6}  {c['situacao_esperada']:<20}  {c['subject']}")


if __name__ == "__main__":
    main()
