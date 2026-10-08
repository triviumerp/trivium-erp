import os
import re
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, make_response
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from services.auth_token import gerar_token_recuperacao, validar_token_recuperacao
from services.email_service import enviar_email_recuperacao_senha

from extensions import db, limiter
from models import Empresa, Usuario, CupomDesconto

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# -----------------------------------------------------------------------------
# FUNÇÕES DE VALIDAÇÃO
# -----------------------------------------------------------------------------
def is_cpf_valido(cpf):
    if not cpf:
        return True
    cpf_limpo = re.sub(r'\D', '', cpf)
    if len(cpf_limpo) != 11 or cpf_limpo == cpf_limpo[0] * 11:
        return False
    soma = sum(int(cpf_limpo[i]) * (10 - i) for i in range(9))
    resto = 11 - (soma % 11)
    digito1 = 0 if resto in [10, 11] else resto
    if digito1 != int(cpf_limpo[9]):
        return False
    soma = sum(int(cpf_limpo[i]) * (11 - i) for i in range(10))
    resto = 11 - (soma % 11)
    digito2 = 0 if resto in [10, 11] else resto
    return digito2 == int(cpf_limpo[10])

def validar_senha_forte(senha):
    if not senha or len(senha) < 8:
        return False, "A senha deve conter no mínimo 8 caracteres."
    if not re.search(r"[A-Z]", senha):
        return False, "A senha deve conter pelo menos uma letra maiúscula."
    if not re.search(r"[a-z]", senha):
        return False, "A senha deve conter pelo menos uma letra minúscula."
    if not re.search(r"[0-9]", senha):
        return False, "A senha deve conter pelo menos um número."
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-\\\/\[\]~+=\`]", senha):
        return False, "A senha deve conter pelo menos um caractere especial (ex: @, #, $, !)."
    return True, ""

# -----------------------------------------------------------------------------
# ROTAS DE AUTENTICAÇÃO
# -----------------------------------------------------------------------------

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        if current_user.nivel_acesso == 'afiliado':
            return redirect(url_for('painel_afiliado'))
        elif current_user.nivel_acesso == 'master':
            return redirect(url_for('admin_master_dashboard'))
        return redirect(url_for('index'))

    if request.method == 'POST':
        identificador = request.form.get('email', '').strip()
        senha = request.form.get('senha', '')

        usuario = None
        if '@' in identificador:
            usuario = Usuario.query.filter_by(email=identificador.lower()).first()
        else:
            doc_limpo = re.sub(r'\D', '', identificador)
            if doc_limpo:
                empresa_alvo = Empresa.query.filter_by(cnpj=doc_limpo).first()
                if empresa_alvo:
                    usuario = Usuario.query.filter_by(empresa_id=empresa_alvo.id).first()

        if usuario and usuario.check_senha(senha):
            if not usuario.ativo:
                flash('Este usuário está inativo no sistema. Entre em contato com o suporte.', 'danger')
                return render_template('auth/login.html')

            session.permanent = True
            login_user(usuario, remember=True)
            flash(f'Bem-vindo de volta, {usuario.nome}!', 'success')
            
            proxima_pagina = request.args.get('next')
            if proxima_pagina:
                return redirect(proxima_pagina)

            if usuario.nivel_acesso == 'afiliado':
                return redirect(url_for('painel_afiliado'))
            elif usuario.nivel_acesso == 'master':
                return redirect(url_for('admin_master_dashboard'))
            
            return redirect(url_for('index'))
        else:
            flash('Credenciais incorretas. Verifique seu e-mail ou CPF/CNPJ e senha.', 'danger')

    return render_template('auth/login.html')

@auth_bp.route('/registro', methods=['GET', 'POST'])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    cupom_url = (request.args.get('ref') or '').strip().upper()
    afiliado_id_url = request.args.get('afiliado', type=int)

    if request.method == 'POST':
        nome_usuario = (request.form.get('nome_usuario') or '').strip()
        is_pessoa_fisica = request.form.get('is_pessoa_fisica') in ['1', 'true', 'on']
        razao_social = (request.form.get('razao_social') or '').strip()
        
        email = (request.form.get('email') or '').strip().lower()
        confirma_email = (request.form.get('confirma_email') or '').strip().lower()
        senha = request.form.get('senha', '')
        confirma_senha = request.form.get('confirma_senha', '')
        
        # Respostas da Triagem
        perfil_operacao = request.form.get('perfil_operacao', 'servicos_campo')
        equipe_porte = request.form.get('equipe_porte', '1')
        usar_financeiro = request.form.get('usar_financeiro') in ['1', 'true', 'on']
        
        cupom_indicacao = (request.form.get('cupom_indicacao') or cupom_url).strip().upper()

        # Validações com flag para abrir direto no Step 3
        if email != confirma_email:
            flash('O e-mail e a confirmação de e-mail não coincidem.', 'danger')
            return render_template('auth/registro.html', cupom_ref=cupom_indicacao, abrir_step3=True, perfil_operacao=perfil_operacao, equipe_porte=equipe_porte, usar_financeiro=usar_financeiro)

        senha_valida, msg_erro = validar_senha_forte(senha)
        if not senha_valida:
            flash(msg_erro, 'danger')
            return render_template('auth/registro.html', cupom_ref=cupom_indicacao, abrir_step3=True, perfil_operacao=perfil_operacao, equipe_porte=equipe_porte, usar_financeiro=usar_financeiro)

        if senha != confirma_senha:
            flash('A palavra-passe e a confirmação não coincidem.', 'danger')
            return render_template('auth/registro.html', cupom_ref=cupom_indicacao, abrir_step3=True, perfil_operacao=perfil_operacao, equipe_porte=equipe_porte, usar_financeiro=usar_financeiro)

        if Usuario.query.filter_by(email=email).first():
            flash('Este e-mail já está registado no sistema. Por favor, inicie sessão.', 'danger')
            return render_template('auth/registro.html', cupom_ref=cupom_indicacao, abrir_step3=True, email_duplicado=True, perfil_operacao=perfil_operacao, equipe_porte=equipe_porte, usar_financeiro=usar_financeiro)

        # Regra de Razão Social / Nome Fantasia para PF vs PJ
        if is_pessoa_fisica or not razao_social:
            nome_empresa_final = nome_usuario
            fantasia_final = "Profissional Autônomo"
        else:
            nome_empresa_final = razao_social
            fantasia_final = None

        # Definição dinâmica dos módulos com base na Triagem
        modulo_servicos = False
        modulo_atend = False
        modulo_est = False
        modulo_vendas = False
        modulo_tecnicos = False

        if perfil_operacao == 'saude':
            modulo_atend = True
        elif perfil_operacao == 'servicos_campo':
            modulo_servicos = True
            modulo_tecnicos = (equipe_porte != '1')
        elif perfil_operacao == 'distribuidora':
            modulo_est = True
            modulo_vendas = True
        elif perfil_operacao == 'estoque_interno':
            modulo_est = True
        elif perfil_operacao == 'documentos':
            pass

        limite_users = 2
        if equipe_porte == '2_5':
            limite_users = 5
        elif equipe_porte == 'mais_5':
            limite_users = 10

        try:
            cupom_obj = None
            if cupom_indicacao:
                cupom_obj = CupomDesconto.query.filter_by(codigo=cupom_indicacao).first()

            nova_empresa = Empresa(
                razao_social=nome_empresa_final,
                nome_fantasia=fantasia_final,
                email=email,
                plano=f"Trial ({perfil_operacao.capitalize()})",
                status_assinatura="trial",
                valor_mensalidade=0.0,
                data_vencimento=date.today() + relativedelta(days=14),
                cupom_utilizado=cupom_obj.codigo if cupom_obj and cupom_obj.is_valido else None,
                afiliado_id=cupom_obj.id if cupom_obj and cupom_obj.is_valido else None,
                limite_usuarios=limite_users,
                modulo_servicos_campo=modulo_servicos,
                modulo_atendimentos=modulo_atend,
                modulo_gestao_tecnicos=modulo_tecnicos,
                modulo_estoque=modulo_est,
                modulo_vendas_externas=modulo_vendas
            )
            nova_empresa.gerar_token_requisicao_se_necessario()
            db.session.add(nova_empresa)
            db.session.flush()

            novo_usuario = Usuario(
                empresa_id=nova_empresa.id,
                nome=nome_usuario,
                email=email,
                cargo="Profissional / Administrador",
                nivel_acesso="admin",
                ativo=True,
                perm_clientes=True,
                perm_propostas=True,
                perm_servicos=modulo_servicos or modulo_atend,
                perm_financeiro=usar_financeiro,
                perm_estoque=modulo_est,
                perm_expedicao=modulo_vendas,
                perm_configuracoes=True,
                aceitou_termos_beta=True,
                data_aceite_termos=datetime.utcnow()
            )
            novo_usuario.set_senha(senha)
            db.session.add(novo_usuario)

            if cupom_obj and cupom_obj.is_valido:
                cupom_obj.usos_atuais = (cupom_obj.usos_atuais or 0) + 1

            db.session.commit()

            session.permanent = True
            login_user(novo_usuario, remember=True)
            flash('Ambiente configurado com sucesso! Bem-vindo aos seus 14 dias de teste.', 'success')
            return redirect(url_for('index'))

        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao processar o registo: {str(e)}', 'danger')
            return render_template('auth/registro.html', cupom_ref=cupom_indicacao, abrir_step3=True)

    return render_template('auth/registro.html', cupom_ref=cupom_url, abrir_step3=False)


@auth_bp.route('/esqueci-senha', methods=['GET', 'POST'])
def esqueci_senha():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    email_enviado_mascarado = None
    disparo_solicitado = False

    if request.method == 'POST':
        identificador = request.form.get('email', '').strip().lower()
        usuario = None

        if '@' in identificador:
            usuario = Usuario.query.filter_by(email=identificador).first()
        else:
            doc_limpo = re.sub(r'\D', '', identificador)
            if doc_limpo:
                empresa_alvo = Empresa.query.filter_by(cnpj=doc_limpo).first()
                if empresa_alvo:
                    usuario = Usuario.query.filter_by(empresa_id=empresa_alvo.id).first()

        if usuario:
            token = gerar_token_recuperacao(usuario.email)
            link_reset = url_for('auth.redefinir_senha', token=token, _external=True)
            enviar_email_recuperacao_senha(usuario.email, usuario.nome, link_reset)

            # Mascara o e-mail: sergio@gmail.com -> s***o@g***.com
            partes = usuario.email.split('@')
            user_parte = partes[0]
            dom_parte = partes[1] if len(partes) > 1 else ""
            
            user_masc = user_parte[0] + "***" + (user_parte[-1] if len(user_parte) > 1 else "")
            dom_masc = dom_parte[0] + "***." + dom_parte.split('.')[-1] if '.' in dom_parte else dom_parte
            email_enviado_mascarado = f"{user_masc}@{dom_masc}"

        disparo_solicitado = True
        return render_template('auth/esqueci_senha.html', 
                               sucesso_envio=disparo_solicitado, 
                               email_destino=email_enviado_mascarado)

    return render_template('auth/esqueci_senha.html', sucesso_envio=False)


@auth_bp.route('/redefinir-senha/<token>', methods=['GET', 'POST'])
def redefinir_senha(token):
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    # Valida o token criptográfico (tempo limite: 30 min)
    email = validar_token_recuperacao(token, max_age_segundos=1800)
    if not email:
        flash('O link de recuperação é inválido ou expirou. Solicite um novo envio.', 'danger')
        return redirect(url_for('auth.esqueci_senha'))

    usuario = Usuario.query.filter_by(email=email).first_or_404()

    if request.method == 'POST':
        nova_senha = request.form.get('nova_senha', '')
        confirma_senha = request.form.get('confirma_senha', '')

        senha_valida, msg_erro = validar_senha_forte(nova_senha)
        if not senha_valida:
            flash(msg_erro, 'warning')
            return redirect(request.url)

        if nova_senha != confirma_senha:
            flash('A nova palavra-passe e a confirmação não conferem.', 'warning')
            return redirect(request.url)

        # Grava a nova palavra-passe com hash seguro
        usuario.set_senha(nova_senha)
        db.session.commit()

        flash('Palavra-passe atualizada com sucesso! Inicie sessão com os novos dados.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/redefinir_senha.html', token=token)

@auth_bp.route('/seja-parceiro', methods=['GET', 'POST'])
def registro_afiliado():
    if current_user.is_authenticated:
        return redirect(url_for('painel_afiliado'))

    if request.method == 'POST':
        nome = (request.form.get('nome') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        confirma_email = (request.form.get('confirma_email') or '').strip().lower()
        cpf_cnpj = (request.form.get('cpf_cnpj') or '').strip()
        rede_social = (request.form.get('rede_social_principal') or '').strip()
        tipo_parceiro = request.form.get('tipo_parceiro', 'Outros')
        senha = request.form.get('senha', '')
        confirma_senha = request.form.get('confirma_senha', '')

        if email != confirma_email:
            flash('O e-mail e a confirmação de e-mail não conferem.', 'warning')
            return render_template('auth/registro_afiliado.html')

        senha_valida, msg_erro = validar_senha_forte(senha)
        if not senha_valida:
            flash(msg_erro, 'warning')
            return render_template('auth/registro_afiliado.html')

        if senha != confirma_senha:
            flash('As senhas não conferem.', 'warning')
            return render_template('auth/registro_afiliado.html')

        if Usuario.query.filter_by(email=email).first():
            flash('Este e-mail já está cadastrado. Faça login na sua conta.', 'warning')
            return render_template('auth/registro_afiliado.html')

        novo_user = Usuario(
            empresa_id=None,
            nome=nome,
            email=email,
            cpf_cnpj=cpf_cnpj,
            rede_social_principal=rede_social,
            tipo_parceiro=tipo_parceiro,
            cargo="Afiliado Parceiro",
            nivel_acesso="afiliado",
            ativo=True,
            status_aprovacao="pendente"
        )
        novo_user.set_senha(senha)
        db.session.add(novo_user)
        db.session.flush()

        codigo_sugerido = re.sub(r'[^A-Z0-9]', '', nome.split()[0].upper()) + "10"
        
        novo_cupom = CupomDesconto(
            usuario_id=novo_user.id,
            codigo=codigo_sugerido,
            percentual_desconto=10.0,
            percentual_comissao=20.0,
            limite_usos=100,
            ativo=False
        )
        db.session.add(novo_cupom)
        db.session.commit()

        login_user(novo_user)
        flash('Cadastro realizado! Seus dados foram enviados para análise da equipe.', 'info')
        return redirect(url_for('painel_afiliado'))

    return render_template('auth/registro_afiliado.html')

@auth_bp.route('/logout')
def logout():
    try:
        logout_user()
    except Exception:
        pass
    
    session.clear()
    
    flash('Você saiu da sua conta com segurança.', 'info')
    resposta = make_response(redirect(url_for('auth.login')))
    resposta.set_cookie('session', '', expires=0, max_age=0, path='/')
    resposta.set_cookie('remember_token', '', expires=0, max_age=0, path='/')
    
    return resposta