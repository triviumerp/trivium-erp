import os
import mercadopago
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("MERCADOPAGO_ACCESS_TOKEN")
if not token:
    print("❌ Erro: MERCADOPAGO_ACCESS_TOKEN não encontrado no .env")
    exit()

sdk = mercadopago.SDK(token)

# 1. Solicita o ID da transação gerada
payment_id_input = input("Cole o ID do Pagamento (payment_id) gerado: ").strip()

if not payment_id_input.isdigit():
    print("❌ Erro: O ID deve conter apenas números.")
    exit()

payment_id = int(payment_id_input)

print(f"\n🔄 Solicitando ao Mercado Pago a aprovação do ID {payment_id}...")

# 2. Atualiza o status no Sandbox para 'approved'
resposta = sdk.payment().update(payment_id, {"status": "approved"})

if resposta.get("status") in [200, 201]:
    dados = resposta.get("response", {})
    status_atual = dados.get("status")
    ext_ref = dados.get("external_reference")
    print(f"✅ SUCESSO: Pagamento {payment_id} atualizado para '{status_atual}'!")
    print(f"📌 Referência da Empresa: {ext_ref}")
    print("\n⏳ O Mercado Pago acaba de disparar o Webhook para o Render.")
    print("👉 Verifique os logs no painel do Render ou recarregue o site para ver a empresa ativa!")
else:
    print("❌ Falha ao atualizar pagamento:", resposta)