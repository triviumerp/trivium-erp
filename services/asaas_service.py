import os
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()

def _get_api_key():
    return os.getenv('ASAAS_API_KEY', '').strip()

def _get_base_url():
    return os.getenv('ASAAS_BASE_URL', 'https://api.asaas.com/v3').strip().rstrip('/')

def _headers():
    return {
        "access_token": _get_api_key(),
        "Content-Type": "application/json",
        "User-Agent": "TriviumERP/1.0"
    }

def _fazer_requisicao(endpoint, metodo="GET", payload=None):
    chave = _get_api_key()
    if not chave:
        print("[ASAAS] Chave ASAAS_API_KEY não configurada no ambiente.")
        return None

    url = f"{_get_base_url()}/{endpoint.lstrip('/')}"
    headers = _headers()
    data = json.dumps(payload).encode('utf-8') if payload else None

    req = urllib.request.Request(url, data=data, headers=headers, method=metodo)

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status in (200, 201):
                return json.loads(response.read().decode('utf-8'))
        return None
    except urllib.error.HTTPError as e:
        erro_detalhe = e.read().decode('utf-8')
        print(f"[ERRO ASAAS HTTP {e.code}]: {erro_detalhe}")
        return None
    except Exception as e:
        print(f"[ERRO ASAAS]: {e}")
        return None

def criar_ou_obter_cliente_asaas(empresa):
    if empresa.asaas_customer_id:
        return empresa.asaas_customer_id

    payload = {
        "name": empresa.razao_social or empresa.nome_fantasia,
        "cpfCnpj": empresa.cnpj,
        "email": empresa.email,
        "phone": empresa.telefone,
        "mobilePhone": empresa.telefone,
        "externalReference": f"empresa_{empresa.id}"
    }

    resposta = _fazer_requisicao("customers", metodo="POST", payload=payload)
    if resposta and "id" in resposta:
        return resposta["id"]
    return None

def gerar_link_pagamento_plano(empresa, nome_plano, valor_mensal):
    customer_id = criar_ou_obter_cliente_asaas(empresa)

    payload = {
        "name": f"Assinatura Trivium ERP - {nome_plano}",
        "description": f"Mensalidade SaaS Trivium ERP para {empresa.razao_social}",
        "value": valor_mensal,
        "billingType": "UNDEFINED",
        "chargeType": "RECURRENT",
        "cycle": "MONTHLY",
        "dueDateLimitDays": 3,
        "customer": customer_id
    }

    resposta = _fazer_requisicao("paymentLinks", metodo="POST", payload=payload)
    if resposta and "url" in resposta:
        return resposta.get("url")
    return None

def consultar_cobranca(cobranca_id):
    return _fazer_requisicao(f"payments/{cobranca_id}", metodo="GET")