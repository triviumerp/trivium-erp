import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
SMTP_USER = os.getenv('SMTP_USER', 'suporte.triviumerp@gmail.com')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', 'oqowvladpuxqpeex')

def enviar_email_ativacao(destinatario, nome, link_ativacao):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = 'Ativação da sua conta - Trivium ERP'
    msg['From'] = f"Trivium ERP <{SMTP_USER}>"
    msg['To'] = destinatario

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
    msg.attach(MIMEText(html_content, 'html'))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, destinatario, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"[ERRO GMAIL SMTP] Falha no disparo de ativação: {e}")
        return False

def enviar_email_recuperacao_senha(destinatario, nome, link_recuperacao):
    """Dispara o e-mail de redefinição de senha com botão de ação."""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = 'Redefinição de Senha - Trivium ERP'
    msg['From'] = f"Trivium ERP <{SMTP_USER}>"
    msg['To'] = destinatario

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
    msg.attach(MIMEText(html_content, 'html'))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, destinatario, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"[ERRO GMAIL SMTP] Falha no disparo de recuperação: {e}")
        return False