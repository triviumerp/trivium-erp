import os
import mercadopago
from dotenv import load_dotenv

load_dotenv()

sdk = mercadopago.SDK(os.getenv("MERCADOPAGO_ACCESS_TOKEN"))
resposta = sdk.payment_methods().list_all()

if resposta.get("status") == 200:
    print("✅ SUCESSO: Conexão com o Mercado Pago (Sandbox) funcionando perfeitamente!")
else:
    print("❌ ERRO:", resposta)