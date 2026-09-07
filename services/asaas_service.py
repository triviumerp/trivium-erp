import os
import json
import urllib.request
import urllib.error
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# CONFIGURAÇÃO CENTRALIZADA DOS PLANOS DO ERP
# ==========================================
PLANOS_CONFIG = {
    'MENSAL': {
        'nome': 'Plano Flex Mensal',
        'valor_total': 39.90,
        'valor_exibicao': 39.90,
        'parcelas': 1,
        'tipo': 'RECORRENTE',  # Usa /v3/subscriptions (ciclo mensal)
        'dias_validade': 30
    },
    'SEMESTRAL': {
        'nome': 'Plano Pro Semestral',
        'valor_total': 209.40,
        'valor_exibicao': 34.90,
        'parcelas': 6,
        'tipo': 'PARCELADO',   # Usa /v3/payments com 6 parcelas
        'dias_validade': 180
    },
    'ANUAL': {
        'nome': 'Plano Anual Founder',
        'valor_total': 358.80,
        'valor_exibicao': 29.90,
        'parcelas': 12,
        'tipo': 'PARCELADO',   # Usa /v3/payments com 12 parcelas
        'dias_validade': 365
    }
}

def _get_api_key():
    return os.getenv('ASAAS_API_KEY', '').strip()

def _get_base_url():
    return os.getenv('ASAAS_BASE_URL', 'https://sandbox.asaas.com/api/v3').strip().rstrip('/')

def _headers():
    return {
        "access_token": _get_api_key(),
        "Content-Type": "application/json",
        "User-Agent": "TriviumERP/1.0"
    }

def _limpar_documento(doc):
    if not doc:
        return ""
    return "".join([c for c in str(doc) if c.isdigit()])

def _fazer_requisicao(endpoint, metodo="GET", payload=None):
    chave = _get_api_key()
    if not chave:
        print("[ASAAS] Chave ASAAS_API_KEY não configurada no .env.")
        return {"errors": [{"description": "Chave de API do Asaas não configurada no .env."}]}

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
    """Cria ou atualiza o cadastro do cliente (PF ou PJ) no Asaas de forma sincronizada."""
    doc_limpo = _limpar_documento(empresa.cnpj)
    tel_limpo = _limpar_documento(empresa.telefone)
    cep_limpo = _limpar_documento(empresa.cep)

    # Garante telefone com DDD válido
    if not tel_limpo or len(tel_limpo) < 10:
        tel_limpo = "11999999999"

    # Garante CEP válido com 8 dígitos
    if not cep_limpo or len(cep_limpo) != 8:
        cep_limpo = "08696040"

    payload = {
        "name": empresa.razao_social or empresa.nome_fantasia or "Cliente Trivium",
        "cpfCnpj": doc_limpo,
        "email": empresa.email or "contato@triviumerp.com.br",
        "phone": tel_limpo,
        "mobilePhone": tel_limpo,
        "postalCode": cep_limpo,
        "address": empresa.logradouro or "",
        "addressNumber": str(empresa.numero or "S/N"),
        "complement": str(empresa.complemento or ""),
        "province": empresa.bairro or "",
        "externalReference": f"empresa_{empresa.id}"
    }

    print(f"\n[DEBUG ASAAS] Tentando registrar/atualizar cliente. Payload: {payload}\n")

    # 1. Se já possui ID no Asaas, tenta atualizar
    if empresa.asaas_customer_id:
        resp_update = _fazer_requisicao(f"customers/{empresa.asaas_customer_id}", metodo="POST", payload=payload)
        if resp_update and "id" in resp_update:
            return empresa.asaas_customer_id
        empresa.asaas_customer_id = None

    # 2. Se já existe cadastrado pelo CPF/CNPJ, recupera o ID
    if doc_limpo:
        busca = _fazer_requisicao(f"customers?cpfCnpj={doc_limpo}", metodo="GET")
        if busca and busca.get('data') and len(busca['data']) > 0:
            cust_id = busca['data'][0]['id']
            _fazer_requisicao(f"customers/{cust_id}", metodo="POST", payload=payload)
            empresa.asaas_customer_id = cust_id
            return cust_id

    # 3. Cria novo cadastro
    resposta = _fazer_requisicao("customers", metodo="POST", payload=payload)
    if resposta and "id" in resposta:
        empresa.asaas_customer_id = resposta["id"]
        return resposta["id"]

    print(f"\n[ERRO DETALHADO ASAAS CUSTOMER]: {resposta}\n")
    return None

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

def criar_assinatura_transparente(empresa, nome_plano, valor, forma_pagamento, cartao_dados=None, remote_ip=None, parcelas=1):
    doc_limpo = _limpar_documento(empresa.cnpj)
    
    if not doc_limpo or len(doc_limpo) not in (11, 14):
        return {
            "sucesso": False, 
            "mensagem": f"O documento informado ({empresa.cnpj or 'Vazio'}) não possui 11 (CPF) ou 14 (CNPJ) dígitos. Revise na aba 'Dados Cadastrais'."
        }

    customer_id = criar_ou_obter_cliente_asaas(empresa)
    if not customer_id:
        return {
            "sucesso": False, 
            "mensagem": "O Asaas recusou os dados cadastrais. Verifique no terminal do servidor o motivo retornado pela API."
        }

    chave_plano = str(nome_plano).upper().replace("PLANO ", "").strip()
    if 'ANUAL' in chave_plano:
        cfg = PLANOS_CONFIG['ANUAL']
    elif 'SEMESTRAL' in chave_plano:
        cfg = PLANOS_CONFIG['SEMESTRAL']
    else:
        cfg = PLANOS_CONFIG['MENSAL']

    # 1. PIX / BOLETO
    if forma_pagamento in ['PIX', 'BOLETO']:
        payload_cobranca = {
            "customer": customer_id,
            "billingType": forma_pagamento,
            "value": float(cfg['valor_total']),
            "dueDate": (date.today() + timedelta(days=3)).strftime('%Y-%m-%d'),
            "description": f"Assinatura Trivium ERP - {cfg['nome']} ({forma_pagamento})",
            "externalReference": f"emp_{empresa.id}_{cfg['nome']}"
        }
        
        resp_cobranca = _fazer_requisicao("payments", metodo="POST", payload=payload_cobranca)
        
        if resp_cobranca and "id" in resp_cobranca:
            empresa.plano = cfg['nome']
            empresa.valor_mensalidade = cfg['valor_exibicao']
            empresa.forma_pagamento_asaas = forma_pagamento
            
            dados_qr = None
            if forma_pagamento == 'PIX':
                dados_qr = obter_pix_qrcode_cobranca(resp_cobranca["id"])
            
            return {
                "sucesso": True, 
                "dados": resp_cobranca, 
                "pix": dados_qr,
                "bankSlipUrl": resp_cobranca.get("bankSlipUrl"),
                "invoiceUrl": resp_cobranca.get("invoiceUrl") or resp_cobranca.get("bankSlipUrl"),
                "plano_info": cfg
            }
        
        erros = resp_cobranca.get('errors', [{}]) if isinstance(resp_cobranca, dict) else [{}]
        return {"sucesso": False, "mensagem": erros[0].get('description', f'Erro ao emitir {forma_pagamento} no Asaas.')}

    # 2. CARTÃO DE CRÉDITO
    holder_info = {
        "name": cartao_dados.get('holder_name') if cartao_dados else (empresa.razao_social or "Cliente Trivium"),
        "email": empresa.email or "financeiro@triviumerp.com.br",
        "cpfCnpj": doc_limpo,
        "postalCode": _limpar_documento(empresa.cep) or "08696040",
        "addressNumber": str(empresa.numero or "S/N"),
        "phone": _limpar_documento(empresa.telefone) or "11999999999"
    }

    card_info = {
        "holderName": cartao_dados.get('holder_name'),
        "number": _limpar_documento(cartao_dados.get('number')),
        "expiryMonth": str(cartao_dados.get('expiry_month')).zfill(2),
        "expiryYear": str(cartao_dados.get('expiry_year')),
        "ccv": str(cartao_dados.get('ccv'))
    } if cartao_dados else {}

    if cfg['tipo'] == 'RECORRENTE':
        payload = {
            "customer": customer_id,
            "billingType": "CREDIT_CARD",
            "value": float(cfg['valor_total']),
            "nextDueDate": date.today().strftime('%Y-%m-%d'),
            "cycle": "MONTHLY",
            "description": f"Assinatura Trivium ERP - {cfg['nome']}",
            "creditCard": card_info,
            "creditCardHolderInfo": holder_info
        }
        if remote_ip:
            payload["remoteIp"] = remote_ip
        resposta = _fazer_requisicao("subscriptions", metodo="POST", payload=payload)
    else:
        payload = {
            "customer": customer_id,
            "billingType": "CREDIT_CARD",
            "totalValue": float(cfg['valor_total']),
            "installmentCount": int(cfg['parcelas']),
            "dueDate": date.today().strftime('%Y-%m-%d'),
            "description": f"Assinatura Trivium ERP - {cfg['nome']} ({cfg['parcelas']}x)",
            "creditCard": card_info,
            "creditCardHolderInfo": holder_info
        }
        if remote_ip:
            payload["remoteIp"] = remote_ip
        resposta = _fazer_requisicao("payments", metodo="POST", payload=payload)

    if resposta and "id" in resposta:
        empresa.plano = cfg['nome']
        empresa.valor_mensalidade = cfg['valor_exibicao']
        empresa.forma_pagamento_asaas = "CREDIT_CARD"
        if cfg['tipo'] == 'RECORRENTE':
            empresa.asaas_subscription_id = resposta.get("id")
        return {"sucesso": True, "dados": resposta, "plano_info": cfg}

    erros = resposta.get('errors', [{}]) if isinstance(resposta, dict) else [{}]
    return {"sucesso": False, "mensagem": erros[0].get('description', 'Erro ao processar cartão junto ao Asaas.')}

def gerar_link_pagamento_plano(empresa, nome_plano, valor_mensal):
    """Gera link direto de pagamento caso necessário"""
    customer_id = criar_ou_obter_cliente_asaas(empresa)
    if not customer_id:
        return None

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