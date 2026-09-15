import os
import requests
import mercadopago
from dotenv import load_dotenv

load_dotenv()

RENDER_WEBHOOK_URL = "https://trivium-erp.onrender.com/webhook/mercadopago"
PAYMENT_ID = "1328178818"

# 1. Consulta os detalhes da transação real gerada
token = os.getenv("MERCADOPAGO_ACCESS_TOKEN")
sdk = mercadopago.SDK(token)

print(f"🔍 Consultando transação {PAYMENT_ID} no Mercado Pago...")
info = sdk.payment().get(PAYMENT_ID).get("response", {})

ext_ref = info.get("external_reference", "")
valor = info.get("transaction_amount", 0.0)
status = info.get("status", "pending")

print(f"📌 Status na API: {status}")
print(f"📌 Referência: {ext_ref}")
print(f"📌 Valor: R$ {valor}")

# 2. Dispara a notificação de webhook para o Render
payload = {
    "type": "payment",
    "data": {
        "id": PAYMENT_ID
    }
}

print(f"\n📡 Disparando webhook para: {RENDER_WEBHOOK_URL}...")
resp = requests.post(RENDER_WEBHOOK_URL, json=payload, timeout=15)

print(f"✅ Resposta do Render: HTTP {resp.status_code} - {resp.text}")