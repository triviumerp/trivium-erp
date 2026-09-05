import os
import json
import re
import urllib.request
import urllib.error
from datetime import date
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

def _limpar_documento(doc):
    if not doc:
        return ""
    return re.sub(r'\D', '', str(doc))

def _fazer_requisicao(endpoint, metodo="GET", payload=None):
    chave = _get_api_key()
    if not chave:
        print("[ASAAS] Chave ASAAS_API_KEY não configurada no ambiente.")
        return {"errors": [{"description": "Chave de API do Asaas não configurada no .env ou Render."}]}

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
        try:
            return json.loads(erro_detalhe)
        except Exception:
            return {"errors": [{"description": f"Erro de comunicação Asaas (HTTP {e.code})"}]}
    except Exception as e:
        print(f"[ERRO ASAAS]: {e}")
        return {"errors": [{"description": str(e)}]}

def criar_ou_obter_cliente_asaas(empresa):
    if empresa.asaas_customer_id:
        return empresa.asaas_customer_id

    doc_limpo = _limpar_documento(empresa.cnpj)
    payload = {
        "name": empresa.razao_social or empresa.nome_fantasia or "Cliente Trivium",
        "cpfCnpj": doc_limpo,
        "email": empresa.email or "financeiro@triviumerp.com.br",
        "phone": _limpar_documento(empresa.telefone),
        "mobilePhone": _limpar_documento(empresa.telefone),
        "externalReference": f"empresa_{empresa.id}"
    }

    resposta = _fazer_requisicao("customers", metodo="POST", payload=payload)
    if resposta and "id" in resposta:
        empresa.asaas_customer_id = resposta["id"]
        return resposta["id"]
    
    print(f"[ASAAS] Falha ao criar cliente: {resposta}")
    return None

def gerar_link_pagamento_plano(empresa, nome_plano, valor_mensal):
    customer_id = criar_ou_obter_cliente_asaas(empresa)

    payload = {
        "name": f"Assinatura Trivium ERP - {nome_plano}",
        "description": f"Mensalidade SaaS Trivium ERP para {empresa.razao_social}",
        "value": float(valor_mensal),
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

def obter_pix_qrcode_cobranca(payment_id):
    """Obtém QR Code e Copia e Cola para pagamento Pix no Asaas."""
    resposta = _fazer_requisicao(f"payments/{payment_id}/pixQrCode", metodo="GET")
    if resposta and isinstance(resposta, dict):
        return {
            "encodedImage": resposta.get("encodedImage") or "",
            "payload": resposta.get("payload") or "",
            "expirationDate": resposta.get("expirationDate") or ""
        }
    return None

def criar_assinatura_transparente(empresa, nome_plano, valor, forma_pagamento, cartao_dados=None, remote_ip=None):
    doc_limpo = _limpar_documento(empresa.cnpj)
    if len(doc_limpo) not in (11, 14):
        return {"sucesso": False, "mensagem": "Cadastre um CPF ou CNPJ válido na aba 'Dados Cadastrais' antes de prosseguir."}

    customer_id = criar_ou_obter_cliente_asaas(empresa)
    if not customer_id:
        return {"sucesso": False, "mensagem": "Não foi possível registrar o cliente no Asaas. Verifique se o CPF/CNPJ e telefone estão válidos."}

    # SE FOR PIX: Emissão direta com tipo PIX nativo
    if forma_pagamento == 'PIX':
        payload_pix = {
            "customer": customer_id,
            "billingType": "PIX",
            "value": float(valor),
            "dueDate": date.today().strftime('%Y-%m-%d'),
            "description": f"Assinatura Trivium ERP - Plano {nome_plano}"
        }
        resp_pix = _fazer_requisicao("payments", metodo="POST", payload=payload_pix)
        
        if resp_pix and "id" in resp_pix:
            empresa.plano = nome_plano
            empresa.valor_mensalidade = float(valor)
            empresa.forma_pagamento_asaas = "PIX"
            
            dados_qr = obter_pix_qrcode_cobranca(resp_pix["id"])
            return {
                "sucesso": True, 
                "subscription": resp_pix, 
                "pix": dados_qr,
                "invoiceUrl": resp_pix.get("invoiceUrl")
            }
        
        erros = resp_pix.get('errors', [{}]) if isinstance(resp_pix, dict) else [{}]
        return {"sucesso": False, "mensagem": erros[0].get('description', 'Erro ao gerar cobrança Pix no Asaas.')}

    # SE FOR CARTÃO: Cria a assinatura recorrente
    payload = {
        "customer": customer_id,
        "billingType": "CREDIT_CARD",
        "value": float(valor),
        "nextDueDate": date.today().strftime('%Y-%m-%d'),
        "cycle": "MONTHLY",
        "description": f"Assinatura Trivium ERP - Plano {nome_plano}"
    }

    if cartao_dados:
        payload["creditCard"] = {
            "holderName": cartao_dados.get('holder_name'),
            "number": _limpar_documento(cartao_dados.get('number')),
            "expiryMonth": str(cartao_dados.get('expiry_month')).zfill(2),
            "expiryYear": str(cartao_dados.get('expiry_year')),
            "ccv": str(cartao_dados.get('ccv'))
        }
        payload["creditCardHolderInfo"] = {
            "name": cartao_dados.get('holder_name'),
            "email": empresa.email or "financeiro@triviumerp.com.br",
            "cpfCnpj": doc_limpo,
            "postalCode": _limpar_documento(empresa.cep) or "08674000",
            "addressNumber": "S/N",
            "phone": _limpar_documento(empresa.telefone) or "11999999999"
        }
        if remote_ip:
            payload["remoteIp"] = remote_ip

    resposta = _fazer_requisicao("subscriptions", metodo="POST", payload=payload)
    
    if resposta and "id" in resposta:
        empresa.asaas_subscription_id = resposta.get("id")
        empresa.plano = nome_plano
        empresa.valor_mensalidade = float(valor)
        empresa.forma_pagamento_asaas = "CREDIT_CARD"
        return {"sucesso": True, "subscription": resposta}

    erros = resposta.get('errors', [{}]) if isinstance(resposta, dict) else [{}]
    return {"sucesso": False, "mensagem": erros[0].get('description', 'Erro ao processar cartão junto ao Asaas.')}

    # SE FOR CARTÃO: Cria a assinatura recorrente
    payload = {
        "customer": customer_id,
        "billingType": "CREDIT_CARD",
        "value": float(valor),
        "nextDueDate": date.today().strftime('%Y-%m-%d'),
        "cycle": "MONTHLY",
        "description": f"Assinatura Trivium ERP - Plano {nome_plano}"
    }

    if cartao_dados:
        payload["creditCard"] = {
            "holderName": cartao_dados.get('holder_name'),
            "number": _limpar_documento(cartao_dados.get('number')),
            "expiryMonth": str(cartao_dados.get('expiry_month')).zfill(2),
            "expiryYear": str(cartao_dados.get('expiry_year')),
            "ccv": str(cartao_dados.get('ccv'))
        }
        payload["creditCardHolderInfo"] = {
            "name": cartao_dados.get('holder_name'),
            "email": empresa.email or "financeiro@triviumerp.com.br",
            "cpfCnpj": doc_limpo,
            "postalCode": _limpar_documento(empresa.cep) or "08674000",
            "addressNumber": "S/N",
            "phone": _limpar_documento(empresa.telefone) or "11999999999"
        }
        if remote_ip:
            payload["remoteIp"] = remote_ip

    resposta = _fazer_requisicao("subscriptions", metodo="POST", payload=payload)
    
    if resposta and "id" in resposta:
        empresa.asaas_subscription_id = resposta.get("id")
        empresa.plano = nome_plano
        empresa.valor_mensalidade = float(valor)
        empresa.forma_pagamento_asaas = "CREDIT_CARD"
        return {"sucesso": True, "subscription": resposta}

    erros = resposta.get('errors', [{}]) if isinstance(resposta, dict) else [{}]
    return {"sucesso": False, "mensagem": erros[0].get('description', 'Erro ao processar cartão junto ao Asaas.')}
    # SE FOR CARTÃO: Cria a assinatura recorrente
    payload = {
        "customer": customer_id,
        "billingType": "CREDIT_CARD",
        "value": float(valor),
        "nextDueDate": date.today().strftime('%Y-%m-%d'),
        "cycle": "MONTHLY",
        "description": f"Assinatura Trivium ERP - Plano {nome_plano}"
    }

    if cartao_dados:
        payload["creditCard"] = {
            "holderName": cartao_dados.get('holder_name'),
            "number": _limpar_documento(cartao_dados.get('number')),
            "expiryMonth": str(cartao_dados.get('expiry_month')).zfill(2),
            "expiryYear": str(cartao_dados.get('expiry_year')),
            "ccv": str(cartao_dados.get('ccv'))
        }
        payload["creditCardHolderInfo"] = {
            "name": cartao_dados.get('holder_name'),
            "email": empresa.email or "financeiro@triviumerp.com.br",
            "cpfCnpj": doc_limpo,
            "postalCode": _limpar_documento(empresa.cep) or "08674000",
            "addressNumber": "S/N",
            "phone": _limpar_documento(empresa.telefone) or "11999999999"
        }
        if remote_ip:
            payload["remoteIp"] = remote_ip

    resposta = _fazer_requisicao("subscriptions", metodo="POST", payload=payload)
    
    if resposta and "id" in resposta:
        empresa.asaas_subscription_id = resposta.get("id")
        empresa.plano = nome_plano
        empresa.valor_mensalidade = float(valor)
        empresa.forma_pagamento_asaas = "CREDIT_CARD"
        return {"sucesso": True, "subscription": resposta}

    erros = resposta.get('errors', [{}]) if isinstance(resposta, dict) else [{}]
    return {"sucesso": False, "mensagem": erros[0].get('description', 'Erro ao processar cartão junto ao Asaas.')}