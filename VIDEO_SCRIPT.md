# Roteiro — Procore RFI Monitor (2 min)

Objetivo: mostrar que você entende o domínio (construção) e não só a API.
O gancho é o achado técnico, não o código.

## 0:00–0:20 — O problema (fala + tela no README)

"Todo monitor de RFI que alguém constrói de primeira faz a mesma coisa:
lê o campo `ball_in_court` do Procore e manda notificação pra essa pessoa.
Isso parece óbvio. Está errado."

Mostrar a tabela de 3 estados do README na tela.

## 0:20–0:50 — O achado (tela: docs/api-notes.md ou README, seção "ball_in_court")

"Quando alguém responde oficialmente um RFI na API do Procore,
`ball_in_court` continua apontando pra quem respondeu — não muda pra quem
precisa aceitar. Testei isso ao vivo no sandbox: respondi um RFI, o campo
não se moveu. Só o `accepted: true` fecha, e só o `rfi_manager` pode fazer
isso."

Mostrar rapidamente `sandbox/recriar_rfis.py` — "criei um cenário de teste
programático com 6 RFIs pra provar isso, não fiquei só lendo a doc."

## 0:50–1:20 — A solução (tela: split monitor.py / terminal com pytest)

"O monitor certo não tem 2 estados, tem 3." Mostrar a tabela de novo,
rápido.

Rodar ao vivo (ou mostrar gravado):
```
python -m pytest tests/ -v
```
24 testes verdes. "Testado contra dados reais do sandbox, não só casos
inventados."

## 1:20–1:50 — Rodando de verdade (tela: n8n)

Mostrar o workflow "Procore — RFI Monitor" executando (Test workflow),
os 3 estados sendo classificados, e a mensagem chegando no Telegram
agrupada por responsável.

"Mesma lógica, rodando de produção a cada 2h, notificando as pessoas
certas — não quem já fez a parte dele."

## 1:50–2:00 — Fechamento (fala direto pra câmera)

"Sou engenheiro civil, 15 anos em obra pública. Não aprendi Procore lendo
a documentação — aprendi rodando contra o sandbox e vendo onde ela mente.
É esse tipo de coisa que eu resolvo."

---

## Checklist antes de gravar

- [ ] Rodar `sandbox/recriar_rfis.py` pra ter dados frescos no sandbox
- [ ] Confirmar workflow n8n ativo e testável ao vivo
- [ ] Terminal com fonte grande, tema claro (grava melhor em vídeo)
- [ ] Cortar qualquer token/URL de company privada da tela antes de gravar
