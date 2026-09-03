from dotenv import load_dotenv
load_dotenv()

from services.asaas_service import _fazer_requisicao, _get_api_key, _get_base_url

print("=" * 60)
print("TESTE DE CONEXÃO COM A API DO ASAAS (PRODUÇÃO)")
print("=" * 60)

url_base = _get_base_url()
chave = _get_api_key()

print(f"URL Base: {url_base}")
if chave:
    print(f"Chave detectada: {chave[:15]}... (ocultada por segurança)")
else:
    print("❌ Nenhuma chave detectada no .env!")
print("-" * 60)

resposta = _fazer_requisicao("customers?limit=1", metodo="GET")

if resposta is not None and "data" in resposta:
    print("✅ SUCESSO! Conexão autenticada perfeitamente com a API do Asaas.")
    print(f"Total de clientes cadastrados no Asaas: {resposta.get('totalCount', 0)}")
else:
    print("❌ FALHA NA CONEXÃO! Verifique as mensagens de erro acima.")
print("=" * 60)