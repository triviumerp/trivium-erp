import os
import json
import urllib.request
import urllib.error

RESEND_API_KEY = os.getenv('RESEND_API_KEY', '')
# Enquanto você não tiver domínio próprio configurado no Resend, use o remetente oficial de teste:
DEFAULT_FROM = "Trivium ERP <onboarding@resend.dev>"

def _enviar_email(destinatario, assunto, html_conteudo):
    """Envia e-mail via API HTTPS do Resend (funciona 100% no plano gratuito do Render)."""
    if not RESEND_API_KEY:
        print("[EMAIL IGNORADO] RESEND_API_KEY não configurada no Environment.")
        return False

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "TriviumERP/1.0"
    }

    payload = {
        "from": DEFAULT_FROM,
        "to": [destinatario],
        "subject": assunto,
        "html": html_conteudo
    }

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status in (200, 201):
                print(f"[EMAIL ENVIADO] Sucesso para: {destinatario}")
                return True
        return False
    except urllib.error.HTTPError as e:
        erro_body = e.read().decode('utf-8')
        print(f"[ERRO RESEND HTTP {e.code}]: {erro_body}")
        return False
    except Exception as e:
        print(f"[ERRO RESEND]: {e}")
        return False

def enviar_email_ativacao(destinatario, nome, link_ativacao):
    """Dispara o e-mail de confirmação de cadastro e ativação de conta."""
    assunto = "Confirmação de Cadastro - Trivium ERP"
    html_content = f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8fafc; margin: 0; padding: 30px;">
        <div style="max-width: 540px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 32px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
            <div style="text-align: center; margin-bottom: 24px;">
                <h2 style="color: #1e3a8a; margin: 0; font-size: 26px;">Trivium <span style="color: #2563eb;">ERP</span></h2>
                <p style="color: #64748b; font-size: 13px; margin-top: 4px;">Plataforma de Gestão Inteligente</p>
            </div>
            
            <p style="font-size: 15px; color: #1e293b;">Olá, <b>{nome}</b>!</p>
            <p style="font-size: 14px; color: #475569; line-height: 1.6;">
                Obrigado por se cadastrar no <b>Trivium ERP</b>. Para liberar seu acesso e ativar sua conta com segurança, confirme seu endereço de e-mail clicando no botão abaixo:
            </p>
            
            <div style="text-align: center; margin: 32px 0;">
                <a href="{link_ativacao}" style="background-color: #2563eb; color: #ffffff; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: bold; font-size: 14px; display: inline-block;">
                    Ativar Minha Conta
                </a>
            </div>

            <p style="font-size: 12px; color: #e11d48; text-align: center; background: #ffe4e6; padding: 10px; border-radius: 6px;">
                ⚠️ <b>Importante:</b> Caso não encontre este e-mail na Caixa de Entrada, verifique sua pasta de <b>Spam</b> ou <b>Lixo Eletrônico</b> e marque-o como "Não é spam".
            </p>
            
            <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 24px 0;">
            <p style="font-size: 12px; color: #94a3b8; text-align: center; margin: 0;">
                Este link expira em 24 horas.
            </p>
        </div>
    </body>
    </html>
    """
    return _enviar_email(destinatario, assunto, html_content)

def enviar_email_recuperacao_senha(destinatario, nome, link_recuperacao):
    """Dispara o e-mail de redefinição de senha com botão de ação."""
    assunto = "Redefinição de Senha - Trivium ERP"
    html_content = f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8fafc; margin: 0; padding: 30px;">
        <div style="max-width: 540px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 32px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
            <div style="text-align: center; margin-bottom: 24px;">
                <h2 style="color: #1e3a8a; margin: 0; font-size: 26px;">Trivium <span style="color: #2563eb;">ERP</span></h2>
                <p style="color: #64748b; font-size: 13px; margin-top: 4px;">Recuperação de Acesso</p>
            </div>
            
            <p style="font-size: 15px; color: #1e293b;">Olá, <b>{nome}</b>!</p>
            <p style="font-size: 14px; color: #475569; line-height: 1.6;">
                Recebemos uma solicitação para redefinir a senha da sua conta no <b>Trivium ERP</b>. Clique no botão abaixo para cadastrar uma nova senha:
            </p>
            
            <div style="text-align: center; margin: 32px 0;">
                <a href="{link_recuperacao}" style="background-color: #0f172a; color: #ffffff; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: bold; font-size: 14px; display: inline-block;">
                    Redefinir Minha Senha
                </a>
            </div>

            <p style="font-size: 12px; color: #e11d48; text-align: center; background: #ffe4e6; padding: 10px; border-radius: 6px;">
                ⚠️ <b>Atenção:</b> Caso não encontre nossos e-mails futuros, verifique sua pasta de <b>Spam</b> ou <b>Lixo Eletrônico</b> e adicione nosso contato.
            </p>
            
            <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 24px 0;">
            <p style="font-size: 12px; color: #94a3b8; text-align: center; margin: 0;">
                Este link é válido por 30 minutos. Se não solicitou a alteração, desconsidere esta mensagem.
            </p>
        </div>
    </body>
    </html>
    """
    return _enviar_email(destinatario, assunto, html_content)
