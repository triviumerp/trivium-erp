import io
import os
import re
import time
import html
import secrets
import csv
import zipfile
import pandas as pd
from functools import wraps
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from io import BytesIO, StringIO
from collections import defaultdict


# Carrega variáveis de ambiente (.env)
from dotenv import load_dotenv
load_dotenv()

# Flask e Autenticação
from flask import (
    Flask, render_template, request, redirect, 
    url_for, flash, send_from_directory, send_file, 
    abort, jsonify, session, make_response
)

from flask_login import login_required, current_user, login_user
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash

# Relatórios PDF (ReportLab)
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch

# Extensões, Modelos e Blueprints
from extensions import db, login_manager, limiter
from models import (
    Empresa, Usuario, Cliente, Documento, TipoServico, 
    ServicoCliente, Proposta, ItemProposta, ContratoRecorrente, 
    Fatura, ParcelaFatura, ChamadoSuporte, MensagemChamado, CupomDesconto, 
    ServicoCustoPadrao, ItemPropostaCusto, ContratoGerado, ServicoEtapaRastreio, 
    ComissaoAfiliado, RepasseAfiliado, EvidenciaServico, OperadorCampo,
    ProdutoEstoque, MovimentacaoEstoque, PedidoRequisicao, ItemPedidoRequisicao
)
from auth.routes import auth_bp
from auth.routes import validar_senha_forte

# Serviços Externos (Mercado Pago e Armazenamento Supabase S3)
import mercadopago
from services.mercadopago_service import (
    criar_cobranca_mercadopago, 
    criar_preferencia_mercado_pago,
    PLANOS_CONFIG
)
from services.storage_service import (
    salvar_arquivo_supabase,
    excluir_arquivo_supabase,
    gerar_url_temporaria,
    obter_arquivo_bytes,
    excluir_pasta_empresa_supabase
)

# -----------------------------------------------------------------------------
# 1. CONFIGURAÇÃO DA APLICAÇÃO
# -----------------------------------------------------------------------------
app = Flask(__name__)

# Configurações de Upload
UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Chave Secreta e Segurança de Sessão
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'trivium_erp_chave_secreta_producao_2026')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Conexão com o Banco de Dados
uri_banco = os.getenv('DATABASE_URL', 'postgresql://postgres:admin@127.0.0.1:5432/trivium_db')
if uri_banco.startswith("postgres://"):
    uri_banco = uri_banco.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri_banco
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configuração de Engine do SQLAlchemy
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "connect_args": {
        "options": "-cclient_encoding=utf8"
    }
}

# Inicialização de Extensões e Blueprints
db.init_app(app)
login_manager.init_app(app)
limiter.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Por favor, faça login para acessar o sistema.'
login_manager.login_message_category = 'warning'

app.register_blueprint(auth_bp)

# Criação de tabelas na inicialização
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"[ERRO AO CRIAR TABELAS]: {e}")

# Headers HTTP de Segurança
@app.after_request
def aplicar_headers_seguranca(response):
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

# Funções Auxiliares
def _limpar_texto(texto):
    """Garante que caracteres especiais não quebrem o parser XML do ReportLab."""
    if not texto:
        return ""
    return html.escape(str(texto).strip(), quote=True)

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

def master_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.nivel_acesso != 'master':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def _obter_logo_reportlab(logo_filename, width=1.5*inch, height=0.6*inch):
    """Auxiliar unificado para obter imagem para o ReportLab sem travar o PDF."""
    if not logo_filename:
        return None
    try:
        # Se estiver no Supabase
        if logo_filename.startswith('emp_') or '/' in logo_filename:
            stream = obter_arquivo_bytes(logo_filename)
            if stream:
                img = RLImage(stream, width=width, height=height)
                img.hAlign = 'LEFT'
                return img
        # Suporte para caminho local
        caminho_local = os.path.join(app.config['UPLOAD_FOLDER'], logo_filename)
        if os.path.exists(caminho_local):
            img = RLImage(caminho_local, width=width, height=height)
            img.hAlign = 'LEFT'
            return img
    except Exception as e:
        print(f"[AVISO REPORTLAB LOGO]: {e}")
    return None

# -----------------------------------------------------------------------------
# 2. ROTAS DO PAINEL MASTER
# -----------------------------------------------------------------------------

@app.route('/admin/master')
@login_required
@master_required
def admin_master_dashboard():
    empresas = Empresa.query.order_by(Empresa.data_criacao.desc()).all()
    total_empresas = len(empresas)
    total_ativas = len([e for e in empresas if e.status_assinatura == 'ativo'])
    total_trial = len([e for e in empresas if e.status_assinatura == 'trial'])
    total_bloqueadas = len([e for e in empresas if e.status_assinatura not in ['ativo', 'trial']])

    return render_template(
        'admin/master_dashboard.html',
        empresas=empresas,
        total_empresas=total_empresas,
        total_ativas=total_ativas,
        total_trial=total_trial,
        total_bloqueadas=total_bloqueadas,
    )

@app.route('/admin/master/chamados')
@login_required
@master_required
def admin_master_chamados():
    filtro = request.args.get('status', 'todos')
    query = ChamadoSuporte.query

    if filtro == 'abertos':
        query = query.filter_by(status='Aberto')
    elif filtro == 'em_atendimento':
        query = query.filter_by(status='Em Atendimento')
    elif filtro == 'resolvidos':
        query = query.filter_by(status='Resolvido')

    chamados = query.order_by(ChamadoSuporte.data_abertura.desc()).all()

    qtd_abertos = ChamadoSuporte.query.filter_by(status='Aberto').count()
    qtd_em_analise = ChamadoSuporte.query.filter_by(status='Em Atendimento').count()
    qtd_resolvidos = ChamadoSuporte.query.filter_by(status='Resolvido').count()
    total_historico = ChamadoSuporte.query.count()

    return render_template(
        'admin/master_chamados.html',
        chamados=chamados,
        filtro_atual=filtro,
        qtd_abertos=qtd_abertos,
        qtd_em_analise=qtd_em_analise,
        qtd_resolvidos=qtd_resolvidos,
        total_historico=total_historico,
    )

@app.route('/admin/master/chamados/<int:id>', methods=['GET', 'POST'])
@login_required
@master_required
def admin_atender_chamado(id):
    chamado = ChamadoSuporte.query.get_or_404(id)

    if request.method == 'POST':
        conteudo = request.form.get('mensagem')
        novo_status = request.form.get('novo_status')
        arquivo = request.files.get('anexo')

        filename = None
        if arquivo and arquivo.filename:
            try:
                filename = salvar_arquivo_supabase(
                    file_storage=arquivo,
                    pasta_destino='suporte',
                    empresa_id=chamado.empresa_id
                )
            except ValueError as err:
                flash(str(err), 'danger')
                return redirect(url_for('admin_atender_chamado', id=chamado.id))

        if conteudo or filename:
            msg_suporte = MensagemChamado(
                chamado_id=chamado.id,
                usuario_id=current_user.id,
                conteudo=conteudo or "Anexo enviado pelo suporte.",
                is_suporte=True,
                anexo_filename=filename,
            )
            db.session.add(msg_suporte)

        if novo_status:
            chamado.status = novo_status
            if novo_status == 'Resolvido':
                chamado.data_fechamento = datetime.now()

        db.session.commit()
        flash(f'Chamado {chamado.numero_protocolo} atualizado!', 'success')
        return redirect(url_for('admin_atender_chamado', id=chamado.id))

    return render_template('admin/master_atender_chamado.html', chamado=chamado)

@app.route('/admin/master/usuarios')
@login_required
@master_required
def admin_master_usuarios():
    usuarios = (
        Usuario.query.join(Empresa)
        .order_by(Usuario.nivel_acesso.desc(), Usuario.nome.asc())
        .all()
    )
    return render_template('admin/master_usuarios.html', usuarios=usuarios)

@app.route('/admin/master/usuarios/<int:id>/alterar-nivel', methods=['POST'])
@login_required
@master_required
def admin_alterar_nivel_usuario(id):
    usuario = Usuario.query.get_or_404(id)
    novo_nivel = request.form.get('nivel_acesso')

    if usuario.id == current_user.id and novo_nivel != 'master':
        flash('Você não pode remover seu próprio privilégio de Master.', 'danger')
        return redirect(url_for('admin_master_usuarios'))

    if novo_nivel in ['operador', 'admin', 'master']:
        usuario.nivel_acesso = novo_nivel
        db.session.commit()
        flash(f'Nível de acesso de "{usuario.nome}" atualizado para "{novo_nivel.upper()}".', 'success')
    else:
        flash('Nível de acesso inválido informado.', 'danger')

    return redirect(url_for('admin_master_usuarios'))

@app.route('/admin/master/impersonar/<int:empresa_id>')
@login_required
@master_required
def admin_impersonar_empresa(empresa_id):
    alvo_empresa = Empresa.query.get_or_404(empresa_id)
    usuario_alvo = Usuario.query.filter_by(empresa_id=alvo_empresa.id).first()

    if not usuario_alvo:
        flash('Esta empresa não possui nenhum usuário cadastrado para acesso.', 'danger')
        return redirect(url_for('admin_master_dashboard'))

    session['original_master_id'] = current_user.id
    login_user(usuario_alvo)

    flash(f'Modo Suporte Ativado: Você está navegando como "{usuario_alvo.nome}" ({alvo_empresa.razao_social}).', 'warning')
    return redirect(url_for('index'))

@app.route('/admin/master/sair-impersonacao')
@login_required
def admin_sair_impersonacao():
    master_id = session.pop('original_master_id', None)
    if master_id:
        usuario_master = Usuario.query.get(master_id)
        if usuario_master and usuario_master.nivel_acesso == 'master':
            login_user(usuario_master)
            flash('Você retornou ao seu painel Master.', 'info')
            return redirect(url_for('admin_master_dashboard'))

    return redirect(url_for('auth.logout'))

@app.route('/admin/master/empresa/<int:id>/atualizar-gestao', methods=['POST'])
@login_required
@master_required
def admin_atualizar_gestao_empresa(id):
    empresa = Empresa.query.get_or_404(id)
    
    plano_escolhido = request.form.get('plano', empresa.plano)
    empresa.plano = plano_escolhido
    empresa.status_assinatura = request.form.get('status_assinatura', empresa.status_assinatura)
    empresa.forma_pagamento_mp = request.form.get('forma_pagamento_mp', getattr(empresa, 'forma_pagamento_mp', None))
    empresa.observacoes_master = request.form.get('observacoes_master')

    # Preenche valor correspondente caso não seja digitado manualmente
    valor_form = request.form.get('valor_mensalidade')
    if valor_form and valor_form.strip():
        empresa.valor_mensalidade = float(valor_form)
    else:
        valores_padrao = {
            'Mensal': 39.90,
            'Semestral': 34.90,
            'Anual': 29.90,
            'Trial': 0.0
        }
        empresa.valor_mensalidade = valores_padrao.get(plano_escolhido, empresa.valor_mensalidade)

    dt_venc = request.form.get('data_vencimento')
    if dt_venc:
        empresa.data_vencimento = datetime.strptime(dt_venc, '%Y-%m-%d').date()

    dt_pag = request.form.get('data_ultimo_pagamento')
    if dt_pag:
        empresa.data_ultimo_pagamento = datetime.strptime(dt_pag, '%Y-%m-%d').date()

    db.session.commit()
    flash(f'Gestão da empresa "{empresa.razao_social}" atualizada com sucesso!', 'success')
    return redirect(url_for('admin_master_dashboard'))

@app.route('/admin/master/empresa/<int:id>/excluir-definitivo', methods=['POST'])
@login_required
@master_required
def admin_excluir_empresa_definitiva(id):
    empresa = Empresa.query.get_or_404(id)
    nome_empresa = empresa.razao_social
    empresa_id = empresa.id

    try:
        # 1. Remove anexos e ficheiros do Storage Supabase S3
        excluir_pasta_empresa_supabase(empresa_id)

        # 2. Apaga chamados de suporte e mensagens vinculadas explicitamente
        chamados_empresa = ChamadoSuporte.query.filter_by(empresa_id=empresa_id).all()
        for chamado in chamados_empresa:
            db.session.delete(chamado)

        # 3. Remove comissões de afiliados e contratos gerados vinculados à empresa
        ComissaoAfiliado.query.filter_by(empresa_id=empresa_id).delete()
        ContratoGerado.query.filter_by(empresa_id=empresa_id).delete()

        # 4. Exclui a empresa e todas as restantes entidades em cascata
        db.session.delete(empresa)
        db.session.commit()

        flash(f'Empresa "{nome_empresa}" (ID: {empresa_id}) e todos os seus ficheiros/registos foram removidos permanentemente!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir empresa permanentemente: {str(e)}', 'danger')

    return redirect(url_for('admin_master_dashboard'))

@app.route('/admin/master/usuario/<int:id>/redefinir-senha', methods=['POST'])
@login_required
@master_required
def admin_redefinir_senha_usuario(id):
    usuario = Usuario.query.get_or_404(id)
    nova_senha = request.form.get('nova_senha')

    if not nova_senha or len(nova_senha) < 6:
        flash('A nova senha deve ter pelo menos 6 caracteres.', 'danger')
    else:
        usuario.senha_hash = generate_password_hash(nova_senha)
        db.session.commit()
        flash(f'Senha de "{usuario.nome}" redefinida com sucesso para: {nova_senha}', 'success')

    return redirect(url_for('admin_master_usuarios'))

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

# -----------------------------------------------------------------------------
# 3. CONTEXT PROCESSOR & MIDDLEWARES
# -----------------------------------------------------------------------------

@app.context_processor
def utility_processor():
    perfil = None
    if current_user.is_authenticated:
        perfil = current_user.empresa
    return dict(perfil_empresa=perfil)

@app.before_request
def interceptar_bloqueio_assinatura():
    rotas_livres = [
        'auth.',
        'static',
        'download_file',
        'webhook_mercadopago',
        'regularizar_assinatura',
        'api_checkout_transparente'
    ]
    if request.endpoint and any(request.endpoint.startswith(r) for r in rotas_livres):
        return None
    
    if current_user.is_authenticated and current_user.nivel_acesso == 'afiliado':
        return None

    if current_user.is_authenticated:
        if current_user.nivel_acesso == 'master':
            return None

        if current_user.empresa:
            if current_user.empresa.status_assinatura in ['bloqueado', 'cancelado']:
                if request.endpoint != 'regularizar_assinatura':
                    return redirect(url_for('regularizar_assinatura'))

            if current_user.empresa.status_assinatura == 'trial' and current_user.empresa.data_vencimento:
                if current_user.empresa.data_vencimento < date.today():
                    current_user.empresa.status_assinatura = 'bloqueado'
                    db.session.commit()
                    if request.endpoint != 'regularizar_assinatura':
                        return redirect(url_for('regularizar_assinatura'))

@app.route('/painel-afiliado', methods=['GET', 'POST'])
@login_required
def painel_afiliado():
    if current_user.nivel_acesso != 'afiliado':
        flash('Acesso restrito a parceiros afiliados.', 'danger')
        return redirect(url_for('index'))

    cupons = CupomDesconto.query.filter_by(usuario_id=current_user.id).order_by(CupomDesconto.id.asc()).all()
    if not cupons:
        codigo_sugerido = re.sub(r'[^A-Z0-9]', '', current_user.nome.split()[0].upper()) + "10"
        cupom_padrao = CupomDesconto(
            usuario_id=current_user.id,
            codigo=codigo_sugerido,
            percentual_desconto=10.0,
            percentual_comissao=20.0,
            meses_comissao_limite=3,
            ativo=True if current_user.status_aprovacao == 'aprovado' else False
        )
        db.session.add(cupom_padrao)
        db.session.commit()
        cupons = [cupom_padrao]

    cupom_principal = cupons[0]
    link_principal = url_for('auth.registro', ref=cupom_principal.codigo, _external=True)

    if request.method == 'POST':
        chave_pix = request.form.get('chave_pix', '').strip()
        whatsapp = request.form.get('whatsapp', '').strip()
        rede_social = request.form.get('rede_social_principal', '').strip()
        aceitou_termos = bool(request.form.get('aceitou_termos'))

        current_user.chave_pix = chave_pix
        current_user.whatsapp = whatsapp
        current_user.rede_social_principal = rede_social
        
        if aceitou_termos:
            current_user.aceitou_termos_afiliado = True
            current_user.data_aceite_termos_afiliado = datetime.utcnow()
            if current_user.status_aprovacao == 'aprovado':
                for c in cupons:
                    c.ativo = True

        db.session.commit()
        flash('Informações e dados de repasse atualizados com sucesso!', 'success')
        return redirect(url_for('painel_afiliado'))

    codigos_cupons = [c.codigo for c in cupons]
    cupons_ids = [c.id for c in cupons]

    condicoes = []
    if codigos_cupons:
        condicoes.append(Empresa.cupom_utilizado.in_(codigos_cupons))
    if cupons_ids:
        condicoes.append(Empresa.afiliado_id.in_(cupons_ids))

    if condicoes:
        from sqlalchemy import or_
        empresas_indicadas = Empresa.query.filter(or_(*condicoes)).order_by(Empresa.data_criacao.desc()).all()
    else:
        empresas_indicadas = []
    
    total_cadastros = len(empresas_indicadas)
    total_assinantes_ativos = sum(1 for e in empresas_indicadas if e.status_assinatura == 'ativo')
    
    comissao_recorrente_estimada = sum(
        (e.valor_mensalidade or 39.90) * (getattr(e, 'percentual_comissao_parceiro', 20.0) / 100.0)
        for e in empresas_indicadas if e.status_assinatura == 'ativo'
    )

    return render_template(
        'afiliados/painel.html',
        cupons=cupons,
        cupom_principal=cupom_principal,
        link_principal=link_principal,
        empresas_indicadas=empresas_indicadas,
        total_cadastros=total_cadastros,
        total_assinantes_ativos=total_assinantes_ativos,
        comissao_recorrente_estimada=comissao_recorrente_estimada
    )

# -----------------------------------------------------------------------------
# 4. ROTAS DO DASHBOARD & CLIENTES
# -----------------------------------------------------------------------------

@app.route('/')
@login_required
def index():
    hoje = date.today()
    proximos_7_dias = hoje + timedelta(days=7)
    empresa = current_user.empresa

    # 1. Indicadores Universais
    total_clientes = Cliente.query.filter_by(empresa_id=empresa.id).count()

    # 2. Comercial / Propostas
    propostas_todas = Proposta.query.filter_by(empresa_id=empresa.id).all()
    qtd_total_propostas = len(propostas_todas)
    qtd_propostas_aprovadas = len([p for p in propostas_todas if p.status == 'Aprovado'])
    taxa_conversao_propostas = round((qtd_propostas_aprovadas / qtd_total_propostas * 100), 1) if qtd_total_propostas > 0 else 0.0

    propostas_abertas = [p for p in propostas_todas if p.status == 'Aguardando Aprovação']
    qtd_propostas_negociacao = len(propostas_abertas)
    valor_propostas_abertas = sum(p.valor_total for p in propostas_abertas)

    # 3. Serviços & Campo
    qtd_servicos_execucao = 0
    total_servicos_concluidos = 0
    proximos_servicos = []
    if empresa.modulo_servicos_campo:
        query_os = ServicoCliente.query.filter_by(empresa_id=empresa.id).filter(
            (ServicoCliente.tipo_ficha == 'operacional') | (ServicoCliente.tipo_ficha.is_(None))
        )
        qtd_servicos_execucao = query_os.filter(ServicoCliente.status.in_(['Em Andamento', 'Bloqueado'])).count()
        total_servicos_concluidos = query_os.filter_by(status='Concluido').count()
        proximos_servicos = query_os.filter(
            ServicoCliente.status.in_(['Em Andamento', 'Pendente', 'Bloqueado'])
        ).order_by(ServicoCliente.data_previsao.asc().nullslast()).limit(5).all()

    # 4. Atendimentos Clínicos
    qtd_atendimentos_pendentes = 0
    total_consultas_realizadas = 0
    proximos_atendimentos = []
    if empresa.modulo_atendimentos:
        query_atend = ServicoCliente.query.filter_by(empresa_id=empresa.id, tipo_ficha='atendimento')
        qtd_atendimentos_pendentes = query_atend.filter(ServicoCliente.status.in_(['Em Andamento', 'Pendente'])).count()
        total_consultas_realizadas = query_atend.filter_by(status='Concluido').count()
        proximos_atendimentos = query_atend.filter(
            ServicoCliente.status.in_(['Em Andamento', 'Pendente'])
        ).order_by(ServicoCliente.data_previsao.asc().nullslast()).limit(5).all()

    # 5. Estoque & Almoxarifado
    total_itens_estoque = 0
    itens_alerta_baixo = 0
    valor_imobilizado_estoque = 0.0
    if empresa.modulo_estoque:
        produtos = ProdutoEstoque.query.filter_by(empresa_id=empresa.id).all()
        total_itens_estoque = len(produtos)
        itens_alerta_baixo = sum(1 for p in produtos if p.alerta_estoque_baixo)
        valor_imobilizado_estoque = sum((p.quantidade_atual or 0) * (p.preco_custo or 0) for p in produtos)

    # 6. Vendas & Expedição
    pedidos_separacao = 0
    pedidos_rota = 0
    total_entregas_concluidas = 0
    if empresa.modulo_vendas_externas or empresa.modulo_estoque:
        pedidos_separacao = PedidoRequisicao.query.filter_by(empresa_id=empresa.id, status='em_separacao').count()
        pedidos_rota = PedidoRequisicao.query.filter_by(empresa_id=empresa.id, status='em_rota').count()
        total_entregas_concluidas = PedidoRequisicao.query.filter_by(empresa_id=empresa.id, status='entregue').count()

    # 7. Financeiro & Inadimplência
    todas_parcelas = ParcelaFatura.query.filter_by(empresa_id=empresa.id).all()
    total_recebido_mes = sum(p.valor for p in todas_parcelas if p.status == 'Pago')
    
    titulos_atrasados = [p for p in todas_parcelas if p.status != 'Pago' and p.data_vencimento and p.data_vencimento < hoje]
    qtd_titulos_atrasados = len(titulos_atrasados)
    valor_titulos_atrasados = sum(p.valor for p in titulos_atrasados)

    titulos_proximos = ParcelaFatura.query.filter_by(empresa_id=empresa.id).filter(
        ParcelaFatura.status != 'Pago',
        ParcelaFatura.data_vencimento >= hoje,
        ParcelaFatura.data_vencimento <= proximos_7_dias
    ).order_by(ParcelaFatura.data_vencimento.asc()).limit(5).all()

    return render_template(
        'index.html',
        hoje=hoje,
        total_clientes=total_clientes,
        qtd_propostas_negociacao=qtd_propostas_negociacao,
        valor_propostas_abertas=valor_propostas_abertas,
        taxa_conversao_propostas=taxa_conversao_propostas,
        qtd_servicos_execucao=qtd_servicos_execucao,
        total_servicos_concluidos=total_servicos_concluidos,
        proximos_servicos=proximos_servicos,
        qtd_atendimentos_pendentes=qtd_atendimentos_pendentes,
        total_consultas_realizadas=total_consultas_realizadas,
        proximos_atendimentos=proximos_atendimentos,
        total_itens_estoque=total_itens_estoque,
        itens_alerta_baixo=itens_alerta_baixo,
        valor_imobilizado_estoque=valor_imobilizado_estoque,
        pedidos_separacao=pedidos_separacao,
        pedidos_rota=pedidos_rota,
        total_entregas_concluidas=total_entregas_concluidas,
        total_recebido_mes=total_recebido_mes,
        qtd_titulos_atrasados=qtd_titulos_atrasados,
        valor_titulos_atrasados=valor_titulos_atrasados,
        titulos_proximos=titulos_proximos
    )

@app.route('/clientes')
@login_required
def listar_clientes():
    busca = request.args.get('busca', '')
    query = Cliente.query.filter_by(empresa_id=current_user.empresa_id)

    if busca:
        query = query.filter(
            (Cliente.nome.ilike(f'%{busca}%')) | 
            (Cliente.cnpj_cpf.ilike(f'%{busca}%')) |
            (Cliente.cidade.ilike(f'%{busca}%'))
        )

    clientes = query.order_by(Cliente.nome).all()
    return render_template('clientes.html', clientes=clientes, busca=busca)

@app.route('/cliente/novo', methods=['GET', 'POST'])
@login_required
def novo_cliente():
    if request.method == 'POST':
        tipo_pessoa = request.form.get('tipo_pessoa', 'PJ')
        nome = request.form.get('nome')
        nome_fantasia = request.form.get('nome_fantasia')
        cnpj_cpf = request.form.get('cnpj') if tipo_pessoa == 'PJ' else request.form.get('cpf')
        telefone = request.form.get('telefone')
        email = request.form.get('email')
        
        novo_cli = Cliente(
            empresa_id=current_user.empresa_id,
            nome=nome,
            nome_fantasia=nome_fantasia,
            cnpj_cpf=cnpj_cpf,
            inscricao_estadual=request.form.get('inscricao_estadual'),
            responsavel=request.form.get('responsavel'),
            telefone=telefone,
            telefone_secundario=request.form.get('telefone_secundario'),
            email=email,
            email_financeiro=request.form.get('email_financeiro'),
            cep=request.form.get('cep'),
            logradouro=request.form.get('logradouro'),
            numero=request.form.get('numero'),
            complemento=request.form.get('complemento'),
            bairro=request.form.get('bairro'),
            cidade=request.form.get('cidade'),
            estado=request.form.get('estado'),
            observacoes=request.form.get('observacoes')
        )
        db.session.add(novo_cli)
        db.session.commit()

        flash(f'Cliente "{novo_cli.nome}" cadastrado com sucesso!', 'success')

        acao = request.form.get('acao')
        if acao == 'salvar_e_proposta':
            return redirect(url_for('listar_propostas', cliente_id=novo_cli.id, abrir_modal='true'))

        return redirect(url_for('listar_clientes'))

    return render_template('cadastro.html', cliente=None)

@app.route('/cliente/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_cliente(id):
    cliente = Cliente.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()

    if request.method == 'POST':
        tipo_pessoa = request.form.get('tipo_pessoa')
        doc_identificacao = request.form.get('cnpj') if tipo_pessoa == 'PJ' else request.form.get('cpf')

        if tipo_pessoa == 'PF' and doc_identificacao:
            if not is_cpf_valido(doc_identificacao):
                flash('O CPF informado é inválido. Por favor, revise os dígitos.', 'danger')
                return render_template('cadastro.html', cliente=cliente)

        cliente.nome = request.form.get('nome')
        cliente.nome_fantasia = request.form.get('nome_fantasia') if tipo_pessoa == 'PJ' else None
        cliente.cnpj_cpf = doc_identificacao
        cliente.inscricao_estadual = request.form.get('inscricao_estadual') if tipo_pessoa == 'PJ' else None
        cliente.responsavel = request.form.get('responsavel')
        cliente.telefone = request.form.get('telefone')
        cliente.telefone_secundario = request.form.get('telefone_secundario')
        cliente.email = request.form.get('email')
        cliente.email_financeiro = request.form.get('email_financeiro')
        cliente.cep = request.form.get('cep')
        cliente.logradouro = request.form.get('logradouro')
        cliente.numero = request.form.get('numero')
        cliente.complemento = request.form.get('complemento')
        cliente.bairro = request.form.get('bairro')
        cliente.cidade = request.form.get('cidade')
        cliente.estado = request.form.get('estado')
        cliente.observacoes = request.form.get('observacoes')

        db.session.commit()
        flash('Cadastro atualizado com sucesso!', 'success')
        return redirect(url_for('detalhe_cliente', id=cliente.id))

    return render_template('cadastro.html', cliente=cliente)

@app.route('/cliente/deletar/<int:id>')
@login_required
def deletar_cliente(id):
    cliente = Cliente.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    db.session.delete(cliente)
    db.session.commit()
    flash('Cliente e todo o histórico vinculado foram removidos.', 'warning')
    return redirect(url_for('listar_clientes'))

@app.route('/cliente/<int:id>')
@login_required
def detalhe_cliente(id):
    try:
        cliente = Cliente.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
        documentos = Documento.query.filter_by(cliente_id=cliente.id).order_by(Documento.data_upload.desc()).all()
        contratos_gerados = ContratoGerado.query.filter_by(cliente_id=cliente.id, empresa_id=current_user.empresa_id).order_by(ContratoGerado.data_criacao.desc()).all()
        
        return render_template(
            'detalhe_cliente.html', 
            cliente=cliente, 
            documentos=documentos, 
            contratos_gerados=contratos_gerados
        )
    except Exception as e:
        flash(f'Erro ao carregar o cliente: {str(e)}', 'danger')
        return redirect(url_for('listar_clientes'))

@app.route('/cliente/<int:id>/upload', methods=['POST'])
@login_required
def upload_documento(id):
    cliente = Cliente.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    if 'arquivo' not in request.files:
        flash('Nenhum arquivo enviado!', 'danger')
        return redirect(url_for('detalhe_cliente', id=id))
        
    file = request.files['arquivo']
    tipo = request.form.get('tipo_documento')

    if not file or file.filename == '':
        flash('Nenhum arquivo selecionado!', 'danger')
        return redirect(url_for('detalhe_cliente', id=id))

    try:
        chave_salva = salvar_arquivo_supabase(
            file_storage=file,
            pasta_destino='docs_clientes',
            empresa_id=current_user.empresa_id
        )
        doc = Documento(cliente_id=cliente.id, nome_arquivo=chave_salva, tipo_documento=tipo)
        db.session.add(doc)
        db.session.commit()
        flash('Documento anexado com sucesso no Supabase!', 'success')
    except ValueError as err:
        flash(str(err), 'danger')
    except Exception as e:
        flash(f'Erro ao enviar o documento: {str(e)}', 'danger')

    return redirect(url_for('detalhe_cliente', id=id))

@app.route('/documento/deletar/<int:doc_id>')
@login_required
def deletar_documento(doc_id):
    doc = Documento.query.join(Cliente).filter(Documento.id == doc_id, Cliente.empresa_id == current_user.empresa_id).first_or_404()
    cliente_id = doc.cliente_id

    if doc.nome_arquivo:
        excluir_arquivo_supabase(doc.nome_arquivo)

    db.session.delete(doc)
    db.session.commit()
    flash('Documento removido com sucesso.', 'info')
    return redirect(url_for('detalhe_cliente', id=cliente_id))

@app.route('/uploads/<path:filename>')
@login_required
def download_file(filename):
    """Redireciona diretamente para o link assinado temporário do Supabase Storage."""
    prefixo_permitido = f"emp_{current_user.empresa_id}/"
    if not filename.startswith(prefixo_permitido) and getattr(current_user, 'nivel_acesso', '') != 'master':
        abort(403)

    url_temporaria = gerar_url_temporaria(filename, tempo_segundos=900)
    if not url_temporaria:
        abort(404)

    return redirect(url_temporaria)


# =============================================================================
# IMPORTAÇÃO & EXPORTAÇÃO DE ESTOQUE EM EXCEL (.XLSX)
# =============================================================================

@app.route('/estoque/modelo-excel')
@login_required
def baixar_modelo_estoque_excel():
    """Gera um modelo de planilha padrão com instruções para importação em lote."""
    if not current_user.empresa.modulo_estoque and current_user.nivel_acesso != 'master':
        abort(403)

    dados_exemplo = [
        {
            'NOME': 'Cabo Flexível 2.5mm Azul 100m',
            'CODIGO_SKU': 'CAB-FLEX-25-AZ',
            'CODIGO_BARRAS': '7891234567890',
            'UNIDADE': 'rl',
            'TIPO_ITEM': 'consumo_interno',  # venda, consumo_interno ou misto
            'QUANTIDADE_INICIAL': 15.0,
            'QUANTIDADE_MINIMA': 3.0,
            'PRECO_CUSTO': 145.50,
            'PRECO_VENDA_SUGERIDO': 210.00,
            'DESCRICAO': 'Rolo de 100 metros antichamas'
        },
        {
            'NOME': 'Disjuntor Bipolar 32A Curva C',
            'CODIGO_SKU': 'DISJ-BI-32A',
            'CODIGO_BARRAS': '7899876543210',
            'UNIDADE': 'un',
            'TIPO_ITEM': 'venda',
            'QUANTIDADE_INICIAL': 40.0,
            'QUANTIDADE_MINIMA': 10.0,
            'PRECO_CUSTO': 28.00,
            'PRECO_VENDA_SUGERIDO': 49.90,
            'DESCRICAO': 'Padrão DIN para trilho'
        }
    ]

    df = pd.DataFrame(dados_exemplo)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Modelo_Estoque')
    
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name="Modelo_Importacao_Estoque_Trivium.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.route('/estoque/exportar-excel')
@login_required
def exportar_estoque_excel():
    """Exporta a lista completa de produtos e saldos atuais da empresa em formato Excel."""
    if not current_user.empresa.modulo_estoque and current_user.nivel_acesso != 'master':
        abort(403)

    empresa_id = current_user.empresa_id
    produtos = ProdutoEstoque.query.filter_by(empresa_id=empresa_id).order_by(ProdutoEstoque.nome.asc()).all()

    dados = []
    for p in produtos:
        dados.append({
            'ID': p.id,
            'NOME': p.nome,
            'CODIGO_SKU': p.codigo_sku or '',
            'CODIGO_BARRAS': p.codigo_barras or '',
            'UNIDADE': p.unidade_medida or 'un',
            'TIPO_ITEM': p.tipo_item,
            'SALDO_ATUAL': p.quantidade_atual or 0.0,
            'QUANTIDADE_MINIMA': p.quantidade_minima or 0.0,
            'PRECO_CUSTO': p.preco_custo or 0.0,
            'PRECO_VENDA_SUGERIDO': p.preco_venda_sugerido or 0.0,
            'VALOR_TOTAL_EM_ESTOQUE': round((p.quantidade_atual or 0.0) * (p.preco_custo or 0.0), 2),
            'STATUS_ALERTA': 'BAIXO' if p.alerta_estoque_baixo else 'NORMAL',
            'DESCRICAO': p.descricao or ''
        })

    df = pd.DataFrame(dados)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Estoque_Atual')

    output.seek(0)
    nome_arquivo = f"Estoque_{current_user.empresa.razao_social[:15].strip()}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=nome_arquivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.route('/estoque/importar-excel', methods=['POST'])
@login_required
def importar_estoque_excel():
    """Lê a planilha enviada, cadastra novos produtos ou atualiza saldos já existentes."""
    if not current_user.empresa.modulo_estoque and current_user.nivel_acesso != 'master':
        flash('Módulo de estoque indisponível para importação.', 'danger')
        return redirect(url_for('listar_estoque'))

    arquivo = request.files.get('arquivo_excel')
    if not arquivo or not arquivo.filename:
        flash('Nenhum arquivo Excel selecionado.', 'warning')
        return redirect(url_for('listar_estoque'))

    ext = arquivo.filename.rsplit('.', 1)[-1].lower()
    if ext not in ['xlsx', 'xls']:
        flash('Formato inválido. Por favor, envie uma planilha no formato .xlsx ou .xls.', 'danger')
        return redirect(url_for('listar_estoque'))

    try:
        df = pd.read_excel(arquivo)
        # Padroniza nomes das colunas (maiúsculas e sem espaços extras)
        df.columns = [str(col).strip().upper() for col in df.columns]

        if 'NOME' not in df.columns:
            flash('A coluna obrigatória "NOME" não foi encontrada na planilha. Baixe o modelo padrão.', 'danger')
            return redirect(url_for('listar_estoque'))

        empresa_id = current_user.empresa_id
        novos_cadastrados = 0
        atualizados = 0

        for _, row in df.iterrows():
            nome = str(row.get('NOME', '')).strip()
            if not nome or nome.lower() == 'nan':
                continue

            sku = str(row.get('CODIGO_SKU', '')).strip()
            if not sku or sku.lower() == 'nan':
                sku = None

            barras = str(row.get('CODIGO_BARRAS', '')).strip()
            if not barras or barras.lower() == 'nan':
                barras = None

            unidade = str(row.get('UNIDADE', 'un')).strip() or 'un'
            if unidade.lower() == 'nan':
                unidade = 'un'

            tipo_item = str(row.get('TIPO_ITEM', 'misto')).strip().lower()
            if tipo_item not in ['venda', 'consumo_interno', 'misto']:
                tipo_item = 'misto'

            qtd_inicial = float(row.get('QUANTIDADE_INICIAL', 0.0) if pd.notnull(row.get('QUANTIDADE_INICIAL')) else 0.0)
            qtd_min = float(row.get('QUANTIDADE_MINIMA', 5.0) if pd.notnull(row.get('QUANTIDADE_MINIMA')) else 5.0)
            p_custo = float(row.get('PRECO_CUSTO', 0.0) if pd.notnull(row.get('PRECO_CUSTO')) else 0.0)
            p_venda = float(row.get('PRECO_VENDA_SUGERIDO', 0.0) if pd.notnull(row.get('PRECO_VENDA_SUGERIDO')) else 0.0)
            descricao = str(row.get('DESCRICAO', '')).strip()
            if descricao.lower() == 'nan':
                descricao = None

            # 1. Verifica se o produto já existe pelo SKU ou Código de Barras na mesma empresa
            produto = None
            if sku:
                produto = ProdutoEstoque.query.filter_by(empresa_id=empresa_id, codigo_sku=sku).first()
            if not produto and barras:
                produto = ProdutoEstoque.query.filter_by(empresa_id=empresa_id, codigo_barras=barras).first()
            if not produto:
                produto = ProdutoEstoque.query.filter_by(empresa_id=empresa_id, nome=nome).first()

            if produto:
                # Atualiza dados existentes e ajusta o saldo
                saldo_anterior = float(produto.quantidade_atual or 0.0)
                produto.nome = nome
                produto.unidade_medida = unidade
                produto.tipo_item = tipo_item
                produto.preco_custo = p_custo
                produto.preco_venda_sugerido = p_venda
                produto.quantidade_minima = qtd_min
                if descricao:
                    produto.descricao = descricao

                # Se a planilha enviou quantidade inicial positiva, soma ao saldo
                if qtd_inicial > 0:
                    produto.quantidade_atual = saldo_anterior + qtd_inicial
                    mov = MovimentacaoEstoque(
                        empresa_id=empresa_id,
                        produto_id=produto.id,
                        tipo_movimento='entrada_manual',
                        quantidade=qtd_inicial,
                        saldo_anterior=saldo_anterior,
                        saldo_posterior=produto.quantidade_atual,
                        motivo_observacao='Importação Excel: Atualização de Saldo',
                        usuario_id=current_user.id
                    )
                    db.session.add(mov)

                atualizados += 1
            else:
                # Cadastra novo produto
                novo_prod = ProdutoEstoque(
                    empresa_id=empresa_id,
                    nome=nome,
                    codigo_sku=sku,
                    codigo_barras=barras,
                    unidade_medida=unidade,
                    tipo_item=tipo_item,
                    quantidade_atual=qtd_inicial,
                    quantidade_minima=qtd_min,
                    preco_custo=p_custo,
                    preco_venda_sugerido=p_venda,
                    descricao=descricao
                )
                db.session.add(novo_prod)
                db.session.flush()

                if qtd_inicial > 0:
                    mov = MovimentacaoEstoque(
                        empresa_id=empresa_id,
                        produto_id=novo_prod.id,
                        tipo_movimento='entrada_manual',
                        quantidade=qtd_inicial,
                        saldo_anterior=0.0,
                        saldo_posterior=qtd_inicial,
                        motivo_observacao='Importação Excel: Saldo Inicial',
                        usuario_id=current_user.id
                    )
                    db.session.add(mov)

                novos_cadastrados += 1

        db.session.commit()
        flash(f'Importação concluída com sucesso! {novos_cadastrados} novo(s) item(ns) cadastrado(s) e {atualizados} atualizado(s).', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao processar planilha: {str(e)}', 'danger')

    return redirect(url_for('listar_estoque'))

# -----------------------------------------------------------------------------
# 5. ROTAS DE PROPOSTAS COMERCIAIS
# -----------------------------------------------------------------------------

@app.route('/propostas')
@login_required
def listar_propostas():
    filtro_atual = request.args.get('filtro', 'ativas')
    query = Proposta.query.filter_by(empresa_id=current_user.empresa_id)

    if filtro_atual == 'ativas':
        propostas = query.filter_by(status='Aguardando Aprovação').order_by(Proposta.data_criacao.desc()).all()
    elif filtro_atual == 'aprovadas':
        propostas = query.filter_by(status='Aprovado').order_by(Proposta.data_criacao.desc()).all()
    elif filtro_atual == 'canceladas':
        propostas = query.filter_by(status='Cancelado').order_by(Proposta.data_criacao.desc()).all()
    else:
        propostas = query.order_by(Proposta.data_criacao.desc()).all()

    todas = query.all()
    total_aguardando = sum(p.valor_total for p in todas if p.status == 'Aguardando Aprovação')
    total_aprovadas = sum(p.valor_total for p in todas if p.status == 'Aprovado')
    qtd_aguardando = len([p for p in todas if p.status == 'Aguardando Aprovação'])

    clientes = Cliente.query.filter_by(empresa_id=current_user.empresa_id).order_by(Cliente.nome).all()
    tipos_servico = TipoServico.query.filter_by(empresa_id=current_user.empresa_id).all()

    return render_template(
        'propostas.html',
        propostas=propostas,
        filtro_atual=filtro_atual,
        total_aguardando=total_aguardando,
        total_aprovadas=total_aprovadas,
        qtd_aguardando=qtd_aguardando,
        clientes=clientes,
        tipos_servico=tipos_servico
    )

@app.route('/propostas/nova', methods=['POST'])
@login_required
def criar_proposta():
    try:
        cliente_id = int(request.form.get('cliente_id'))
        validade_dias = int(request.form.get('validade_dias') or 15)
        condicoes = request.form.get('condicoes_pagamento') or 'Conforme alinhamento comercial'
        observacoes = request.form.get('observacoes')
        
        tipo_cobranca = request.form.get('tipo_cobranca', 'pontual')
        periodicidade = request.form.get('periodicidade', 'mensal')
        dia_vencimento = int(request.form.get('dia_vencimento') or 10)

        exige_entrada = request.form.get('exige_entrada') in ['on', 'true']
        valor_entrada = float(request.form.get('valor_entrada') or 0.0)
        forma_pagamento_entrada = request.form.get('forma_pagamento_entrada', 'PIX')
        qtd_parcelas = int(request.form.get('qtd_parcelas') or 1)
        forma_pagamento_parcelas = request.form.get('forma_pagamento_parcelas', 'Boleto Bancário')
        intervalo_dias = int(request.form.get('intervalo_dias') or 30)
        
        total_existentes = Proposta.query.filter_by(empresa_id=current_user.empresa_id).count() + 1
        numero_proposta = f"PROP-{date.today().year}-{total_existentes:03d}"
        tipo_destino = request.form.get('tipo_destino', 'operacional')

        nova_prop = Proposta(
            empresa_id=current_user.empresa_id,
            numero_proposta=numero_proposta,
            cliente_id=cliente_id,
            validade_dias=validade_dias,
            condicoes_pagamento=condicoes,
            observacoes=observacoes,
            status='Aguardando Aprovação',
            tipo_cobranca=tipo_cobranca,
            periodicidade=periodicidade,
            dia_vencimento=dia_vencimento,
            tipo_destino=tipo_destino,
            exige_entrada=exige_entrada,
            valor_entrada=valor_entrada,
            forma_pagamento_entrada=forma_pagamento_entrada,
            qtd_parcelas=qtd_parcelas,
            forma_pagamento_parcelas=forma_pagamento_parcelas,
            intervalo_dias=intervalo_dias
        )
        db.session.add(nova_prop)
        db.session.flush()

        servicos_ids = request.form.getlist('tipo_servico_id[]')
        valores = request.form.getlist('valor_unitario[]')
        quantidades = request.form.getlist('quantidade[]')
        unidades = request.form.getlist('unidade[]')
        descricoes = request.form.getlist('descricao[]')

        for i in range(len(servicos_ids)):
            s_id = servicos_ids[i] if i < len(servicos_ids) else None
            val = valores[i] if i < len(valores) else None
            qtd = quantidades[i] if i < len(quantidades) else '1.0'
            und = unidades[i] if i < len(unidades) else 'un'
            desc = descricoes[i] if i < len(descricoes) else ''

            if s_id and str(s_id).strip() and val and str(val).strip():
                qtd_num = float(qtd or 1.0)
                item = ItemProposta(
                    proposta_id=nova_prop.id,
                    tipo_servico_id=int(s_id),
                    quantidade=qtd_num,
                    unidade=und or 'un',
                    valor_unitario=float(val),
                    descricao_personalizada=desc
                )
                db.session.add(item)
                db.session.flush()

                tipo_serv = TipoServico.query.get(int(s_id))
                if tipo_serv and hasattr(tipo_serv, 'custos_padrao') and tipo_serv.custos_padrao:
                    for cp in tipo_serv.custos_padrao:
                        custo_analitico = ItemPropostaCusto(
                            item_proposta_id=item.id,
                            tipo_custo=cp.tipo_custo,
                            descricao=cp.descricao,
                            unidade=cp.unidade,
                            quantidade=round((cp.quantidade or 1.0) * qtd_num, 2),
                            custo_unitario=cp.custo_unitario or 0.0,
                            visivel_proposta=False
                        )
                        db.session.add(custo_analitico)

        db.session.commit()
        flash(f'Proposta {nova_prop.numero_proposta} gerada com sucesso!', 'success')
        return redirect(url_for('listar_propostas'))

    except Exception as e:
        db.session.rollback()
        print(f"\n[ERRO CRÍTICO AO GERAR PROPOSTA]: {e}\n")
        flash(f'Erro ao salvar proposta: {str(e)}', 'danger')
        return redirect(url_for('listar_propostas'))


@app.route('/propostas/<int:id>/status', methods=['POST'])
@login_required
def atualizar_status_proposta(id):
    proposta = Proposta.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    novo_status = request.form.get('novo_status')
    
    if novo_status in ['Aguardando Aprovação', 'Aprovado', 'Cancelado']:
        status_anterior = proposta.status
        proposta.status = novo_status

        if novo_status == 'Aprovado' and status_anterior != 'Aprovado':
            try:
                hoje = date.today()
                prefixo = f"Termo Aditivo #{proposta.numero_aditivo} ({proposta.numero_proposta})" if proposta.tipo_documento == 'aditivo' else f"Proposta {proposta.numero_proposta}"
                
                fatura = Fatura(
                    empresa_id=current_user.empresa_id,
                    cliente_id=proposta.cliente_id,
                    proposta_id=proposta.id,
                    descricao=f"{prefixo} ({len(proposta.itens)} itens)",
                    valor_total=float(proposta.valor_total or 0.0),
                    data_emissao=hoje
                )
                db.session.add(fatura)
                db.session.flush()

                if proposta.tipo_cobranca == 'recorrente' and proposta.tipo_documento != 'aditivo':
                    contrato = ContratoRecorrente(
                        empresa_id=current_user.empresa_id,
                        cliente_id=proposta.cliente_id,
                        tipo_servico_id=proposta.itens[0].tipo_servico_id if proposta.itens else None,
                        proposta_origem_id=proposta.id,
                        titulo=f"Contrato Mensal - {proposta.cliente.nome}",
                        valor_periodo=float(proposta.valor_total or 0.0),
                        periodicidade=proposta.periodicidade or 'mensal',
                        dia_vencimento=proposta.dia_vencimento or 10,
                        status='Ativo',
                        data_inicio=hoje,
                        observacoes=proposta.observacoes
                    )
                    db.session.add(contrato)
                    db.session.flush()
                    fatura.contrato_id = contrato.id

                exige_entrada = bool(proposta.exige_entrada and (proposta.valor_entrada or 0) > 0)
                valor_entrada = float(proposta.valor_entrada or 0.0) if exige_entrada else 0.0
                saldo_parcelar = max(0.0, float(proposta.valor_total or 0.0) - valor_entrada)
                qtd_parc = max(1, min(12, int(proposta.qtd_parcelas or 1)))
                total_titulos = (1 if exige_entrada else 0) + (qtd_parc if saldo_parcelar > 0 else 0)

                num_seq = 1

                if exige_entrada:
                    p_entrada = ParcelaFatura(
                        empresa_id=current_user.empresa_id,
                        fatura_id=fatura.id,
                        numero_parcela=num_seq,
                        total_parcelas=total_titulos,
                        descricao_parcela="Sinal / Entrada" if proposta.tipo_documento != 'aditivo' else "Entrada Aditivo",
                        is_entrada=True,
                        forma_pagamento=proposta.forma_pagamento_entrada or "PIX",
                        valor=valor_entrada,
                        data_vencimento=hoje + timedelta(days=3),
                        status="A Faturar"
                    )
                    db.session.add(p_entrada)
                    num_seq += 1

                if saldo_parcelar > 0:
                    valor_cada_parcela = round(saldo_parcelar / qtd_parc, 2)
                    intervalo = int(proposta.intervalo_dias or 30)

                    for i in range(1, qtd_parc + 1):
                        dt_venc = hoje + timedelta(days=i * intervalo)
                        p_normal = ParcelaFatura(
                            empresa_id=current_user.empresa_id,
                            fatura_id=fatura.id,
                            numero_parcela=num_seq,
                            total_parcelas=total_titulos,
                            descricao_parcela=f"Parcela {i}/{qtd_parc}",
                            is_entrada=False,
                            forma_pagamento=proposta.forma_pagamento_parcelas or "Boleto Bancário",
                            valor=valor_cada_parcela,
                            data_vencimento=dt_venc,
                            status="A Faturar"
                        )
                        db.session.add(p_normal)
                        num_seq += 1

                status_inicial_os = 'Bloqueado' if exige_entrada else ('Em Andamento' if proposta.tipo_cobranca != 'recorrente' else 'Pendente')
                dias_validade = int(proposta.validade_dias or 30)
                data_prev_os = hoje + timedelta(days=dias_validade)
                modo_os = request.form.get('modo_os', 'individual')

                destino_ficha = getattr(proposta, 'tipo_destino', 'operacional') or 'operacional'

                if modo_os == 'unificada':
                    # Cria apenas 1 Ordem de Serviço consolidando todos os itens
                    resumo_itens = "\n".join([
                        f"• {it.tipo_servico.nome if it.tipo_servico else 'Serviço'} ({it.quantidade} {it.unidade}) - {it.descricao_personalizada or ''}"
                        for it in proposta.itens
                    ])
                    primeiro_tipo_id = proposta.itens[0].tipo_servico_id if proposta.itens else None

                    nova_ordem = ServicoCliente(
                        empresa_id=current_user.empresa_id,
                        cliente_id=proposta.cliente_id,
                        tipo_servico_id=primeiro_tipo_id,
                        fatura_id=fatura.id,
                        valor_cobrado=float(proposta.valor_total or 0.0),
                        status=status_inicial_os,
                        data_solicitacao=hoje,
                        data_previsao=data_prev_os,
                        tipo_ficha=proposta.tipo_destino or 'operacional',
                        titulo_documento_custom=f"Ordem de Serviço Unificada - {proposta.numero_proposta}",
                        detalhamento_execucao=f"Escopo Integrado da Proposta:\n{resumo_itens}".strip(),
                        observacoes=f"[{proposta.numero_proposta}] Atendimento unificado englobando {len(proposta.itens)} serviço(s)."
                    )
                    nova_ordem.gerar_token_se_necessario()
                    db.session.add(nova_ordem)
                else:
                    # Modo individual: 1 Ordem de Serviço para cada item da proposta
                    for item in proposta.itens:
                        nova_ordem = ServicoCliente(
                            empresa_id=current_user.empresa_id,
                            cliente_id=proposta.cliente_id,
                            tipo_servico_id=item.tipo_servico_id,
                            fatura_id=fatura.id,
                            valor_cobrado=float(item.valor_total or 0.0),
                            status=status_inicial_os,
                            data_solicitacao=hoje,
                            data_previsao=data_prev_os,
                            tipo_ficha=destino_ficha,  # <--- FORÇA O TIPO DEFINIDO NA PROPOSTA
                            observacoes=f"[{proposta.numero_proposta}] {item.descricao_personalizada or ''}".strip()
                        )
                        nova_ordem.gerar_token_se_necessario()
                        db.session.add(nova_ordem)
                
                db.session.commit()
                flash(f'{prefixo} aprovada com sucesso! Fatura gerada no Financeiro com {total_titulos} título(s).', 'success')
                return redirect(url_for('listar_propostas'))

                # ENCAMINHAMENTO AUTOMÁTICO SEGUNDO A FINALIDADE DA PROPOSTA:
                if getattr(proposta, 'tipo_destino', 'operacional') == 'atendimento':
                    return redirect(url_for('listar_atendimentos'))
                else:
                    return redirect(url_for('consultar_servicos'))

            except Exception as e:
                db.session.rollback()
                print(f"\n[ERRO CRÍTICO AO APROVAR PROPOSTA]: {type(e).__name__} - {e}\n")
                flash(f'Erro ao aprovar proposta: {str(e)}', 'danger')
                return redirect(url_for('listar_propostas'))

        db.session.commit()
        flash(f'Status da Proposta alterado para "{novo_status}"!', 'info')
    
    return redirect(url_for('listar_propostas'))

@app.route('/propostas/<int:id>/editar', methods=['POST'])
@login_required
def editar_proposta(id):
    proposta = Proposta.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    if proposta.status == 'Aprovado':
        flash('Propostas já aprovadas que geraram faturas não podem ser editadas diretamente.', 'warning')
        return redirect(url_for('listar_propostas'))

    try:
        proposta.cliente_id = int(request.form.get('cliente_id'))
        proposta.validade_dias = int(request.form.get('validade_dias') or 15)
        proposta.condicoes_pagamento = request.form.get('condicoes_pagamento') or 'Conforme alinhamento comercial'
        proposta.observacoes = request.form.get('observacoes')
        
        proposta.tipo_cobranca = request.form.get('tipo_cobranca', 'pontual')
        proposta.periodicidade = request.form.get('periodicidade', 'mensal')
        proposta.dia_vencimento = int(request.form.get('dia_vencimento') or 10)

        proposta.exige_entrada = request.form.get('exige_entrada') in ['on', 'true']
        proposta.valor_entrada = float(request.form.get('valor_entrada') or 0.0)
        proposta.forma_pagamento_entrada = request.form.get('forma_pagamento_entrada', 'PIX')
        proposta.qtd_parcelas = int(request.form.get('qtd_parcelas') or 1)
        proposta.forma_pagamento_parcelas = request.form.get('forma_pagamento_parcelas', 'Boleto Bancário')
        proposta.intervalo_dias = int(request.form.get('intervalo_dias') or 30)

        # Remove itens anteriores e recadastra atualizados
        ItemProposta.query.filter_by(proposta_id=proposta.id).delete()
        
        servicos_ids = request.form.getlist('tipo_servico_id[]')
        valores = request.form.getlist('valor_unitario[]')
        quantidades = request.form.getlist('quantidade[]')
        unidades = request.form.getlist('unidade[]')
        descricoes = request.form.getlist('descricao[]')

        for i in range(len(servicos_ids)):
            s_id = servicos_ids[i] if i < len(servicos_ids) else None
            val = valores[i] if i < len(valores) else None
            qtd = quantidades[i] if i < len(quantidades) else '1.0'
            und = unidades[i] if i < len(unidades) else 'un'
            desc = descricoes[i] if i < len(descricoes) else ''

            if s_id and str(s_id).strip() and val and str(val).strip():
                qtd_num = float(qtd or 1.0)
                item = ItemProposta(
                    proposta_id=proposta.id,
                    tipo_servico_id=int(s_id),
                    quantidade=qtd_num,
                    unidade=und or 'un',
                    valor_unitario=float(val),
                    descricao_personalizada=desc
                )
                db.session.add(item)
                db.session.flush()

                tipo_serv = TipoServico.query.get(int(s_id))
                if tipo_serv and hasattr(tipo_serv, 'custos_padrao') and tipo_serv.custos_padrao:
                    for cp in tipo_serv.custos_padrao:
                        custo_analitico = ItemPropostaCusto(
                            item_proposta_id=item.id,
                            tipo_custo=cp.tipo_custo,
                            descricao=cp.descricao,
                            unidade=cp.unidade,
                            quantidade=round((cp.quantidade or 1.0) * qtd_num, 2),
                            custo_unitario=cp.custo_unitario or 0.0,
                            visivel_proposta=False
                        )
                        db.session.add(custo_analitico)

        db.session.commit()
        flash(f'Proposta {proposta.numero_proposta} atualizada com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao atualizar proposta: {str(e)}', 'danger')

    return redirect(url_for('listar_propostas'))

@app.route('/proposta/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_proposta(id):
    prop = Proposta.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    if prop.faturas or ContratoRecorrente.query.filter_by(proposta_origem_id=prop.id).first():
        flash('Não é possível excluir esta proposta pois ela já gerou faturas ou contratos ativos.', 'danger')
    else:
        numero = prop.numero_proposta
        db.session.delete(prop)
        db.session.commit()
        flash(f'Proposta "{numero}" excluída com sucesso!', 'info')
        
    return redirect(url_for('listar_propostas'))

@app.route('/relatorios/lucratividade')
@login_required
def relatorio_lucratividade():
    propostas_aprovadas = Proposta.query.filter_by(
        empresa_id=current_user.empresa_id, 
        status='Aprovado'
    ).order_by(Proposta.data_criacao.desc()).all()

    receita_total = sum(p.valor_total for p in propostas_aprovadas)
    custo_total = sum(p.custo_total_previsto for p in propostas_aprovadas)
    lucro_total = receita_total - custo_total
    margem_media = round((lucro_total / receita_total * 100.0), 1) if receita_total > 0 else 0.0

    custos_por_categoria = {'mao_de_obra': 0.0, 'material': 0.0, 'logistica': 0.0, 'taxa': 0.0}
    for p in propostas_aprovadas:
        for it in p.itens:
            for c in it.custos:
                cat = c.tipo_custo if c.tipo_custo in custos_por_categoria else 'taxa'
                custos_por_categoria[cat] += (c.custo_total or 0.0)

    return render_template(
        'relatorio_lucratividade.html',
        propostas=propostas_aprovadas,
        receita_total=receita_total,
        custo_total=custo_total,
        lucro_total=lucro_total,
        margem_media=margem_media,
        custos_por_categoria=custos_por_categoria
    )

# -----------------------------------------------------------------------------
# NOVO RELATÓRIO: RENTABILIDADE DE VENDAS & MERCADORIAS
# -----------------------------------------------------------------------------
@app.route('/relatorios/vendas')
@login_required
def relatorio_vendas():
    if not (current_user.empresa.modulo_estoque or current_user.empresa.modulo_vendas_externas) and current_user.nivel_acesso != 'master':
        flash('O Módulo de Vendas não está ativo no seu plano.', 'warning')
        return redirect(url_for('perfil_empresa'))

    empresa_id = current_user.empresa_id

    # Busca apenas pedidos concluídos / expedidos
    vendas_concluidas = PedidoRequisicao.query.filter_by(
        empresa_id=empresa_id
    ).filter(PedidoRequisicao.status.in_(['entregue', 'em_separacao', 'em_rota'])).order_by(
        PedidoRequisicao.data_solicitacao.desc()
    ).all()

    receita_total = sum(v.valor_total for v in vendas_concluidas)
    
    custo_total = sum(
        (item.quantidade_solicitada * (item.produto.preco_custo or 0.0))
        for v in vendas_concluidas for item in v.itens if item.produto
    )

    lucro_total = receita_total - custo_total
    margem_media = round((lucro_total / receita_total * 100.0), 1) if receita_total > 0 else 0.0

    return render_template(
        'relatorio_vendas.html',
        vendas=vendas_concluidas,
        receita_total=receita_total,
        custo_total=custo_total,
        lucro_total=lucro_total,
        margem_media=margem_media
    )

@app.route('/propostas/<int:id>/pdf')
@login_required
def gerar_pdf_proposta(id):
    proposta = Proposta.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    cliente = proposta.cliente
    empresa = current_user.empresa
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    elementos = []
    styles = getSampleStyleSheet()

    cor_primaria_hex = empresa.cor_primaria if empresa.cor_primaria and empresa.cor_primaria.startswith('#') else "#1e3a8a"
    cor_marca = colors.HexColor(cor_primaria_hex)

    estilo_empresa_nome = ParagraphStyle('PDF_EmpresaNome', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=13, leading=16, textColor=cor_marca)
    estilo_empresa_sub = ParagraphStyle('PDF_EmpresaSub', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor("#475569"))
    estilo_secao = ParagraphStyle('PDF_SecaoTit', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9.5, leading=13, textColor=cor_marca)
    estilo_corpo = ParagraphStyle('PDF_CorpoDoc', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=12, textColor=colors.HexColor("#334155"))
    estilo_corpo_bold = ParagraphStyle('PDF_CorpoBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=12, textColor=colors.HexColor("#0f172a"))
    estilo_escopo = ParagraphStyle('PDF_Escopo', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor("#64748b"))
    estilo_total = ParagraphStyle('PDF_TotalNum', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor("#16a34a"), alignment=2)

    logo_elemento = _obter_logo_reportlab(empresa.logo_filename, width=1.5*inch, height=0.6*inch)

    razao_empresa = _limpar_texto(empresa.razao_social or 'EMPRESA PRESTADORA')
    fantasia_empresa = _limpar_texto(empresa.nome_fantasia or '')
    cnpj_empresa = _limpar_texto(empresa.cnpj or 'Não informado')
    tel_empresa = _limpar_texto(empresa.telefone or 'Não informado')
    email_empresa = _limpar_texto(empresa.email or '')
    site_empresa = _limpar_texto(empresa.site or '')
    end_empresa = _limpar_texto(empresa.endereco_completo or '')

    info_empresa_html = f"""
    <b>{razao_empresa.upper()}</b><br/>
    {f"Nome Fantasia: {fantasia_empresa}<br/>" if fantasia_empresa else ""}
    CNPJ/CPF: {cnpj_empresa} | Tel: {tel_empresa}<br/>
    {f"E-mail: {email_empresa} | " if email_empresa else ""}{site_empresa}<br/>
    {end_empresa}
    """.strip()

    if logo_elemento:
        tab_topo = Table([[logo_elemento, Paragraph(info_empresa_html, estilo_empresa_sub)]], colWidths=[1.8*inch, 5.7*inch])
    else:
        tab_topo = Table([[Paragraph(f"<b>{razao_empresa.upper()}</b>", estilo_empresa_nome), Paragraph(info_empresa_html, estilo_empresa_sub)]], colWidths=[2.8*inch, 4.7*inch])

    tab_topo.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
    ]))
    elementos.append(tab_topo)
    elementos.append(Spacer(1, 6))
    elementos.append(HRFlowable(width="100%", thickness=1.5, color=cor_marca, spaceAfter=10))

    nome_cli = _limpar_texto(cliente.nome or 'Cliente')
    doc_cli = _limpar_texto(cliente.cnpj_cpf or '--')
    resp_cli = _limpar_texto(cliente.responsavel or cliente.nome or '--')
    tel_cli = _limpar_texto(cliente.telefone or '--')
    num_prop = _limpar_texto(proposta.numero_proposta or f"PROP-{proposta.id}")
    dt_emissao = proposta.data_criacao.strftime('%d/%m/%Y') if proposta.data_criacao else datetime.today().strftime('%d/%m/%Y')
    
    end_cli_fmt = _limpar_texto(
        f"{cliente.logradouro or ''}, {cliente.numero or 'S/N'} {cliente.complemento or ''} - {cliente.bairro or ''}, {cliente.cidade or ''}/{cliente.estado or ''}".strip(" ,-/")
    ) or "Endereço não informado"

    dados_painel = [
        [
            Paragraph(f"<b>PROPOSTA COMERCIAL:</b> {num_prop}", estilo_corpo_bold),
            Paragraph(f"<b>DATA DE EMISSÃO:</b> {dt_emissao}", estilo_corpo)
        ],
        [
            Paragraph(f"<b>CLIENTE:</b> {nome_cli}", estilo_corpo_bold),
            Paragraph(f"<b>VALIDADE:</b> {proposta.validade_dias or 15} dias", estilo_corpo)
        ],
        [
            Paragraph(f"<b>CNPJ / CPF:</b> {doc_cli}", estilo_corpo),
            Paragraph(f"<b>RESPONSÁVEL PELA PROPOSTA:</b> {_limpar_texto(current_user.nome)}", estilo_corpo)
        ],
        [
            Paragraph(f"<b>LOCAL / ENDEREÇO:</b> {end_cli_fmt}", estilo_corpo),
            Paragraph(f"<b>CONTATO / TEL:</b> {resp_cli} | {tel_cli}", estilo_corpo)
        ]
    ]
    tab_painel = Table(dados_painel, colWidths=[4.2*inch, 3.3*inch])
    tab_painel.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#f1f5f9")),
        ('PADDING', (0,0), (-1,-1), 4.5),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elementos.append(tab_painel)
    elementos.append(Spacer(1, 10))

    elementos.append(Paragraph("1. ESCOPO TÉCNICO & SERVIÇOS INCLUSOS", estilo_secao))
    elementos.append(Spacer(1, 4))

    dados_servicos = [
        [
            Paragraph("<b>Item / Serviço</b>", estilo_corpo_bold),
            Paragraph("<b>Detalhamento Técnico / Metodologia</b>", estilo_corpo_bold),
            Paragraph("<b>Valor (R$)</b>", estilo_corpo_bold)
        ]
    ]

    for idx, item in enumerate(proposta.itens, 1):
        nome_serv = _limpar_texto(item.tipo_servico.nome if item.tipo_servico else 'Serviço Técnico')
        qtd_und = f" ({item.quantidade} {item.unidade})" if hasattr(item, 'unidade') and item.unidade else ""
        escopo_raw = item.descricao_personalizada or (item.tipo_servico.descricao_padrao if item.tipo_servico else '') or "Conforme alinhamento técnico e comercial."
        escopo_fmt = _limpar_texto(escopo_raw)

        dados_servicos.append([
            Paragraph(f"<b>{idx:02d}. {nome_serv}{qtd_und}</b>", estilo_corpo),
            Paragraph(escopo_fmt, estilo_escopo),
            Paragraph(f"R$ {item.valor_total:,.2f}", estilo_corpo_bold)
        ])

    label_total = "VALOR DA MENSALIDADE" if proposta.tipo_cobranca == 'recorrente' else "TOTAL GLOBAL DO INVESTIMENTO"
    sufixo_mes = "/mês" if proposta.tipo_cobranca == 'recorrente' else ""

    dados_servicos.append([
        Paragraph(f"<b>{label_total}</b>", estilo_corpo_bold),
        Paragraph(f"<font color='#64748b'>Ref. {len(proposta.itens)} serviço(s) listado(s)</font>", estilo_escopo),
        Paragraph(f"R$ {proposta.valor_total:,.2f} {sufixo_mes}", estilo_total)
    ])

    tab_servicos = Table(dados_servicos, colWidths=[2.3*inch, 4.0*inch, 1.2*inch])
    tab_servicos.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (2,0), (2,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-2), 0.5, colors.HexColor("#cbd5e1")),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#f1f5f9")),
        ('LINEABOVE', (0,-1), (-1,-1), 1.2, colors.HexColor("#0f172a")),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    elementos.append(tab_servicos)
    elementos.append(Spacer(1, 10))

    elementos.append(Paragraph("2. CONDIÇÕES COMERCIAIS & FORMA DE PAGAMENTO", estilo_secao))
    elementos.append(Spacer(1, 4))

    linhas_condicoes = []

    if proposta.tipo_cobranca == 'recorrente':
        periodo_txt = _limpar_texto(proposta.periodicidade or 'mensal').capitalize()
        dia_venc_txt = proposta.dia_vencimento or 10
        linhas_condicoes.append(f"• <b>Modelo Contratual:</b> Prestação de Serviços Contínuos ({periodo_txt}).")
        linhas_condicoes.append(f"• <b>Vencimento das Mensalidades:</b> Todo dia <b>{dia_venc_txt}</b> de cada mês via Boleto Bancário.")
    else:
        if proposta.exige_entrada and (proposta.valor_entrada or 0) > 0:
            forma_ent = _limpar_texto(proposta.forma_pagamento_entrada or 'PIX')
            linhas_condicoes.append(f"• <b>Sinal de Entrada:</b> <font color='#b91c1c'><b>R$ {proposta.valor_entrada:,.2f}</b></font> ({forma_ent}) para confirmação e liberação de agenda.")
            
            saldo = max(0.0, proposta.valor_total - (proposta.valor_entrada or 0))
            if saldo > 0:
                qtd_p = max(1, proposta.qtd_parcelas or 1)
                v_p = saldo / qtd_p
                forma_parc = _limpar_texto(proposta.forma_pagamento_parcelas or 'Boleto Bancário')
                inter_dias = proposta.intervalo_dias or 30
                linhas_condicoes.append(f"• <b>Saldo Restante:</b> R$ {saldo:,.2f} parcelado em <b>{qtd_p}x de R$ {v_p:,.2f}</b> no {forma_parc} (a cada {inter_dias} dias).")
        elif (proposta.qtd_parcelas or 1) > 1:
            qtd_p = proposta.qtd_parcelas
            v_p = proposta.valor_total / qtd_p
            forma_parc = _limpar_texto(proposta.forma_pagamento_parcelas or 'Boleto Bancário')
            inter_dias = proposta.intervalo_dias or 30
            linhas_condicoes.append(f"• <b>Condição Parcelada:</b> Dividido em <b>{qtd_p}x de R$ {v_p:,.2f}</b> no {forma_parc} a cada {inter_dias} dias (Sem entrada).")
        else:
            linhas_condicoes.append("• <b>Condição de Pagamento:</b> Faturamento à Vista em parcela única.")

    if proposta.condicoes_pagamento:
        linhas_condicoes.append(f"• <b>Termos Gerais:</b> {_limpar_texto(proposta.condicoes_pagamento)}")
    if proposta.observacoes:
        linhas_condicoes.append(f"• <b>Observações Gerais:</b> {_limpar_texto(proposta.observacoes)}")

    tab_cond = Table([[Paragraph("<br/>".join(linhas_condicoes), estilo_corpo)]], colWidths=[7.5*inch])
    tab_cond.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    elementos.append(tab_cond)
    elementos.append(Spacer(1, 45))

    cargo_resp = _limpar_texto(current_user.cargo or 'Responsável pela Proposta')
    nome_usuario = _limpar_texto(current_user.nome)

    dados_assinaturas = [
        [
            Paragraph(f"____________________________________________<br/><b>{razao_empresa.upper()}</b><br/>{nome_usuario} - {cargo_resp}", estilo_corpo),
            Paragraph("____________________________________________<br/><b>DE ACORDO DO CLIENTE / CONTRATANTE</b><br/>Carimbo / Assinatura / Data", estilo_corpo)
        ]
    ]
    tab_ass = Table(dados_assinaturas, colWidths=[3.75*inch, 3.75*inch])
    tab_ass.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elementos.append(tab_ass)

    doc.build(elementos)
    buffer.seek(0)

    nome_arquivo_pdf = f"Carta_Proposta_{num_prop.replace('/', '_')}.pdf"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=nome_arquivo_pdf,
        mimetype='application/pdf'
    )

# -----------------------------------------------------------------------------
# 6. ROTAS DE OPERAÇÃO & AGENDA DE SERVIÇOS (O.S. / ATENDIMENTOS)
# -----------------------------------------------------------------------------

@app.route('/servicos')
@login_required
def consultar_servicos():
    filtro_atual = request.args.get('status', 'agenda')
    periodo_atual = request.args.get('periodo', 'todos')
    hoje = date.today()

    query_base = ServicoCliente.query.filter_by(empresa_id=current_user.empresa_id).filter(
        (ServicoCliente.tipo_ficha == 'operacional') | (ServicoCliente.tipo_ficha.is_(None))
    )

    if filtro_atual == 'agenda':
        query = query_base.filter(ServicoCliente.status.in_(['Em Andamento', 'Pendente', 'Bloqueado']))
    elif filtro_atual == 'recorrentes':
        query = query_base.filter(ServicoCliente.contrato_id.isnot(None))
    elif filtro_atual == 'avulsos':
        query = query_base.filter(ServicoCliente.contrato_id.is_(None))
    elif filtro_atual == 'concluidos':
        query = query_base.filter_by(status='Concluido')
    elif filtro_atual == 'pendentes':
        query = query_base.filter(ServicoCliente.status.in_(['Pendente', 'Bloqueado']))
    else:
        query = query_base

    if periodo_atual == 'semana':
        fim_periodo = hoje + timedelta(days=7)
        query = query.filter(ServicoCliente.data_previsao.between(hoje - timedelta(days=1), fim_periodo))
    elif periodo_atual == 'mes':
        fim_periodo = hoje + relativedelta(months=1)
        query = query.filter(ServicoCliente.data_previsao.between(hoje - timedelta(days=1), fim_periodo))
    elif periodo_atual == 'ano':
        fim_periodo = hoje + relativedelta(years=1)
        query = query.filter(ServicoCliente.data_previsao.between(hoje - timedelta(days=1), fim_periodo))

    servicos_operacionais = query.order_by(ServicoCliente.data_previsao.asc().nullslast()).all()

    qtd_em_andamento = query_base.filter_by(status='Em Andamento').count()
    qtd_pendentes = query_base.filter(ServicoCliente.status.in_(['Pendente', 'Bloqueado'])).count()
    qtd_concluidos = query_base.filter_by(status='Concluido').count()

    catalogo = TipoServico.query.filter_by(empresa_id=current_user.empresa_id).all()
    clientes = Cliente.query.filter_by(empresa_id=current_user.empresa_id).order_by(Cliente.nome).all()
    operadores = OperadorCampo.query.filter_by(empresa_id=current_user.empresa_id, ativo=True).order_by(OperadorCampo.nome).all()

    return render_template(
        'servicos.html',
        servicos_operacionais=servicos_operacionais,
        filtro_atual=filtro_atual,
        periodo_atual=periodo_atual,
        qtd_em_andamento=qtd_em_andamento,
        qtd_pendentes=qtd_pendentes,
        qtd_concluidos=qtd_concluidos,
        catalogo=catalogo,
        clientes=clientes,
        operadores=operadores,
        hoje=hoje
    )

# -----------------------------------------------------------------------------
# 6.1. NOVA ROTA DEDICADA: FICHAS DE ATENDIMENTO CLÍNICO / CONSULTAS
# -----------------------------------------------------------------------------
@app.route('/atendimentos')
@login_required
def listar_atendimentos():
    busca = request.args.get('busca', '').strip()
    filtro_status = request.args.get('status', 'todos')
    hoje = date.today()

    query = ServicoCliente.query.filter_by(
        empresa_id=current_user.empresa_id,
        tipo_ficha='atendimento'
    )

    if busca:
        doc_busca = re.sub(r'\D', '', busca)
        query = query.join(Cliente).filter(
            (Cliente.nome.ilike(f'%{busca}%')) |
            (Cliente.cnpj_cpf.ilike(f'%{busca}%')) |
            (Cliente.cnpj_cpf.ilike(f'%{doc_busca}%'))
        )

    if filtro_status == 'em_curso':
        query = query.filter(ServicoCliente.status.in_(['Em Andamento', 'Pendente']))
    elif filtro_status == 'concluidos':
        query = query.filter_by(status='Concluido')

    atendimentos = query.order_by(ServicoCliente.data_previsao.desc().nullslast(), ServicoCliente.id.desc()).all()

    total_atendimentos = query.count()
    total_concluidos = ServicoCliente.query.filter_by(empresa_id=current_user.empresa_id, tipo_ficha='atendimento', status='Concluido').count()
    total_pendentes = ServicoCliente.query.filter_by(empresa_id=current_user.empresa_id, tipo_ficha='atendimento').filter(ServicoCliente.status != 'Concluido').count()

    catalogo = TipoServico.query.filter_by(empresa_id=current_user.empresa_id).all()
    clientes = Cliente.query.filter_by(empresa_id=current_user.empresa_id).order_by(Cliente.nome).all()

    return render_template(
        'atendimentos.html',
        atendimentos=atendimentos,
        busca=busca,
        filtro_status=filtro_status,
        total_atendimentos=total_atendimentos,
        total_concluidos=total_concluidos,
        total_pendentes=total_pendentes,
        catalogo=catalogo,
        clientes=clientes,
        hoje=hoje
    )

@app.route('/catalogo', methods=['GET'])
@login_required
def listar_catalogo():
    catalogo = TipoServico.query.filter_by(empresa_id=current_user.empresa_id).all()
    return render_template('catalogo.html', catalogo=catalogo)

@app.route('/catalogo/novo', methods=['POST'])
@login_required
def novo_tipo_servico():
    nome = request.form.get('nome')
    modelo_cobranca = request.form.get('modelo_cobranca', 'pontual')
    unidade_medida = request.form.get('unidade_medida', 'un')
    margem_lucro_alvo = float(request.form.get('margem_lucro_alvo') or 30.0)
    valor_sugerido = float(request.form.get('valor_sugerido') or 0.0)
    descricao = request.form.get('descricao')

    novo_item = TipoServico(
        empresa_id=current_user.empresa_id,
        nome=nome,
        modelo_cobranca=modelo_cobranca,
        unidade_medida=unidade_medida,
        margem_lucro_alvo=margem_lucro_alvo,
        valor_sugerido=valor_sugerido,
        descricao_padrao=descricao
    )
    db.session.add(novo_item)
    db.session.flush()

    tipos_custo = request.form.getlist('custo_tipo[]')
    descricoes_custo = request.form.getlist('custo_desc[]')
    quantidades_custo = request.form.getlist('custo_qtd[]')
    valores_custo = request.form.getlist('custo_unit[]')

    for t, d, q, v in zip(tipos_custo, descricoes_custo, quantidades_custo, valores_custo):
        if d and v:
            c = ServicoCustoPadrao(
                tipo_servico_id=novo_item.id,
                tipo_custo=t,
                descricao=d,
                quantidade=float(q or 1.0),
                custo_unitario=float(v or 0.0)
            )
            db.session.add(c)

    db.session.commit()
    flash(f'Serviço "{nome}" cadastrado com sucesso no catálogo!', 'success')
    return redirect(url_for('listar_catalogo'))

@app.route('/catalogo/editar/<int:id>', methods=['POST'])
@login_required
def editar_tipo_servico(id):
    item = TipoServico.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    item.nome = request.form.get('nome', item.nome).strip()
    item.modelo_cobranca = request.form.get('modelo_cobranca', item.modelo_cobranca)
    item.unidade_medida = request.form.get('unidade_medida', item.unidade_medida).strip()
    item.margem_lucro_alvo = float(request.form.get('margem_lucro_alvo') or 30.0)
    item.valor_sugerido = float(request.form.get('valor_sugerido') or 0.0)
    item.descricao_padrao = request.form.get('descricao', '').strip()

    ServicoCustoPadrao.query.filter_by(tipo_servico_id=item.id).delete()

    tipos_custo = request.form.getlist('custo_tipo[]')
    descricoes_custo = request.form.getlist('custo_desc[]')
    quantidades_custo = request.form.getlist('custo_qtd[]')
    valores_custo = request.form.getlist('custo_unit[]')

    for t, d, q, v in zip(tipos_custo, descricoes_custo, quantidades_custo, valores_custo):
        if d and v:
            c = ServicoCustoPadrao(
                tipo_servico_id=item.id,
                tipo_custo=t,
                descricao=d,
                quantidade=float(q or 1.0),
                custo_unitario=float(v or 0.0)
            )
            db.session.add(c)

    db.session.commit()
    flash(f'Serviço "{item.nome}" atualizado com sucesso!', 'success')
    return redirect(url_for('listar_catalogo'))

@app.route('/catalogo/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_tipo_servico(id):
    item = TipoServico.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    vinculo_prop = ItemProposta.query.filter_by(tipo_servico_id=item.id).first()
    if item.execucoes or vinculo_prop:
        flash('Não é possível excluir este item pois ele já está vinculado a propostas ou ordens de serviço.', 'danger')
        return redirect(url_for('listar_catalogo'))

    db.session.delete(item)
    db.session.commit()
    flash(f'Serviço "{item.nome}" removido do catálogo com sucesso.', 'info')
    return redirect(url_for('listar_catalogo'))

@app.route('/servicos/definir-responsavel/<int:id>', methods=['POST'])
@login_required
def definir_responsavel_servico(id):
    servico = ServicoCliente.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    servico.responsavel_tecnico = request.form.get('responsavel_tecnico', '').strip()
    db.session.commit()
    flash('Responsável pelo atendimento atualizado!', 'success')
    return redirect(url_for('consultar_servicos'))

@app.route('/servicos/atualizar-operacao/<int:id>', methods=['POST'])
@login_required
def atualizar_operacao_servico(id):
    servico = ServicoCliente.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    if servico.status == 'Bloqueado' and request.form.get('status') != 'Bloqueado':
        flash('Esta atividade está bloqueada pelo Financeiro aguardando o pagamento do sinal.', 'danger')
        return redirect(url_for('consultar_servicos', status=request.form.get('filtro_retorno', 'agenda')))

    novo_status = request.form.get('status', servico.status)
    data_prev_str = request.form.get('data_previsao')
    hora_ini_str = request.form.get('hora_inicio_agendada')
    hora_fim_str = request.form.get('hora_fim_agendada')
    
    servico.status = novo_status
    if data_prev_str:
        servico.data_previsao = datetime.strptime(data_prev_str, '%Y-%m-%d').date()

    # Atualiza horários gerais da OS
    servico.hora_inicio_agendada = datetime.strptime(hora_ini_str, '%H:%M').time() if hora_ini_str else None
    servico.hora_fim_agendada = datetime.strptime(hora_fim_str, '%H:%M').time() if hora_fim_str else None
        
    operador_id = request.form.get('operador_id')
    if operador_id and operador_id.isdigit():
        servico.operador_id = int(operador_id)
        op_obj = OperadorCampo.query.get(int(operador_id))
        if op_obj:
            servico.responsavel_tecnico = op_obj.nome
            servico.documento_responsavel = op_obj.documento_registro
    elif operador_id == '':
        servico.operador_id = None
        servico.responsavel_tecnico = request.form.get('responsavel_tecnico', '').strip()
        servico.documento_responsavel = request.form.get('documento_responsavel', '').strip()

    servico.titulo_documento_custom = request.form.get('titulo_documento_custom', 'Ordem de Serviço').strip()
    servico.detalhamento_execucao = request.form.get('detalhamento_execucao')
    servico.orientacoes_cliente = request.form.get('orientacoes_cliente')
    servico.observacoes = request.form.get('observacoes')

    usar_end_custom = bool(request.form.get('usar_endereco_personalizado'))
    servico.usar_endereco_personalizado = usar_end_custom

    if usar_end_custom:
        servico.cep_execucao = re.sub(r'\D', '', request.form.get('cep_execucao', ''))
        servico.logradouro_execucao = request.form.get('logradouro_execucao', '').strip()
        servico.numero_execucao = request.form.get('numero_execucao', '').strip()
        servico.complemento_execucao = request.form.get('complemento_execucao', '').strip()
        servico.bairro_execucao = request.form.get('bairro_execucao', '').strip()
        servico.cidade_execucao = request.form.get('cidade_execucao', '').strip()
        servico.estado_execucao = request.form.get('estado_execucao', '').strip().upper()
        
        servico.endereco_execucao_completo = f"{servico.logradouro_execucao or ''}, {servico.numero_execucao or 'S/N'} {servico.complemento_execucao or ''} - {servico.bairro_execucao or ''}, {servico.cidade_execucao or ''}/{servico.estado_execucao or ''}".strip(" ,-/")
    else:
        servico.cep_execucao = None
        servico.logradouro_execucao = None
        servico.numero_execucao = None
        servico.complemento_execucao = None
        servico.bairro_execucao = None
        servico.cidade_execucao = None
        servico.estado_execucao = None
        servico.endereco_execucao_completo = None

    # Upload Múltiplo de Fotos / Evidências para o Supabase
    arquivos_evidencia = request.files.getlist('arquivos_evidencia[]')
    for arq in arquivos_evidencia:
        if arq and arq.filename:
            try:
                chave_evidencia = salvar_arquivo_supabase(
                    file_storage=arq,
                    pasta_destino='ordens_servico',
                    empresa_id=current_user.empresa_id
                )
                nova_evidencia = EvidenciaServico(
                    servico_cliente_id=servico.id,
                    chave_bucket=chave_evidencia,
                    nome_original=secure_filename(arq.filename)
                )
                db.session.add(nova_evidencia)
            except ValueError as err:
                flash(f"Aviso no arquivo {arq.filename}: {str(err)}", 'warning')
            except Exception as e:
                flash(f"Erro ao enviar {arq.filename}: {str(e)}", 'danger')

    # Atualização dinâmica de Etapas / Cronograma (Gantt) com Operador e Horários
    titulos_fase = request.form.getlist('etapa_titulo[]')
    inicios_fase = request.form.getlist('etapa_inicio[]')
    fins_fase = request.form.getlist('etapa_fim[]')
    horas_ini_fase = request.form.getlist('etapa_hora_inicio[]')
    horas_fim_fase = request.form.getlist('etapa_hora_fim[]')
    operadores_fase = request.form.getlist('etapa_operador_id[]')
    status_fase = request.form.getlist('etapa_status[]')

    if titulos_fase:
        ServicoEtapaRastreio.query.filter_by(servico_cliente_id=servico.id).delete()
        for idx, t in enumerate(titulos_fase):
            if t.strip():
                d_ini = datetime.strptime(inicios_fase[idx], '%Y-%m-%d').date() if idx < len(inicios_fase) and inicios_fase[idx] else None
                d_fim = datetime.strptime(fins_fase[idx], '%Y-%m-%d').date() if idx < len(fins_fase) and fins_fase[idx] else None
                h_ini = datetime.strptime(horas_ini_fase[idx], '%H:%M').time() if idx < len(horas_ini_fase) and horas_ini_fase[idx] else None
                h_fim = datetime.strptime(horas_fim_fase[idx], '%H:%M').time() if idx < len(horas_fim_fase) and horas_fim_fase[idx] else None
                
                op_fase_id = operadores_fase[idx] if idx < len(operadores_fase) else None
                op_val = int(op_fase_id) if op_fase_id and op_fase_id.isdigit() else None
                st = status_fase[idx] if idx < len(status_fase) else 'pendente'

                nova_etapa = ServicoEtapaRastreio(
                    servico_cliente_id=servico.id,
                    titulo_fase=t.strip(),
                    data_inicio=d_ini,
                    data_fim=d_fim,
                    hora_inicio=h_ini,
                    hora_fim=h_fim,
                    operador_id=op_val,
                    status_fase=st,
                    ordem=idx + 1
                )
                nova_etapa.gerar_token_se_necessario()
                db.session.add(nova_etapa)

    db.session.commit()
    flash('Operação, horários, operadores e etapas atualizados com sucesso!', 'success')
    return redirect(url_for('consultar_servicos', status=request.form.get('filtro_retorno', 'agenda')))

@app.route('/servicos/<int:id>/pdf', methods=['GET', 'POST'])
@login_required

def gerar_pdf_ordem_servico(id):
    servico = ServicoCliente.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    cliente = servico.cliente
    empresa = current_user.empresa
    buffer = io.BytesIO()

    exibir_doc_cliente = request.form.get('exibir_doc_cliente') == '1' if request.method == 'POST' else True
    exibir_datas = request.form.get('exibir_datas') == '1' if request.method == 'POST' else True
    exibir_endereco = request.form.get('exibir_endereco') == '1' if request.method == 'POST' else True
    exibir_responsavel = request.form.get('exibir_responsavel') == '1' if request.method == 'POST' else True
    exibir_descricao = request.form.get('exibir_descricao') == '1' if request.method == 'POST' else True
    exibir_detalhamento = request.form.get('exibir_detalhamento') == '1' if request.method == 'POST' else True
    exibir_orientacoes = request.form.get('exibir_orientacoes') == '1' if request.method == 'POST' else True
    exibir_assinaturas = request.form.get('exibir_assinaturas') == '1' if request.method == 'POST' else True

    doc = SimpleDocTemplate(
        buffer, 
        pagesize=letter, 
        rightMargin=36, 
        leftMargin=36, 
        topMargin=36, 
        bottomMargin=36
    )
    elementos = []
    styles = getSampleStyleSheet()

    cor_primaria_hex = empresa.cor_primaria if empresa.cor_primaria and empresa.cor_primaria.startswith('#') else "#1e3a8a"
    cor_marca = colors.HexColor(cor_primaria_hex)

    estilo_empresa_nome = ParagraphStyle('PDF_EmpNome', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=cor_marca)
    estilo_sub = ParagraphStyle('PDF_Sub', parent=styles['Normal'], fontName='Helvetica', fontSize=7.5, leading=10, textColor=colors.HexColor("#475569"), alignment=2)
    estilo_secao = ParagraphStyle('PDF_Sec', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9.5, leading=13, textColor=cor_marca)
    estilo_corpo = ParagraphStyle('PDF_Corpo', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=12, textColor=colors.HexColor("#1e293b"))
    estilo_corpo_bold = ParagraphStyle('PDF_CorpoB', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=12, textColor=colors.HexColor("#0f172a"))

    logo_elemento = _obter_logo_reportlab(empresa.logo_filename, width=1.5*inch, height=0.6*inch)

    info_emp = f"<b>{_limpar_texto(empresa.razao_social).upper()}</b><br/>CNPJ: {_limpar_texto(empresa.cnpj or '--')} | Tel: {_limpar_texto(empresa.telefone or '--')}<br/>{_limpar_texto(empresa.endereco_completo or '')}"
    if logo_elemento:
        tab_topo = Table([[logo_elemento, Paragraph(info_emp, estilo_sub)]], colWidths=[1.8*inch, 5.7*inch])
    else:
        tab_topo = Table([[Paragraph(f"<b>{_limpar_texto(empresa.razao_social).upper()}</b>", estilo_empresa_nome), Paragraph(info_emp, estilo_sub)]], colWidths=[2.8*inch, 4.7*inch])

    tab_topo.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (1,0), (1,0), 'RIGHT')]))
    elementos.append(tab_topo)
    elementos.append(Spacer(1, 4))
    elementos.append(HRFlowable(width="100%", thickness=1.5, color=cor_marca, spaceAfter=10))

    tit_doc = _limpar_texto(servico.titulo_documento_custom or 'ORDEM DE SERVIÇO').upper()
    elementos.append(Paragraph(f"<b>{tit_doc} Nº OS-{servico.numero_sequencial_empresa:04d}</b>", estilo_secao))
    elementos.append(Spacer(1, 4))

    dados_os = []
    col_dir_1 = Paragraph(f"<b>SOLICITAÇÃO:</b> {servico.data_solicitacao.strftime('%d/%m/%Y') if servico.data_solicitacao else '--'}", estilo_corpo) if exibir_datas else Paragraph("", estilo_corpo)
    dados_os.append([Paragraph(f"<b>CLIENTE:</b> {_limpar_texto(cliente.nome)}", estilo_corpo_bold), col_dir_1])

    col_esq_2 = Paragraph(f"<b>CNPJ/CPF:</b> {_limpar_texto(cliente.cnpj_cpf or '--')}", estilo_corpo) if exibir_doc_cliente else Paragraph("", estilo_corpo)
    col_dir_2 = Paragraph(f"<b>PREVISÃO:</b> {servico.data_previsao.strftime('%d/%m/%Y') if servico.data_previsao else '--'}", estilo_corpo) if exibir_datas else Paragraph("", estilo_corpo)
    if exibir_doc_cliente or exibir_datas:
        dados_os.append([col_esq_2, col_dir_2])

    if exibir_responsavel:
        resp_nome = _limpar_texto(servico.responsavel_tecnico or 'Não informado')
        doc_resp = f" (Doc/Registro: {_limpar_texto(servico.documento_responsavel)})" if servico.documento_responsavel else ""
        dados_os.append([
            Paragraph(f"<b>RESPONSÁVEL PELO ATENDIMENTO:</b> <font color='{cor_primaria_hex}'><b>{resp_nome}{doc_resp}</b></font>", estilo_corpo_bold),
            Paragraph("", estilo_corpo)
        ])

    tab_dados = Table(dados_os, colWidths=[4.5*inch, 3.0*inch])
    tab_dados.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")), 
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")), 
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#f1f5f9")), 
        ('PADDING', (0,0), (-1,-1), 4.5)
    ]))
    elementos.append(tab_dados)
    elementos.append(Spacer(1, 10))

    elementos.append(Paragraph("1. ATIVIDADE & DETALHAMENTO DO ATENDIMENTO", estilo_secao))
    elementos.append(Spacer(1, 4))
    
    nome_serv = _limpar_texto(servico.tipo_servico.nome if servico.tipo_servico else 'Atendimento Técnico')
    detalhes_blocos = [f"<b>Serviço:</b> {nome_serv}"]

    if exibir_descricao and servico.observacoes:
        obs_fmt = _limpar_texto(servico.observacoes).replace('\n', '<br/>')
        detalhes_blocos.append(f"<b>Descrição do Atendimento:</b><br/>{obs_fmt}")

    if exibir_detalhamento and servico.detalhamento_execucao:
        det_fmt = _limpar_texto(servico.detalhamento_execucao).replace('\n', '<br/>')
        detalhes_blocos.append(f"<b>Detalhamento da Execução:</b><br/>{det_fmt}")

    if exibir_orientacoes and servico.orientacoes_cliente:
        ori_fmt = _limpar_texto(servico.orientacoes_cliente).replace('\n', '<br/>')
        detalhes_blocos.append(f"<b>Orientações / Recomendações:</b><br/>{ori_fmt}")

    if exibir_endereco:
        end_texto = _limpar_texto(servico.endereco_exibicao)
        detalhes_blocos.append(f"<b>Endereço do Atendimento:</b><br/>{end_texto}")

    corpo_texto_html = "<br/><br/>".join(detalhes_blocos)
    tab_det = Table([[Paragraph(corpo_texto_html, estilo_corpo)]], colWidths=[7.5*inch])
    tab_det.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#ffffff")), 
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")), 
        ('PADDING', (0,0), (-1,-1), 6)
    ]))
    elementos.append(tab_det)

    if exibir_assinaturas:
        elementos.append(Spacer(1, 45))
        resp_assinatura = _limpar_texto(servico.responsavel_tecnico or 'Responsável pelo Atendimento')
        doc_resp_ass = f"<br/><font size='7.5' color='#64748b'>Reg/Doc: {_limpar_texto(servico.documento_responsavel)}</font>" if servico.documento_responsavel else ""
        assinaturas = [
            [
                Paragraph(f"____________________________________________<br/><b>{resp_assinatura}</b>{doc_resp_ass}<br/>Responsável pelo Atendimento", estilo_corpo),
                Paragraph(f"____________________________________________<br/><b>{_limpar_texto(cliente.nome).upper()}</b><br/>Aceite do Cliente / Declaração de Execução", estilo_corpo)
            ]
        ]
        tab_ass = Table(assinaturas, colWidths=[3.75*inch, 3.75*inch])
        tab_ass.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'), 
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE')
        ]))
        elementos.append(tab_ass)

    doc.build(elementos)
    buffer.seek(0)
    nome_pdf = f"{tit_doc.replace(' ', '_')}_OS_{servico.numero_sequencial_empresa:04d}.pdf"
    return send_file(
        buffer, 
        as_attachment=True, 
        download_name=nome_pdf, 
        mimetype='application/pdf'
    )

@app.route('/servicos/evidencia/<int:evidencia_id>/excluir', methods=['POST'])
@login_required
def excluir_evidencia_servico(evidencia_id):
    evidencia = EvidenciaServico.query.join(ServicoCliente).filter(
        EvidenciaServico.id == evidencia_id,
        ServicoCliente.empresa_id == current_user.empresa_id
    ).first_or_404()
    
    servico_id = evidencia.servico_cliente_id
    if evidencia.chave_bucket:
        excluir_arquivo_supabase(evidencia.chave_bucket)
        
    db.session.delete(evidencia)
    db.session.commit()
    flash('Evidência removida com sucesso!', 'info')
    return redirect(url_for('consultar_servicos'))

@app.route('/servicos/<int:id>/visualizar')
@login_required
def visualizar_ficha_servico(id):
    servico = ServicoCliente.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    return render_template('detalhe_servico.html', servico=servico, hoje=date.today())

@app.route('/servicos/atendimento/<int:id>/salvar', methods=['POST'])
@login_required
def salvar_evolucao_atendimento(id):
    servico = ServicoCliente.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    try:
        servico.responsavel_tecnico = request.form.get('responsavel_tecnico', '').strip()
        servico.documento_responsavel = request.form.get('documento_responsavel', '').strip()
        
        servico.observacoes = request.form.get('motivo_queixa', '').strip() # Queixa principal
        servico.anamnese_historico = request.form.get('anamnese_historico', '').strip() # Relato da sessão
        servico.conclusao_parecer = request.form.get('conclusao_parecer', '').strip() # Parecer / Diagnóstico
        servico.orientacoes_cliente = request.form.get('orientacoes_cliente', '').strip() # Conduta / Plano de ação
        
        num_sessao = request.form.get('numero_sessao')
        if num_sessao and num_sessao.isdigit():
            servico.numero_sessao = int(num_sessao)

        dt_prev = request.form.get('data_previsao')
        if dt_prev:
            servico.data_previsao = datetime.strptime(dt_prev, '%Y-%m-%d').date()

        novo_status = request.form.get('status', servico.status)
        servico.status = novo_status
        if novo_status == 'Concluido' and not servico.data_fim_execucao:
            servico.data_fim_execucao = datetime.now()

        # Upload de exames, bioimpedância ou avaliações em anexo
        anexos = request.files.getlist('anexos_atendimento[]')
        for arq in anexos:
            if arq and arq.filename:
                chave = salvar_arquivo_supabase(arq, 'prontuarios', current_user.empresa_id)
                nova_ev = EvidenciaServico(
                    servico_cliente_id=servico.id,
                    chave_bucket=chave,
                    nome_original=secure_filename(arq.filename)
                )
                db.session.add(nova_ev)

        db.session.commit()
        flash(f'Atendimento do paciente "{servico.cliente.nome}" atualizado com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao salvar evolução: {str(e)}', 'danger')

    return redirect(url_for('consultar_servicos', tipo='atendimentos'))

# -----------------------------------------------------------------------------
# 6.1. NOVA ATIVIDADE / OS AVULSA INDEPENDENTE (SEM PROPOSTA)
# -----------------------------------------------------------------------------
@app.route('/servicos/novo-avulso', methods=['POST'])
@login_required
def criar_servico_avulso():
    try:
        cliente_id = int(request.form.get('cliente_id'))
        tipo_servico_id = int(request.form.get('tipo_servico_id'))
        operador_id = request.form.get('operador_id')
        valor = float(request.form.get('valor_cobrado') or 0.0)
        dt_prev = request.form.get('data_previsao')
        hora_ini = request.form.get('hora_inicio_agendada')
        hora_fim = request.form.get('hora_fim_agendada')
        
        titulo_doc = request.form.get('titulo_documento_custom', 'Ordem de Serviço').strip()
        tipo_ficha = request.form.get('tipo_ficha', 'operacional')
        observacoes = request.form.get('observacoes', '').strip()
        detalhamento = request.form.get('detalhamento_execucao', '').strip()
        gerar_fatura = bool(request.form.get('gerar_fatura'))

        hoje = date.today()
        fatura_id = None

        if gerar_fatura and valor > 0:
            cli = Cliente.query.get(cliente_id)
            nova_fat = Fatura(
                empresa_id=current_user.empresa_id,
                cliente_id=cliente_id,
                descricao=f"Atendimento Avulso - {cli.nome if cli else 'Cliente'}",
                valor_total=valor,
                data_emissao=hoje
            )
            db.session.add(nova_fat)
            db.session.flush()

            parc = ParcelaFatura(
                empresa_id=current_user.empresa_id,
                fatura_id=nova_fat.id,
                numero_parcela=1,
                total_parcelas=1,
                descricao_parcela="Parcela Única",
                forma_pagamento=request.form.get('forma_pagamento', 'Boleto Bancário'),
                valor=valor,
                data_vencimento=datetime.strptime(dt_prev, '%Y-%m-%d').date() if dt_prev else (hoje + timedelta(days=15)),
                status="A Faturar"
            )
            db.session.add(parc)
            fatura_id = nova_fat.id

        nova_os = ServicoCliente(
            empresa_id=current_user.empresa_id,
            cliente_id=cliente_id,
            tipo_servico_id=tipo_servico_id,
            operador_id=int(operador_id) if operador_id and operador_id.isdigit() else None,
            fatura_id=fatura_id,
            valor_cobrado=valor,
            status='Em Andamento',
            data_solicitacao=hoje,
            data_previsao=datetime.strptime(dt_prev, '%Y-%m-%d').date() if dt_prev else hoje,
            hora_inicio_agendada=datetime.strptime(hora_ini, '%H:%M').time() if hora_ini else None,
            hora_fim_agendada=datetime.strptime(hora_fim, '%H:%M').time() if hora_fim else None,
            titulo_documento_custom=titulo_doc,
            tipo_ficha=tipo_ficha,
            detalhamento_execucao=detalhamento,
            observacoes=observacoes or "Atividade avulsa gerada diretamente pelo gestor."
        )
        nova_os.gerar_token_se_necessario()
        db.session.add(nova_os)
        db.session.commit()

        flash(f'Ordem de Serviço OS-{nova_os.numero_sequencial_empresa:04d} aberta com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao cadastrar serviço avulso: {str(e)}', 'danger')

    return redirect(url_for('consultar_servicos'))

# -----------------------------------------------------------------------------
# 6.2. MÓDULO DE GESTÃO DE OPERADORES & TÉCNICOS DE CAMPO
# -----------------------------------------------------------------------------
@app.route('/operadores', methods=['GET', 'POST'])
@login_required
def gestao_operadores():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        cargo = request.form.get('cargo', 'Técnico de Campo').strip()
        telefone = re.sub(r'\D', '', request.form.get('telefone', ''))
        doc_registro = request.form.get('documento_registro', '').strip()
        email = request.form.get('email', '').strip().lower()
        cli_alocado_id = request.form.get('cliente_id')

        if not nome or not telefone:
            flash('Nome e WhatsApp do operador são obrigatórios.', 'warning')
            return redirect(url_for('gestao_operadores'))

        novo_op = OperadorCampo(
            empresa_id=current_user.empresa_id,
            cliente_id=int(cli_alocado_id) if cli_alocado_id and cli_alocado_id.isdigit() else None,
            nome=nome,
            cargo=cargo,
            telefone=telefone,
            documento_registro=doc_registro,
            email=email or None
        )
        db.session.add(novo_op)
        db.session.commit()
        flash(f'Operador "{nome}" cadastrado com sucesso!', 'success')
        return redirect(url_for('gestao_operadores'))

    operadores = OperadorCampo.query.filter_by(empresa_id=current_user.empresa_id).order_by(OperadorCampo.nome.asc()).all()
    clientes = Cliente.query.filter_by(empresa_id=current_user.empresa_id).order_by(Cliente.nome.asc()).all()
    
    # -------------------------------------------------------------------------
    # CONSOLIDAÇÃO DA ESCALA: ORDENS GERAIS + FASES ESPECÍFICAS DO GANTT
    # -------------------------------------------------------------------------
    hoje = date.today()
    itens_escala = []

    # 1. OS Gerais com Operador Vinculado
    ordens_gerais = ServicoCliente.query.filter(
        ServicoCliente.empresa_id == current_user.empresa_id,
        ServicoCliente.operador_id.isnot(None)
    ).all()

    for os_item in ordens_gerais:
        itens_escala.append({
            'servico_id': os_item.id,
            'numero_os': os_item.numero_sequencial_empresa,
            'data': os_item.data_previsao or os_item.data_solicitacao,
            'hora_inicio': os_item.hora_inicio_agendada,
            'hora_fim': os_item.hora_fim_agendada,
            'operador_nome': os_item.operador_responsavel.nome if os_item.operador_responsavel else '--',
            'operador_telefone': os_item.operador_responsavel.telefone if os_item.operador_responsavel else '',
            'cliente_nome': os_item.cliente.nome,
            'endereco': os_item.endereco_exibicao,
            'servico_nome': os_item.tipo_servico.nome if os_item.tipo_servico else 'Serviço Técnico',
            'descricao_atividade': os_item.titulo_documento_custom or 'Execução Geral da OS',
            'is_etapa': False,
            'token_externo': os_item.token_externo,
            'status': os_item.status
        })

    # 2. Etapas / Fases do Cronograma (Gantt) com Operador Designado
    etapas_gantt = ServicoEtapaRastreio.query.join(ServicoCliente).filter(
        ServicoCliente.empresa_id == current_user.empresa_id,
        ServicoEtapaRastreio.operador_id.isnot(None)
    ).all()

    for et in etapas_gantt:
        os_pai = et.servico
        token_link = et.gerar_token_se_necessario()
        db.session.commit()
        
        # APPEND DA FASE DO GANTT NA ESCALA (O QUE ESTAVA FALTANDO)
        itens_escala.append({
            'servico_id': os_pai.id,
            'etapa_id': et.id,
            'numero_os': os_pai.numero_sequencial_empresa,
            'data': et.data_inicio or os_pai.data_previsao,
            'hora_inicio': et.hora_inicio,
            'hora_fim': et.hora_fim,
            'operador_nome': et.operador.nome if et.operador else '--',
            'operador_telefone': et.operador.telefone if et.operador else '',
            'cliente_nome': os_pai.cliente.nome,
            'endereco': os_pai.endereco_exibicao,
            'servico_nome': os_pai.tipo_servico.nome if os_pai.tipo_servico else 'Serviço Técnico',
            'descricao_atividade': f"Fase #{et.ordem}: {et.titulo_fase}",
            'is_etapa': True,
            'token_externo': et.token_externo,
            'status': 'Concluido' if et.status_fase == 'concluido' else ('Em Andamento' if et.status_fase == 'em_andamento' else 'Pendente')
        })
        
    # Ordena a escala unificada por data e hora de início
    itens_escala.sort(key=lambda x: (x['data'] or date.min, x['hora_inicio'] or time.min))

    return render_template(
        'operadores.html',
        operadores=operadores,
        clientes=clientes,
        ordens_agendadas=itens_escala,  # Passa a lista consolidada
        hoje=hoje
    )

@app.route('/operadores/<int:id>/status', methods=['POST'])
@login_required
def alternar_status_operador(id):
    op = OperadorCampo.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    op.ativo = not op.ativo
    db.session.commit()
    flash(f'Status de "{op.nome}" atualizado!', 'info')
    return redirect(url_for('gestao_operadores'))

@app.route('/operadores/<int:id>/excluir', methods=['POST'])
@login_required
def excluir_operador(id):
    op = OperadorCampo.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    db.session.delete(op)
    db.session.commit()
    flash('Operador removido da equipe.', 'info')
    return redirect(url_for('gestao_operadores'))

# -----------------------------------------------------------------------------
# 6.3. FORMULÁRIO EXTERNO MOBILE DO OPERADOR (SEM LOGIN)
# -----------------------------------------------------------------------------
@app.route('/os/execucao/<token>', methods=['GET', 'POST'])
def os_formulario_externo(token):
    servico = ServicoCliente.query.filter_by(token_externo=token).first_or_404()
    empresa = servico.empresa

    if request.method == 'POST':
        try:
            servico.relatorio_operador = request.form.get('relatorio_operador', '').strip()
            servico.nome_quem_assinou = request.form.get('nome_quem_assinou', '').strip()
            servico.documento_quem_assinou = request.form.get('documento_quem_assinou', '').strip()
            servico.assinatura_cliente_base64 = request.form.get('assinatura_base64')
            
            # Se for Ficha de Atendimento
            if servico.tipo_ficha == 'atendimento':
                servico.anamnese_historico = request.form.get('anamnese_historico', '').strip()
                servico.conclusao_parecer = request.form.get('conclusao_parecer', '').strip()

            servico.data_fim_execucao = datetime.now()
            if not servico.data_inicio_execucao:
                servico.data_inicio_execucao = servico.data_fim_execucao - timedelta(hours=1)

            # Upload de fotos tiradas no smartphone
            fotos = request.files.getlist('fotos_campo[]')
            for f in fotos:
                if f and f.filename:
                    chave = salvar_arquivo_supabase(f, 'ordens_servico', empresa.id)
                    evidencia = EvidenciaServico(
                        servico_cliente_id=servico.id,
                        chave_bucket=chave,
                        nome_original=secure_filename(f.filename)
                    )
                    db.session.add(evidencia)

            servico.status = 'Concluido'
            db.session.commit()
            return render_template('publico/os_concluida.html', servico=servico, empresa=empresa)
        except Exception as e:
            db.session.rollback()
            return f"Erro ao processar envio da Ordem de Serviço: {str(e)}", 500

    return render_template('publico/os_externa.html', servico=servico, empresa=empresa)

@app.route('/etapa/execucao/<token>', methods=['GET', 'POST'])
def etapa_formulario_externo(token):
    etapa = ServicoEtapaRastreio.query.filter_by(token_externo=token).first_or_404()
    servico = etapa.servico
    empresa = servico.empresa

    if request.method == 'POST':
        try:
            etapa.relatorio_fase = request.form.get('relatorio_fase', '').strip()
            etapa.nome_quem_assinou = request.form.get('nome_quem_assinou', '').strip()
            etapa.documento_quem_assinou = request.form.get('documento_quem_assinou', '').strip()
            etapa.assinatura_base64 = request.form.get('assinatura_base64')
            etapa.status_fase = 'concluido'
            etapa.data_conclusao = datetime.now()

            # Upload das fotos tiradas pelo técnico no celular
            fotos = request.files.getlist('fotos_campo[]')
            for f in fotos:
                if f and f.filename:
                    chave = salvar_arquivo_supabase(f, 'ordens_servico', empresa.id)
                    evidencia = EvidenciaServico(
                        servico_cliente_id=servico.id,
                        etapa_rastreio_id=etapa.id,
                        chave_bucket=chave,
                        nome_original=secure_filename(f.filename)
                    )
                    db.session.add(evidencia)

            # Verifica se todas as etapas do serviço foram concluídas para atualizar o status geral
            todas_etapas = servico.etapas_rastreio
            if todas_etapas and all(e.status_fase == 'concluido' for e in todas_etapas):
                servico.status = 'Concluido'
                if not servico.data_fim_execucao:
                    servico.data_fim_execucao = datetime.now()

            db.session.commit()
            return render_template('publico/etapa_concluida.html', etapa=etapa, servico=servico, empresa=empresa)
        except Exception as e:
            db.session.rollback()
            return f"Erro ao processar envio da Etapa: {str(e)}", 500

    return render_template('publico/etapa_externa.html', etapa=etapa, servico=servico, empresa=empresa)

# -----------------------------------------------------------------------------
# 7. ROTAS DO MÓDULO FINANCEIRO
# -----------------------------------------------------------------------------

@app.route('/financeiro')
@login_required
def financeiro():
    filtro_atual = request.args.get('status', 'todos')
    hoje = date.today()

    query_faturas = Fatura.query.filter_by(empresa_id=current_user.empresa_id)
    todas_faturas = query_faturas.all()

    todas_parcelas = ParcelaFatura.query.filter_by(empresa_id=current_user.empresa_id).all()
    total_a_faturar = sum(p.valor for p in todas_parcelas if p.status == 'A Faturar')
    total_aguardando = sum(p.valor for p in todas_parcelas if p.status == 'Boleto Emitido' and (not p.data_vencimento or p.data_vencimento >= hoje))
    total_recebido = sum(p.valor for p in todas_parcelas if p.status == 'Pago')
    
    parcelas_atrasadas = [p for p in todas_parcelas if p.status != 'Pago' and p.data_vencimento and p.data_vencimento < hoje]
    total_atrasado = sum(p.valor for p in parcelas_atrasadas)
    qtd_atrasados = len(parcelas_atrasadas)

    if filtro_atual == 'afaturar':
        faturas_filtradas = [f for f in todas_faturas if f.status_geral == 'A Faturar']
    elif filtro_atual == 'aguardando':
        faturas_filtradas = [f for f in todas_faturas if f.status_geral == 'Aguardando Pagamento']
    elif filtro_atual == 'atrasados':
        faturas_filtradas = [f for f in todas_faturas if f.status_geral == 'Em Atraso']
    elif filtro_atual == 'pagos':
        faturas_filtradas = [f for f in todas_faturas if f.status_geral == 'Pago']
    else:
        faturas_filtradas = todas_faturas

    itens = []
    for f in faturas_filtradas:
        parcs_pendentes = [p for p in f.parcelas if p.status != 'Pago']
        primeira_parc = parcs_pendentes[0] if parcs_pendentes else (f.parcelas[0] if f.parcelas else None)
        data_venc = primeira_parc.data_vencimento if primeira_parc else None
        esta_vencida = f.status_geral == 'Em Atraso'

        boleto_anexo = None
        for p in f.parcelas:
            if p.arquivo_comprovante_boleto:
                boleto_anexo = p.arquivo_comprovante_boleto
                break

        itens.append({
            'fatura': f,
            'data_vencimento': data_venc,
            'esta_vencido': esta_vencida,
            'status_calculado': f.status_geral,
            'arquivo_boleto': boleto_anexo,
            'arquivo_nf': f.arquivo_nf
        })

    return render_template(
        'financeiro.html',
        itens=itens,
        filtro_atual=filtro_atual,
        total_a_faturar=total_a_faturar,
        total_aguardando=total_aguardando,
        total_atrasado=total_atrasado,
        total_recebido=total_recebido,
        qtd_atrasados=qtd_atrasados,
        hoje=hoje
    )

@app.route('/financeiro/fatura/<int:id>/atualizar', methods=['POST'])
@login_required
def atualizar_cobranca_fatura(id):
    fatura = Fatura.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    novo_status = request.form.get('status_pagamento')
    dt_venc = request.form.get('data_vencimento')
    data_formatada = datetime.strptime(dt_venc, '%Y-%m-%d').date() if dt_venc else None

    if 'arquivo_nf' in request.files:
        f = request.files['arquivo_nf']
        if f and f.filename:
            try:
                if fatura.arquivo_nf:
                    excluir_arquivo_supabase(fatura.arquivo_nf)
                fatura.arquivo_nf = salvar_arquivo_supabase(f, 'notas_fiscais', current_user.empresa_id)
            except ValueError as err:
                flash(str(err), 'danger')
                return redirect(url_for('financeiro', status=request.form.get('filtro_retorno', 'todos')))

    boleto_salvo = None
    if 'arquivo_boleto' in request.files:
        f_bol = request.files['arquivo_boleto']
        if f_bol and f_bol.filename:
            try:
                boleto_salvo = salvar_arquivo_supabase(f_bol, 'boletos', current_user.empresa_id)
            except ValueError as err:
                flash(str(err), 'danger')
                return redirect(url_for('financeiro', status=request.form.get('filtro_retorno', 'todos')))

    nova_obs = request.form.get('nova_ocorrencia')

    if fatura.parcelas:
        for p in fatura.parcelas:
            if novo_status in ['Pago', 'Boleto Emitido', 'A Faturar', 'Em Atraso']:
                p.status = novo_status
            if data_formatada and len(fatura.parcelas) == 1:
                p.data_vencimento = data_formatada
            if boleto_salvo:
                p.arquivo_comprovante_boleto = boleto_salvo
            if nova_obs:
                registro = f"[{datetime.now().strftime('%d/%m/%Y %H:%M')}] {nova_obs}\n"
                p.historico_cobranca = (p.historico_cobranca or "") + registro

    if novo_status == 'Pago':
        servicos_bloqueados = ServicoCliente.query.filter_by(
            fatura_id=fatura.id, 
            empresa_id=current_user.empresa_id
        ).filter(ServicoCliente.status.in_(['Bloqueado', 'Pendente'])).all()
        for sc in servicos_bloqueados:
            sc.status = 'Em Andamento'
            sc.observacoes = (sc.observacoes or "") + " | [Pagamento Confirmado: Execução Liberada]"

    db.session.commit()
    flash(f'Fatura "{fatura.descricao}" atualizada com sucesso!', 'success')
    return redirect(url_for('financeiro', status=request.form.get('filtro_retorno', 'todos')))

@app.route('/financeiro/parcela/<int:id>/atualizar', methods=['POST'])
@login_required
def atualizar_cobranca_parcela(id):
    parcela = ParcelaFatura.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    dt_venc = request.form.get('data_vencimento')
    if dt_venc:
        parcela.data_vencimento = datetime.strptime(dt_venc, '%Y-%m-%d').date()

    status_anterior = parcela.status
    novo_status = request.form.get('status_pagamento')
    parcela.status = novo_status
    parcela.forma_pagamento = request.form.get('forma_pagamento', parcela.forma_pagamento)

    if 'arquivo_comprovante_boleto' in request.files:
        f = request.files['arquivo_comprovante_boleto']
        if f and f.filename:
            try:
                if parcela.arquivo_comprovante_boleto:
                    excluir_arquivo_supabase(parcela.arquivo_comprovante_boleto)
                parcela.arquivo_comprovante_boleto = salvar_arquivo_supabase(f, 'comprovantes_parcelas', current_user.empresa_id)
            except ValueError as err:
                flash(str(err), 'danger')
                return redirect(url_for('financeiro', status=request.form.get('filtro_retorno', 'todos')))

    nova_obs = request.form.get('nova_ocorrencia')
    if nova_obs:
        registro = f"[{datetime.now().strftime('%d/%m/%Y %H:%M')}] {nova_obs}\n"
        parcela.historico_cobranca = (parcela.historico_cobranca or "") + registro

    # GATILHO AUTOMÁTICO DE BAIXA DE SINAL / ENTRADA
    if parcela.is_entrada and novo_status == 'Pago' and status_anterior != 'Pago':
        fatura = parcela.fatura
        
        # 1. Desbloqueia Ordens de Serviço (caso venha de propostas)
        servicos_bloqueados = ServicoCliente.query.filter_by(
            fatura_id=fatura.id, 
            empresa_id=current_user.empresa_id, 
            status='Bloqueado'
        ).all()
        for sc in servicos_bloqueados:
            sc.status = 'Em Andamento'
            sc.observacoes = (sc.observacoes or "") + " | [Sinal Confirmado: Execução Liberada]"

        # 2. Desbloqueia Pedidos de Venda de Produtos e envia para Expedição
        pedidos_bloqueados = PedidoRequisicao.query.filter_by(
            fatura_id=fatura.id,
            empresa_id=current_user.empresa_id,
            status='bloqueado_pagamento'
        ).all()
        for ped in pedidos_bloqueados:
            ped.status = 'em_separacao'
            ped.observacoes = (ped.observacoes or "") + " | [Sinal Pago: Liberado para Expedição]"

        flash(f'Sinal de Entrada quitado! {len(servicos_bloqueados)} serviço(s) e {len(pedidos_bloqueados)} pedido(s) liberados para a expedição.', 'success')

    db.session.commit()
    flash(f'{parcela.descricao_parcela} atualizada com sucesso!', 'info')
    return redirect(url_for('financeiro', status=request.form.get('filtro_retorno', 'todos')))

@app.route('/contratos/faturar-mes', methods=['POST'])
@login_required
def faturar_mes_contratos():
    hoje = date.today()
    mes_ano_ref = hoje.strftime('%m/%Y')
    
    contratos_ativos = ContratoRecorrente.query.filter_by(
        empresa_id=current_user.empresa_id,
        status='Ativo'
    ).all()

    gerados = 0
    for c in contratos_ativos:
        obs_identificador = f"[Ciclo {mes_ano_ref}]"
        
        ja_faturado = Fatura.query.filter(
            Fatura.contrato_id == c.id,
            Fatura.descricao.ilike(f"%{obs_identificador}%")
        ).first()

        if not ja_faturado:
            dia = min(c.dia_vencimento, 28)
            vencimento = date(hoje.year, hoje.month, dia)
            if vencimento < hoje:
                vencimento += relativedelta(months=1)

            nova_fatura = Fatura(
                empresa_id=current_user.empresa_id,
                cliente_id=c.cliente_id,
                contrato_id=c.id,
                descricao=f"{obs_identificador} Mensalidade - {c.titulo}",
                valor_total=c.valor_periodo,
                data_emissao=hoje
            )
            db.session.add(nova_fatura)
            db.session.flush()

            parc_ciclo = ParcelaFatura(
                empresa_id=current_user.empresa_id,
                fatura_id=nova_fatura.id,
                numero_parcela=1,
                total_parcelas=1,
                descricao_parcela=f"Mensalidade {mes_ano_ref}",
                forma_pagamento="Boleto Bancário",
                valor=c.valor_periodo,
                data_vencimento=vencimento,
                status="A Faturar"
            )
            db.session.add(parc_ciclo)

            nova_ordem = ServicoCliente(
                empresa_id=current_user.empresa_id,
                cliente_id=c.cliente_id,
                tipo_servico_id=c.tipo_servico_id,
                contrato_id=c.id,
                fatura_id=nova_fatura.id,
                valor_cobrado=c.valor_periodo,
                status='Pendente',
                data_solicitacao=hoje,
                data_previsao=vencimento,
                observacoes=f"{obs_identificador} Vistoria/Assessoria Mensal"
            )
            db.session.add(nova_ordem)
            gerados += 1

    db.session.commit()
    
    if gerados > 0:
        flash(f'{gerados} fatura(s) e ordem(ns) de serviço foram geradas para o ciclo {mes_ano_ref}!', 'success')
    else:
        flash(f'Todos os contratos ativos já foram faturados para o ciclo {mes_ano_ref}.', 'info')

    return redirect(url_for('financeiro'))

# -----------------------------------------------------------------------------
# 8. PERFIL DA EMPRESA, SUPORTE & ASSINATURA MERCADO PAGO
# -----------------------------------------------------------------------------

@app.route('/configuracoes/perfil', methods=['GET', 'POST'])
@login_required
def perfil_empresa():
    empresa = current_user.empresa
    usuario = current_user
    abrir_modal_pagamento = False
    
    if empresa and empresa.status_assinatura == 'trial':
        if empresa.valor_mensalidade != 0.0:
            empresa.valor_mensalidade = 0.0
            empresa.plano = "Período de Testes (Trial)"
            db.session.commit()

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        # 1. DADOS DA EMPRESA
        if form_type == 'dados_empresa':
            tipo_pessoa = request.form.get('tipo_pessoa', 'PJ')
            def _so_numeros(valor):
                return re.sub(r'\D', '', valor) if valor else ""

            if tipo_pessoa == 'PF':
                nome_pf = request.form.get('nome_profissional') or request.form.get('razao_social')
                empresa.razao_social = nome_pf
                empresa.nome_fantasia = "Profissional Autônomo"
                empresa.cnpj = _so_numeros(request.form.get('cpf') or request.form.get('cnpj'))
            else:
                empresa.razao_social = request.form.get('razao_social')
                empresa.nome_fantasia = request.form.get('nome_fantasia')
                empresa.cnpj = _so_numeros(request.form.get('cnpj'))

            empresa.telefone = _so_numeros(request.form.get('telefone'))
            empresa.email = request.form.get('email', '').strip()
            empresa.site = request.form.get('site', '').strip()
            empresa.cep = _so_numeros(request.form.get('cep'))
            empresa.logradouro = request.form.get('logradouro')
            empresa.numero = request.form.get('numero')
            empresa.complemento = request.form.get('complemento')
            empresa.bairro = request.form.get('bairro')
            empresa.cidade = request.form.get('cidade')
            empresa.estado = request.form.get('estado')
            empresa.endereco_completo = f"{empresa.logradouro or ''}, {empresa.numero or 'S/N'} {empresa.complemento or ''} - {empresa.bairro or ''}, {empresa.cidade or ''}/{empresa.estado or ''}".strip(" ,-/")
            empresa.cor_primaria = request.form.get('cor_primaria', '#1e3a8a')

            logo_file = request.files.get('logo')
            if logo_file and logo_file.filename != '':
                try:
                    if empresa.logo_filename:
                        excluir_arquivo_supabase(empresa.logo_filename)
                    chave_salva = salvar_arquivo_supabase(
                        file_storage=logo_file,
                        pasta_destino='logos',
                        empresa_id=empresa.id
                    )
                    empresa.logo_filename = chave_salva
                except Exception as e:
                    flash(f'Erro ao enviar logotipo: {str(e)}', 'danger')
                    return redirect(url_for('perfil_empresa'))

            db.session.commit()
            flash('Dados cadastrais atualizados com sucesso!', 'success')
            return redirect(url_for('perfil_empresa') + '#tab-dados')

        # 2. DADOS DO USUÁRIO
        elif form_type == 'dados_usuario':
            novo_nome = request.form.get('nome_usuario')
            novo_email = request.form.get('email_login', '').strip().lower()
            senha_atual = request.form.get('senha_atual')
            nova_senha = request.form.get('nova_senha')
            confirma_senha = request.form.get('confirma_senha')

            outro_usuario = Usuario.query.filter(Usuario.email == novo_email, Usuario.id != usuario.id).first()
            if outro_usuario:
                flash('Este e-mail já está sendo utilizado.', 'danger')
                return redirect(url_for('perfil_empresa'))

            usuario.nome = novo_nome
            usuario.email = novo_email

            if nova_senha:
                if not usuario.check_senha(senha_atual):
                    flash('A senha atual está incorreta.', 'danger')
                    return redirect(url_for('perfil_empresa'))
                if nova_senha != confirma_senha:
                    flash('A nova senha e a confirmação não conferem.', 'warning')
                    return redirect(url_for('perfil_empresa'))
                usuario.set_senha(nova_senha)
                flash('Senha alterada com sucesso!', 'success')
            else:
                flash('Dados atualizados com sucesso!', 'success')

            db.session.commit()
            return redirect(url_for('perfil_empresa') + '#tab-usuario')

        # 3. CALCULADORA MODULAR (R$ 14,90 BASE + MÓDULOS + USUÁRIOS)
        elif form_type == 'config_assinatura_modular':
            valor_calculado = 14.90

            empresa.modulo_servicos_campo = True
            empresa.modulo_atendimentos = bool(request.form.get('modulo_atendimentos'))
            empresa.modulo_gestao_tecnicos = bool(request.form.get('modulo_gestao_tecnicos'))
            empresa.modulo_estoque = bool(request.form.get('modulo_estoque'))
            empresa.modulo_vendas_externas = bool(request.form.get('modulo_vendas_externas'))

            if empresa.modulo_atendimentos:
                valor_calculado += 15.00
            if empresa.modulo_gestao_tecnicos:
                valor_calculado += 15.00
            if empresa.modulo_estoque:
                valor_calculado += 20.00
            if empresa.modulo_vendas_externas:
                valor_calculado += 20.00

            qtd_usuarios = int(request.form.get('limite_usuarios') or 5)
            empresa.limite_usuarios = max(5, qtd_usuarios)
            extras_usuarios = max(0, empresa.limite_usuarios - 5)
            valor_calculado += (extras_usuarios * 4.00)

            empresa.valor_base_plano = 14.90
            empresa.valor_mensalidade = round(valor_calculado, 2)
            empresa.plano = "Plano Customizado"

            empresa.gerar_token_requisicao_se_necessario()
            db.session.commit()

            flash(f'Plano configurado! Mensalidade: R$ {empresa.valor_mensalidade:.2f}. Escolha a forma de pagamento abaixo para ativar.', 'success')
            abrir_modal_pagamento = True

    usuarios_equipe = Usuario.query.filter_by(empresa_id=current_user.empresa_id).all()

    return render_template(
        'perfil_empresa.html', 
        perfil=empresa,
        usuarios_equipe=usuarios_equipe,
        abrir_modal_pagamento=abrir_modal_pagamento
    )

@app.route('/configuracoes/usuarios/novo', methods=['POST'])
@login_required
def criar_usuario_equipe():
    if current_user.nivel_acesso not in ['admin', 'master']:
        flash('Acesso restrito ao administrador.', 'danger')
        return redirect(url_for('perfil_empresa'))

    # 1. Contagem no banco (AQUI é onde define a variável para não dar erro)
    total_usuarios_empresa = Usuario.query.filter_by(empresa_id=current_user.empresa_id).count()

    # 2. Limite dinâmico vindo da empresa
    limite_real = getattr(current_user.empresa, 'limite_usuarios', 2) or 2

    # 3. Validação do limite
    if total_usuarios_empresa >= limite_real and current_user.nivel_acesso != 'master':
        flash(f'Limite atingido: Sua conta permite até {limite_real} colaboradores.', 'warning')
        return redirect(url_for('perfil_empresa'))

    nome = request.form.get('nome', '').strip()
    email = request.form.get('email', '').strip().lower()
    senha_padrao = request.form.get('senha_padrao', '')
    cargo = request.form.get('cargo', 'Colaborador').strip()
    perfil_selecionado = request.form.get('perfil_predefinido', 'personalizado')

    if not email or not senha_padrao:
        flash('E-mail e senha inicial são obrigatórios.', 'warning')
        return redirect(url_for('perfil_empresa'))

    # Validação de Senha Forte
    senha_valida, msg_erro = validar_senha_forte(senha_padrao)
    if not senha_valida:
        flash(f'A senha não foi aceita: {msg_erro}', 'warning')
        return redirect(url_for('perfil_empresa'))

    if Usuario.query.filter_by(email=email).first():
        flash('Este e-mail já está cadastrado no sistema.', 'danger')
        return redirect(url_for('perfil_empresa'))

    is_admin = perfil_selecionado == 'admin' or bool(request.form.get('perm_configuracoes'))

    novo_user = Usuario(
        empresa_id=current_user.empresa_id,
        nome=nome or email.split('@')[0],
        email=email,
        cargo=cargo,
        nivel_acesso='admin' if is_admin else 'operador',
        ativo=True,
        perm_clientes=bool(request.form.get('perm_clientes')),
        perm_propostas=bool(request.form.get('perm_propostas')),
        perm_servicos=bool(request.form.get('perm_servicos')),
        perm_financeiro=bool(request.form.get('perm_financeiro')),
        perm_configuracoes=bool(request.form.get('perm_configuracoes'))
    )
    novo_user.set_senha(senha_padrao)

    db.session.add(novo_user)
    db.session.commit()
    flash(f'Usuário "{email}" ({cargo}) cadastrado com sucesso!', 'success')
    return redirect(url_for('perfil_empresa'))

@app.route('/configuracoes/usuarios/resetar-senha/<int:id>', methods=['POST'])
@login_required
def resetar_senha_equipe(id):
    if current_user.nivel_acesso not in ['admin', 'master']:
        flash('Acesso restrito ao administrador.', 'danger')
        return redirect(url_for('perfil_empresa'))

    usuario = Usuario.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    nova_senha = request.form.get('nova_senha', '')

    senha_valida, msg_erro = validar_senha_forte(nova_senha)
    if not senha_valida:
        flash(f'Não foi possível redefinir: {msg_erro}', 'warning')
        return redirect(url_for('perfil_empresa'))

    usuario.set_senha(nova_senha)
    db.session.commit()
    flash(f'Senha de "{usuario.email}" redefinida com sucesso!', 'success')
    return redirect(url_for('perfil_empresa'))

@app.route('/configuracoes/usuarios/editar/<int:id>', methods=['POST'])
@login_required
def editar_usuario_equipe(id):
    if current_user.nivel_acesso not in ['admin', 'master']:
        flash('Acesso restrito ao administrador.', 'danger')
        return redirect(url_for('perfil_empresa'))

    usuario = Usuario.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()

    nome = request.form.get('nome', '').strip()
    email = request.form.get('email', '').strip().lower()
    cargo = request.form.get('cargo', '').strip()
    
    if nome:
        usuario.nome = nome

    # Validação e alteração do e-mail no banco de dados
    if email and email != usuario.email:
        email_em_uso = Usuario.query.filter(Usuario.email == email, Usuario.id != usuario.id).first()
        if email_em_uso:
            flash(f'O e-mail "{email}" já está sendo utilizado por outro usuário no sistema.', 'danger')
            return redirect(url_for('perfil_empresa'))
        usuario.email = email

    if cargo:
        usuario.cargo = cargo

    if usuario.id != current_user.id:
        perm_conf = bool(request.form.get('perm_configuracoes'))
        usuario.perm_clientes = bool(request.form.get('perm_clientes'))
        usuario.perm_propostas = bool(request.form.get('perm_propostas'))
        usuario.perm_servicos = bool(request.form.get('perm_servicos'))
        usuario.perm_financeiro = bool(request.form.get('perm_financeiro'))
        usuario.perm_configuracoes = perm_conf
        usuario.nivel_acesso = 'admin' if perm_conf else 'operador'

    db.session.commit()
    flash(f'Dados e permissões do usuário "{usuario.nome}" atualizados com sucesso no banco de dados!', 'success')
    return redirect(url_for('perfil_empresa'))

@app.route('/configuracoes/usuarios/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_usuario_equipe(id):
    if current_user.nivel_acesso not in ['admin', 'master']:
        flash('Acesso restrito ao administrador.', 'danger')
        return redirect(url_for('perfil_empresa'))

    usuario = Usuario.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    if usuario.id == current_user.id:
        flash('Você não pode remover seu próprio usuário.', 'warning')
        return redirect(url_for('perfil_empresa'))

    db.session.delete(usuario)
    db.session.commit()
    flash('Acesso removido com sucesso.', 'info')
    return redirect(url_for('perfil_empresa'))

@app.route('/faq')
@login_required
def faq():
    return render_template('faq.html')

@app.route('/suporte')
@login_required
def suporte():
    chamados = ChamadoSuporte.query.filter_by(
        empresa_id=current_user.empresa_id
    ).order_by(ChamadoSuporte.data_abertura.desc()).all()
    
    return render_template('suporte.html', chamados=chamados)

@app.route('/suporte/novo', methods=['POST'])
@login_required
def novo_chamado():
    assunto = request.form.get('assunto')
    categoria = request.form.get('categoria', 'Dúvida')
    prioridade = request.form.get('prioridade', 'Média')
    mensagem_texto = request.form.get('mensagem')
    arquivo = request.files.get('anexo')

    protocolo = f"TIK-{int(time.time())}"

    novo_ticket = ChamadoSuporte(
        empresa_id=current_user.empresa_id,
        usuario_id=current_user.id,
        numero_protocolo=protocolo,
        assunto=assunto,
        categoria=categoria,
        prioridade=prioridade,
        status='Aberto'
    )
    db.session.add(novo_ticket)
    db.session.flush()

    filename = None
    if arquivo and arquivo.filename:
        try:
            filename = salvar_arquivo_supabase(
                file_storage=arquivo,
                pasta_destino='suporte',
                empresa_id=current_user.empresa_id
            )
        except ValueError as err:
            flash(str(err), 'danger')
            return redirect(url_for('suporte'))

    primeira_msg = MensagemChamado(
        chamado_id=novo_ticket.id,
        usuario_id=current_user.id,
        conteudo=mensagem_texto,
        is_suporte=False,
        anexo_filename=filename
    )
    db.session.add(primeira_msg)
    db.session.commit()

    flash(f'Chamado {protocolo} aberto com sucesso! Nossa equipe analisará sua solicitação.', 'success')
    return redirect(url_for('suporte'))

@app.route('/suporte/<int:id>', methods=['GET', 'POST'])
@login_required
def detalhe_chamado(id):
    chamado = ChamadoSuporte.query.filter_by(
        id=id, 
        empresa_id=current_user.empresa_id
    ).first_or_404()

    if request.method == 'POST':
        conteudo = request.form.get('mensagem')
        arquivo = request.files.get('anexo')

        filename = None
        if arquivo and arquivo.filename:
            try:
                filename = salvar_arquivo_supabase(
                    file_storage=arquivo,
                    pasta_destino='suporte',
                    empresa_id=current_user.empresa_id
                )
            except ValueError as err:
                flash(str(err), 'danger')
                return redirect(url_for('detalhe_chamado', id=chamado.id))

        if conteudo or filename:
            nova_msg = MensagemChamado(
                chamado_id=chamado.id,
                usuario_id=current_user.id,
                conteudo=conteudo or "Anexo enviado.",
                is_suporte=False,
                anexo_filename=filename
            )
            chamado.status = 'Em Atendimento'
            db.session.add(nova_msg)
            db.session.commit()
            flash('Mensagem enviada com sucesso!', 'success')
            return redirect(url_for('detalhe_chamado', id=chamado.id))

    return render_template('detalhe_chamado.html', chamado=chamado)

@app.route('/assinatura/regularizar')
@login_required
@limiter.exempt
def regularizar_assinatura():
    if current_user.empresa.status_assinatura in ['ativo', 'trial'] or current_user.nivel_acesso == 'master':
        return redirect(url_for('index'))

    return render_template('bloqueio_pagamento.html')

# -----------------------------------------------------------------------------
# WEBHOOK OFICIAL MERCADO PAGO
# -----------------------------------------------------------------------------
@app.route('/webhook/mercadopago', methods=['POST'])
def webhook_mercadopago():
    dados = request.get_json(silent=True) or {}
    topic = dados.get('type') or request.args.get('topic') or request.args.get('type')
    payment_id = dados.get('data', {}).get('id') or request.args.get('id') or request.args.get('data.id')

    if topic == 'payment' and payment_id:
        sdk = mercadopago.SDK(os.getenv("MERCADOPAGO_ACCESS_TOKEN"))
        payment_info = sdk.payment().get(payment_id).get('response', {})

        status = payment_info.get('status')
        ext_ref = payment_info.get('external_reference', '')
        valor_pago = float(payment_info.get('transaction_amount') or 0.0)

        if ext_ref.startswith('emp_'):
            try:
                partes = ext_ref.split('_')
                empresa_id = int(partes[1])
                empresa = Empresa.query.get(empresa_id)

                if empresa:
                    if status == 'approved':
                        status_anterior = empresa.status_assinatura
                        empresa.status_assinatura = 'ativo'
                        empresa.data_ultimo_pagamento = date.today()
                        empresa.data_vencimento = date.today() + timedelta(days=30)
                        empresa.valor_mensalidade = valor_pago
                        empresa.mp_payment_id = str(payment_id)

                        if empresa.cupom_utilizado and status_anterior != 'ativo':
                            cupom_obj = CupomDesconto.query.filter_by(codigo=empresa.cupom_utilizado).first()
                            if cupom_obj:
                                cupom_obj.usos_atuais = (cupom_obj.usos_atuais or 0) + 1
                                
                                if cupom_obj.usuario_id:
                                    mes_ref = date.today().strftime('%Y-%m')
                                    ja_tem_comissao = ComissaoAfiliado.query.filter_by(
                                        empresa_id=empresa.id,
                                        usuario_id=cupom_obj.usuario_id,
                                        mes_competencia=mes_ref
                                    ).first()

                                    if not ja_tem_comissao:
                                        pct_comissao = cupom_obj.percentual_comissao or 20.0
                                        v_comissao = round(valor_pago * (pct_comissao / 100.0), 2)

                                        nova_comissao = ComissaoAfiliado(
                                            usuario_id=cupom_obj.usuario_id,
                                            cupom_id=cupom_obj.id,
                                            empresa_id=empresa.id,
                                            numero_parcela_parceiro=1,
                                            total_parcelas_permitidas=cupom_obj.meses_comissao_limite or 3,
                                            valor_mensalidade=valor_pago,
                                            percentual_comissao=pct_comissao,
                                            valor_comissao=v_comissao,
                                            mes_competencia=mes_ref,
                                            status='liberado'
                                        )
                                        db.session.add(nova_comissao)

                        db.session.commit()
                        print(f"[MERCADO PAGO] Assinatura aprovada e ativada para: {empresa.razao_social}")
                    elif status in ['cancelled', 'rejected']:
                        empresa.status_assinatura = 'bloqueado'
                        db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"[ERRO NO PROCESSAMENTO WEBHOOK MP]: {e}")

    return {"status": "success"}, 200

# -----------------------------------------------------------------------------
# ENDPOINT DE CHECKOUT TRANSPARENTE MERCADO PAGO
# -----------------------------------------------------------------------------
@app.route('/api/assinatura/checkout-preferencia', methods=['POST'])
@login_required
def api_checkout_preferencia():
    dados = request.get_json(silent=True) or {}
    ciclo = str(dados.get('ciclo', 'mensal')).lower()
    empresa = current_user.empresa

    if not empresa:
        return jsonify({"status": "error", "mensagem": "Empresa não vinculada."}), 400

    mensalidade = float(empresa.valor_mensalidade or 14.90)

    # Aplicação das regras de desconto por ciclo
    if ciclo == 'semestral':
        valor_bruto = mensalidade * 6
        valor_final = round(valor_bruto * (1.0 - 0.12), 2)
        nome_plano = "Assinatura Semestral (12% OFF)"
    elif ciclo == 'anual':
        valor_bruto = mensalidade * 12
        valor_final = round(valor_bruto * (1.0 - 0.25), 2)
        nome_plano = "Assinatura Anual (25% OFF)"
    else:
        valor_final = round(mensalidade, 2)
        nome_plano = "Assinatura Mensal"

    resposta = criar_preferencia_mercado_pago(
        empresa=empresa,
        plano=nome_plano,
        valor_total=valor_final
    )

    if resposta.get('sucesso'):
        return jsonify({
            'status': 'success',
            'init_point': resposta.get('init_point'),
            'sandbox_init_point': resposta.get('sandbox_init_point')
        })
    else:
        return jsonify({
            'status': 'error',
            'mensagem': resposta.get('mensagem', 'Erro ao gerar link do Mercado Pago.')
        }), 400

@app.route('/api/assinatura/checkout-transparente', methods=['POST'])
@login_required
def api_checkout_transparente():
    dados = request.get_json(silent=True) or {}
    ciclo = str(dados.get('ciclo', 'mensal')).lower()
    forma_pagamento = dados.get('forma_pagamento', 'PIX')
    cartao_dados = dados.get('cartao')
    parcelas = int(dados.get('parcelas', 1))

    empresa = current_user.empresa
    if not empresa:
        return jsonify({"status": "error", "mensagem": "Empresa não vinculada."}), 400

    mensalidade = float(empresa.valor_mensalidade or 14.90)

    # Cálculo do valor final com desconto por ciclo
    if ciclo == 'semestral':
        valor_bruto = mensalidade * 6
        desconto = valor_bruto * 0.12
        valor_final = round(valor_bruto - desconto, 2)
        nome_plano = "Semestral (12% off)"
    elif ciclo == 'anual':
        valor_bruto = mensalidade * 12
        desconto = valor_bruto * 0.25
        valor_final = round(valor_bruto - desconto, 2)
        nome_plano = "Anual (25% off)"
    else:
        valor_final = round(mensalidade, 2)
        nome_plano = "Mensal"

    ip_cliente = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip_cliente and ',' in ip_cliente:
        ip_cliente = ip_cliente.split(',')[0].strip()

    resultado = criar_cobranca_mercadopago(
        empresa=empresa,
        nome_plano=nome_plano,
        valor=valor_final,
        forma_pagamento=forma_pagamento,
        cartao_dados=cartao_dados,
        remote_ip=ip_cliente,
        parcelas=parcelas
    )

    if resultado.get('sucesso'):
        return jsonify({
            "status": "success",
            "mensagem": "Cobrança gerada com sucesso!",
            "valor_pago": valor_final,
            "ciclo": ciclo,
            "dados": resultado.get('dados'),
            "pix": resultado.get('pix'),
            "bankSlipUrl": resultado.get('bankSlipUrl')
        })
    else:
        return jsonify({
            "status": "error",
            "mensagem": resultado.get('mensagem', 'Erro ao processar cobrança.')
        }), 400
# -----------------------------------------------------------------------------
# GESTÃO DE CUPONS E AFILIADOS (PAINEL MASTER)
# -----------------------------------------------------------------------------

@app.route('/admin/master/cupons', methods=['GET', 'POST'])
@login_required
def admin_master_cupons():
    if current_user.nivel_acesso != 'master':
        flash('Acesso restrito ao Administrador Master.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip().upper()
        perc_desc = float(request.form.get('percentual_desconto', 10.0))
        perc_comissao = float(request.form.get('percentual_comissao', 20.0))
        limite = int(request.form.get('limite_usos', 100))
        val_str = request.form.get('data_validade')
        usuario_id = request.form.get('usuario_id') or None

        if CupomDesconto.query.filter_by(codigo=codigo).first():
            flash('Já existe um cupom com este código.', 'warning')
            return redirect(url_for('admin_master_cupons'))

        novo_cupom = CupomDesconto(
            usuario_id=int(usuario_id) if usuario_id else None,
            codigo=codigo,
            percentual_desconto=perc_desc,
            percentual_comissao=perc_comissao,
            limite_usos=limite,
            data_validade=datetime.strptime(val_str, '%Y-%m-%d').date() if val_str else None,
            ativo=True
        )
        db.session.add(novo_cupom)
        db.session.commit()
        flash(f'Cupom {codigo} criado com sucesso!', 'success')
        return redirect(url_for('admin_master_cupons'))

    cupons = CupomDesconto.query.order_by(CupomDesconto.id.desc()).all()
    parceiros = Usuario.query.filter_by(nivel_acesso='afiliado').all()

    return render_template(
        'admin/master_cupons.html',
        cupons=cupons,
        parceiros=parceiros,
        hoje=date.today()
    )

@app.route('/admin/master/parceiro/<int:user_id>/moderar', methods=['POST'])
@login_required
def admin_moderar_parceiro(user_id):
    if current_user.nivel_acesso != 'master':
        return redirect(url_for('index'))

    parceiro = Usuario.query.get_or_404(user_id)
    decisao = request.form.get('status_aprovacao')
    motivo = request.form.get('motivo_rejeicao', '')

    parceiro.status_aprovacao = decisao
    parceiro.motivo_rejeicao = motivo if decisao == 'rejeitado' else None

    for c in parceiro.cupons:
        c.ativo = (decisao == 'aprovado' and parceiro.aceitou_termos_afiliado)

    db.session.commit()
    flash(f'Parceiro {parceiro.nome} atualizado para {decisao}.', 'success')
    return redirect(url_for('admin_master_cupons'))

@app.route('/admin/master/cupons/<int:id>/status', methods=['POST'])
@login_required
@master_required
def admin_toggle_cupom(id):
    cupom = CupomDesconto.query.get_or_404(id)
    cupom.ativo = not cupom.ativo
    db.session.commit()
    flash(f'Status do cupom "{cupom.codigo}" alterado.', 'info')
    return redirect(url_for('admin_master_cupons'))

@app.route('/admin/master/afiliados', methods=['GET'])
@login_required
def admin_master_afiliados():
    if current_user.nivel_acesso != 'master':
        flash('Acesso restrito.', 'danger')
        return redirect(url_for('index'))
    
    cupons = CupomDesconto.query.all()
    return render_template('admin/master_afiliados.html', cupons=cupons)

@app.route('/admin/master/cupons/<int:id>/excluir', methods=['POST'])
@login_required
@master_required
def admin_excluir_cupom(id):
    cupom = CupomDesconto.query.get_or_404(id)
    codigo_removido = cupom.codigo
    usuario_origem_id = cupom.usuario_id

    try:
        # Desvincula empresas que guardavam o ID deste cupom como FK
        Empresa.query.filter_by(afiliado_id=cupom.id).update({'afiliado_id': None})
        
        # Desvincula comissões associadas a este ID de cupom
        ComissaoAfiliado.query.filter_by(cupom_id=cupom.id).update({'cupom_id': None})

        # Remove o cupom definitivamente do PostgreSQL
        db.session.delete(cupom)
        db.session.commit()

        flash(f'Cupom "{codigo_removido}" excluído permanentemente do banco de dados!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir cupom: {str(e)}', 'danger')

    # Se a exclusão veio de dentro da tela de auditoria de um parceiro, retorna para ela
    retorno = request.form.get('origem_retorno')
    if retorno == 'auditoria' and usuario_origem_id:
        return redirect(url_for('admin_auditoria_parceiro', id=usuario_origem_id))

    return redirect(url_for('admin_master_cupons'))

@app.route('/admin/master/afiliado/<int:id>/status', methods=['POST'])
@login_required
def admin_alterar_status_afiliado(id):
    if current_user.nivel_acesso != 'master':
        return redirect(url_for('index'))
    
    cupom = CupomDesconto.query.get_or_404(id)
    novo_status = request.form.get('status_aprovacao')
    
    cupom.status_aprovacao = novo_status
    if novo_status == 'aprovado':
        cupom.ativo = True
    else:
        cupom.ativo = False
        cupom.motivo_rejeicao = request.form.get('motivo_rejeicao', '')
        
    db.session.commit()
    flash(f'Status do afiliado {cupom.afiliado_nome} atualizado para {novo_status}.', 'success')
    return redirect(url_for('admin_master_afiliados'))

@app.route('/admin/master/parceiro/<int:id>/auditoria', methods=['GET'])
@login_required
def admin_auditoria_parceiro(id):
    if current_user.nivel_acesso != 'master':
        return redirect(url_for('index'))

    parceiro = Usuario.query.get_or_404(id)
    cupons = CupomDesconto.query.filter_by(usuario_id=parceiro.id).order_by(CupomDesconto.id.desc()).all()
    codigos = [c.codigo for c in cupons]
    cupons_ids = [c.id for c in cupons]

    from sqlalchemy import or_
    condicoes = []
    if codigos:
        condicoes.append(Empresa.cupom_utilizado.in_(codigos))
    if cupons_ids:
        condicoes.append(Empresa.afiliado_id.in_(cupons_ids))

    empresas = Empresa.query.filter(or_(*condicoes)).order_by(Empresa.data_criacao.desc()).all() if condicoes else []

    comissoes = ComissaoAfiliado.query.filter_by(usuario_id=parceiro.id).order_by(ComissaoAfiliado.id.desc()).all()
    repasses = RepasseAfiliado.query.filter_by(usuario_id=parceiro.id).order_by(RepasseAfiliado.id.desc()).all()

    saldo_liberado = sum(c.valor_comissao for c in comissoes if c.status == 'liberado')
    total_ja_pago = sum(r.valor_total_pago for r in repasses)
    total_usos_cupons = sum(c.usos_atuais or 0 for c in cupons)

    cupom_primario = cupons[0].codigo if cupons else 'PADRAO'
    link_indicacao = url_for('auth.registro', ref=cupom_primario, _external=True)

    return render_template(
        'admin/master_auditoria_parceiro.html',
        parceiro=parceiro,
        cupons=cupons,
        empresas=empresas,
        comissoes=comissoes,
        repasses=repasses,
        saldo_liberado=saldo_liberado,
        total_ja_pago=total_ja_pago,
        total_usos_cupons=total_usos_cupons,
        link_indicacao=link_indicacao,
        hoje=date.today()
    )

@app.route('/admin/master/parceiro/<int:id>/atualizar-cadastro', methods=['POST'])
@login_required
def admin_atualizar_cadastro_parceiro(id):
    if current_user.nivel_acesso != 'master':
        return redirect(url_for('index'))

    parceiro = Usuario.query.get_or_404(id)
    
    parceiro.nome = request.form.get('nome', parceiro.nome).strip()
    parceiro.email = request.form.get('email', parceiro.email).strip().lower()
    parceiro.whatsapp = request.form.get('whatsapp', '').strip()
    parceiro.cpf_cnpj = request.form.get('cpf_cnpj', '').strip()
    parceiro.chave_pix = request.form.get('chave_pix', '').strip()
    parceiro.rede_social_principal = request.form.get('rede_social_principal', '').strip()
    parceiro.tipo_parceiro = request.form.get('tipo_parceiro', parceiro.tipo_parceiro or 'Outros')
    
    novo_status = request.form.get('status_aprovacao', parceiro.status_aprovacao)
    parceiro.status_aprovacao = novo_status
    if novo_status == 'rejeitado':
        parceiro.motivo_rejeicao = request.form.get('motivo_rejeicao', '')
    else:
        parceiro.motivo_rejeicao = None

    # Sincroniza a ativação dos cupons com a aprovação
    for c in parceiro.cupons:
        c.ativo = (novo_status == 'aprovado' and parceiro.aceitou_termos_afiliado)

    db.session.commit()
    flash(f'Ficha cadastral de "{parceiro.nome}" atualizada com sucesso!', 'success')
    return redirect(url_for('admin_auditoria_parceiro', id=parceiro.id))

@app.route('/admin/master/parceiro/<int:id>/liquidar-repasse', methods=['POST'])
@login_required
def admin_liquidar_repasse(id):
    if current_user.nivel_acesso != 'master':
        return redirect(url_for('index'))

    parceiro = Usuario.query.get_or_404(id)
    mes_comp = request.form.get('mes_competencia', datetime.utcnow().strftime('%Y-%m'))
    valor_pago = float(request.form.get('valor_pago', 0.0))
    observacoes = request.form.get('observacoes', '')

    nome_arquivo_salvo = None
    arquivo = request.files.get('comprovante')
    if arquivo and arquivo.filename:
        try:
            nome_arquivo_salvo = salvar_arquivo_supabase(
                file_storage=arquivo,
                pasta_destino='repasses_afiliados',
                empresa_id=0  # Escopo administrativo/master
            )
        except ValueError as err:
            flash(str(err), 'danger')
            return redirect(url_for('admin_auditoria_parceiro', id=parceiro.id))

    novo_repasse = RepasseAfiliado(
        usuario_id=parceiro.id,
        mes_competencia=mes_comp,
        valor_total_pago=valor_pago,
        chave_pix_utilizada=parceiro.chave_pix,
        arquivo_comprovante=nome_arquivo_salvo,
        observacoes=observacoes
    )
    db.session.add(novo_repasse)
    db.session.flush()

    comissoes_liberadas = ComissaoAfiliado.query.filter_by(usuario_id=parceiro.id, status='liberado').all()
    for c in comissoes_liberadas:
        c.status = 'pago'
        c.data_pagamento = datetime.utcnow()
        c.repasse_id = novo_repasse.id

    novo_repasse.qtd_faturas_inclusas = len(comissoes_liberadas)
    db.session.commit()

    flash(f'Repasse de R$ {valor_pago:.2f} liquidado com sucesso para {parceiro.nome}!', 'success')
    return redirect(url_for('admin_auditoria_parceiro', id=parceiro.id))

@app.route('/api/cupom/validar', methods=['POST'])
def api_validar_cupom():
    dados = request.get_json(silent=True) or {}
    codigo = str(dados.get('codigo', '')).strip().upper()
    nome_plano = str(dados.get('plano', 'MENSAL')).upper()

    cupom = CupomDesconto.query.filter_by(codigo=codigo).first()
    if not cupom or not cupom.is_valido:
        return jsonify({'valido': False, 'mensagem': 'Cupom inválido, esgotado ou inativo.'})

    if cupom.parceiro and cupom.parceiro.status_aprovacao != 'aprovado':
        return jsonify({'valido': False, 'mensagem': 'Este cupom de parceiro ainda está em moderação.'})

    precos = {
        'MENSAL': 39.90,
        'SEMESTRAL': 209.40,
        'ANUAL': 358.80
    }
    
    chave = 'ANUAL' if 'ANUAL' in nome_plano else ('SEMESTRAL' if 'SEMESTRAL' in nome_plano else 'MENSAL')
    valor_original = precos.get(chave, 39.90)
    desconto = valor_original * (cupom.percentual_desconto / 100.0)
    valor_final = round(valor_original - desconto, 2)

    return jsonify({
        'valido': True,
        'codigo': cupom.codigo,
        'desconto_percentual': cupom.percentual_desconto,
        'valor_original': valor_original,
        'valor_final': valor_final,
        'mensagem': f'Cupom {cupom.codigo} aplicado! {cupom.percentual_desconto}% de desconto.'
    })

@app.route('/admin/master/parceiro/<int:id>/criar-cupom', methods=['POST'])
@login_required
def admin_criar_cupom_parceiro(id):
    if current_user.nivel_acesso != 'master':
        return redirect(url_for('index'))

    parceiro = Usuario.query.get_or_404(id)
    codigo = (request.form.get('codigo') or '').strip().upper()
    desconto = float(request.form.get('percentual_desconto') or 10.0)
    comissao = float(request.form.get('percentual_comissao') or 20.0)
    limite = int(request.form.get('limite_usos') or 100)
    meses_limite = int(request.form.get('meses_comissao_limite') or 3)

    if not codigo:
        flash('O código do cupom é obrigatório.', 'warning')
        return redirect(url_for('admin_auditoria_parceiro', id=parceiro.id))

    if CupomDesconto.query.filter_by(codigo=codigo).first():
        flash(f'O código de cupom "{codigo}" já existe no sistema.', 'warning')
        return redirect(url_for('admin_auditoria_parceiro', id=parceiro.id))

    try:
        novo_cupom = CupomDesconto(
            usuario_id=parceiro.id,
            codigo=codigo,
            percentual_desconto=desconto,
            percentual_comissao=comissao,
            limite_usos=limite,
            meses_comissao_limite=meses_limite,
            ativo=True if parceiro.status_aprovacao == 'aprovado' else False
        )
        db.session.add(novo_cupom)
        db.session.commit()
        flash(f'Cupom {codigo} gerado e vinculado a {parceiro.nome} com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao gravar cupom no banco de dados: {str(e)}', 'danger')

    return redirect(url_for('admin_auditoria_parceiro', id=parceiro.id))

# -----------------------------------------------------------------------------
# FASE 3: GERADOR DE MINUTAS & CONTRATOS PERSONALIZADOS
# -----------------------------------------------------------------------------

@app.route('/cliente/<int:cliente_id>/contrato/novo', methods=['POST'])
@login_required
def gerar_minuta_contrato(cliente_id):
    cliente = Cliente.query.filter_by(id=cliente_id, empresa_id=current_user.empresa_id).first_or_404()
    proposta_id = request.form.get('proposta_id')
    
    proposta = None
    if proposta_id:
        proposta = Proposta.query.filter_by(id=int(proposta_id), empresa_id=current_user.empresa_id).first()

    empresa = current_user.empresa
    total_existentes = ContratoGerado.query.filter_by(empresa_id=empresa.id).count() + 1
    num_doc = f"CONT-{date.today().year}-{total_existentes:03d}"

    itens_texto = ""
    valor_contrato = "0,00"
    condicoes_pgto = "A combinar entre as partes."
    
    if proposta:
        valor_contrato = f"{proposta.valor_total:,.2f}"
        condicoes_pgto = proposta.condicoes_pagamento or "Conforme alinhamento comercial prévio."
        for idx, item in enumerate(proposta.itens, 1):
            nome_serv = item.tipo_servico.nome if item.tipo_servico else "Serviço"
            desc_serv = item.descricao_personalizada or (item.tipo_servico.descricao_padrao if item.tipo_servico else "")
            itens_texto += f"<p><b>{idx}. {nome_serv} ({item.quantidade} {item.unidade}):</b> {desc_serv} — Valor: R$ {item.valor_total:,.2f}</p>"
    else:
        itens_texto = "<p>Prestação de serviços técnicos especializados sob demanda.</p>"

    conteudo_padrao = f"""
    <h3 style="text-align: center;">INSTRUMENTO PARTICULAR DE PRESTAÇÃO DE SERVIÇOS</h3>
    <p style="text-align: center;"><b>DOCUMENTO Nº {num_doc}</b></p>
    <br>
    <p><b>CONTRATADA:</b> {empresa.razao_social.upper()}, pessoa jurídica de direito privado/autônomo, inscrita no CNPJ/CPF sob nº {empresa.cnpj or 'Não informado'}, com sede em {empresa.endereco_completo or 'endereço comercial cadastrado'}.</p>
    
    <p><b>CONTRATANTE:</b> {cliente.nome.upper()}, inscrito(a) no CNPJ/CPF sob nº {cliente.cnpj_cpf}, com sede/domicílio em {cliente.logradouro or ''}, {cliente.numero or 'S/N'}, {cliente.bairro or ''}, {cliente.cidade or ''}/{cliente.estado or ''}.</p>
    
    <hr>
    
    <h4>CLÁUSULA 1ª - DO OBJETO</h4>
    <p>O presente contrato tem por objeto a prestação dos serviços técnicos discriminados a seguir:</p>
    {itens_texto}
    
    <h4>CLÁUSULA 2ª - DO VALOR E FORMA DE PAGAMENTO</h4>
    <p>Pela prestação dos serviços ora contratados, o(a) <b>CONTRATANTE</b> pagará à <b>CONTRATADA</b> a quantia global de <b>R$ {valor_contrato}</b>.</p>
    <p><b>Condições acordadas:</b> {condicoes_pgto}</p>
    
    <h4>CLÁUSULA 3ª - DAS OBRIGAÇÕES DAS PARTES</h4>
    <p>A CONTRATADA compromete-se a executar os serviços descritos com zelo, rigor técnico e em estrita observância às normas técnicas e regulamentadoras aplicáveis. O CONTRATANTE obriga-se a fornecer as informações e acessos necessários para a perfeita execução dos trabalhos.</p>
    
    <h4>CLÁUSULA 4ª - DO PRAZO E RESCISÃO</h4>
    <p>O presente instrumento vigorará até a conclusão e entrega final dos serviços contratados. Em caso de rescisão imotivada por qualquer das partes antes do término, fica estipulada a liquidação proporcional das etapas já executadas.</p>
    
    <h4>CLÁUSULA 5ª - DO FORO</h4>
    <p>Para dirimir eventuais controvérsias oriundas do presente instrumento, as partes elegem o foro da comarca de {empresa.cidade or 'Suzano'}/{empresa.estado or 'SP'}, renunciando a qualquer outro por mais privilegiado que seja.</p>
    <br>
    <p style="text-align: right;">{empresa.cidade or 'São Paulo'}, {date.today().strftime('%d de %m de %Y')}.</p>
    """

    novo_contrato = ContratoGerado(
        empresa_id=empresa.id,
        cliente_id=cliente.id,
        proposta_id=proposta.id if proposta else None,
        numero_documento=num_doc,
        titulo=f"Contrato de Prestação de Serviços - {cliente.nome}",
        conteudo_html=conteudo_padrao.strip(),
        status='minuta'
    )
    db.session.add(novo_contrato)
    db.session.commit()

    flash(f'Minuta {num_doc} criada com sucesso! Você pode revisar o texto abaixo.', 'success')
    return redirect(url_for('detalhe_cliente', id=cliente.id))

@app.route('/contrato/<int:id>/salvar-texto', methods=['POST'])
@login_required
def salvar_texto_contrato(id):
    contrato = ContratoGerado.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    contrato.titulo = request.form.get('titulo', contrato.titulo)
    contrato.status = request.form.get('status', contrato.status)
    contrato.conteudo_html = request.form.get('conteudo_html', contrato.conteudo_html)
    
    if contrato.status == 'assinado' and not contrato.data_assinatura:
        contrato.data_assinatura = datetime.utcnow()

    db.session.commit()
    flash(f'Contrato "{contrato.numero_documento}" atualizado com sucesso!', 'success')
    return redirect(url_for('detalhe_cliente', id=contrato.cliente_id))

@app.route('/contrato/<int:id>/excluir', methods=['POST'])
@login_required
def excluir_contrato(id):
    contrato = ContratoGerado.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    cliente_id = contrato.cliente_id
    db.session.delete(contrato)
    db.session.commit()
    flash('Minuta de contrato removida.', 'info')
    return redirect(url_for('detalhe_cliente', id=cliente_id))

@app.route('/contrato/<int:id>/pdf')
@login_required
def gerar_pdf_contrato(id):
    contrato = ContratoGerado.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    cliente = contrato.cliente
    empresa = current_user.empresa
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    elementos = []
    styles = getSampleStyleSheet()

    cor_primaria_hex = empresa.cor_primaria if empresa.cor_primaria and empresa.cor_primaria.startswith('#') else "#1e3a8a"
    cor_marca = colors.HexColor(cor_primaria_hex)

    # Estilos idênticos aos da Proposta
    estilo_empresa_nome = ParagraphStyle('PDF_EmpresaNome', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=13, leading=16, textColor=cor_marca)
    estilo_empresa_sub = ParagraphStyle('PDF_EmpresaSub', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor("#475569"))
    estilo_titulo_doc = ParagraphStyle('PDF_ContrTit', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=15, textColor=cor_marca, alignment=1)
    estilo_subtit = ParagraphStyle('PDF_ContrSubTit', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9.5, leading=13, textColor=cor_marca)
    estilo_corpo = ParagraphStyle('PDF_ContrCorpo', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=13, textColor=colors.HexColor("#1e293b"), alignment=4)

    logo_elemento = _obter_logo_reportlab(empresa.logo_filename, width=1.5*inch, height=0.6*inch)

    razao_empresa = _limpar_texto(empresa.razao_social or 'EMPRESA PRESTADORA')
    fantasia_empresa = _limpar_texto(empresa.nome_fantasia or '')
    cnpj_empresa = _limpar_texto(empresa.cnpj or 'Não informado')
    tel_empresa = _limpar_texto(empresa.telefone or 'Não informado')
    email_empresa = _limpar_texto(empresa.email or '')
    site_empresa = _limpar_texto(empresa.site or '')
    end_empresa = _limpar_texto(empresa.endereco_completo or '')

    info_empresa_html = f"""
    <b>{razao_empresa.upper()}</b><br/>
    {f"Nome Fantasia: {fantasia_empresa}<br/>" if fantasia_empresa else ""}
    CNPJ/CPF: {cnpj_empresa} | Tel: {tel_empresa}<br/>
    {f"E-mail: {email_empresa} | " if email_empresa else ""}{site_empresa}<br/>
    {end_empresa}
    """.strip()

    # Cabeçalho timbrado uniforme (1.8 in x 5.7 in)
    if logo_elemento:
        tab_topo = Table([[logo_elemento, Paragraph(info_empresa_html, estilo_empresa_sub)]], colWidths=[1.8*inch, 5.7*inch])
    else:
        tab_topo = Table([[Paragraph(f"<b>{razao_empresa.upper()}</b>", estilo_empresa_nome), Paragraph(info_empresa_html, estilo_empresa_sub)]], colWidths=[2.8*inch, 4.7*inch])

    tab_topo.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
    ]))
    elementos.append(tab_topo)
    elementos.append(Spacer(1, 6))
    elementos.append(HRFlowable(width="100%", thickness=1.5, color=cor_marca, spaceAfter=12))

    # Título do Contrato e Documento
    elementos.append(Paragraph(f"<b>{_limpar_texto(contrato.titulo).upper()}</b>", estilo_titulo_doc))
    elementos.append(Paragraph(f"<font color='#64748b' size='8'>DOCUMENTO Nº {_limpar_texto(contrato.numero_documento)}</font>", estilo_titulo_doc))
    elementos.append(Spacer(1, 12))

    # Conteúdo das Cláusulas
    texto_raw = contrato.conteudo_html or ""
    blocos = re.split(r'</?(?:p|h\d|div|li|tr)[^>]*>', texto_raw)

    for bloco in blocos:
        bloco_limpo = re.sub(r'<br\s*/?>', '<br/>', bloco).strip()
        if not bloco_limpo:
            continue

        bloco_fmt = re.sub(r'<(?!/?(?:b|i|u|font|br))[^>]+>', '', bloco_limpo)

        if re.match(r'^(?:CL[AÁ]USULA|INSTRUMENTO|\d+\.)', bloco_fmt, re.IGNORECASE):
            elementos.append(Spacer(1, 4))
            elementos.append(Paragraph(bloco_fmt, estilo_subtit))
            elementos.append(Spacer(1, 2))
        else:
            elementos.append(Paragraph(bloco_fmt, estilo_corpo))
            elementos.append(Spacer(1, 4))

    # Espaçamento generoso antes das assinaturas
    elementos.append(Spacer(1, 45))

    nome_cli = _limpar_texto(cliente.nome or 'CONTRATANTE')
    dados_assinaturas = [
        [
            Paragraph(f"____________________________________________<br/><b>{razao_empresa.upper()}</b><br/>Contratada", estilo_corpo),
            Paragraph(f"____________________________________________<br/><b>{nome_cli.upper()}</b><br/>Contratante", estilo_corpo)
        ]
    ]
    tab_ass = Table(dados_assinaturas, colWidths=[3.75*inch, 3.75*inch])
    tab_ass.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elementos.append(tab_ass)

    doc.build(elementos)
    buffer.seek(0)

    nome_arquivo_pdf = f"Contrato_{contrato.numero_documento}.pdf"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=nome_arquivo_pdf,
        mimetype='application/pdf'
    )


# =============================================================================
# MÓDULO DE CONTROLE DE ESTOQUE, ALMOXARIFADO & REQUISIÇÕES
# =============================================================================

@app.route('/estoque')
@login_required
def listar_estoque():
    # Validação da contratação do módulo
    if not current_user.empresa.modulo_estoque and current_user.nivel_acesso != 'master':
        flash('O Módulo de Estoque e Almoxarifado não está habilitado no seu plano. Ative-o na aba de assinaturas.', 'warning')
        return redirect(url_for('perfil_empresa') + '#tab-planos')

    busca = request.args.get('busca', '').strip()
    filtro_alerta = request.args.get('alerta', '')

    query = ProdutoEstoque.query.filter_by(empresa_id=current_user.empresa_id)

    if busca:
        query = query.filter(
            (ProdutoEstoque.nome.ilike(f'%{busca}%')) |
            (ProdutoEstoque.codigo_sku.ilike(f'%{busca}%')) |
            (ProdutoEstoque.codigo_barras.ilike(f'%{busca}%'))
        )

    produtos = query.order_by(ProdutoEstoque.nome.asc()).all()

    if filtro_alerta == 'baixo':
        produtos = [p for p in produtos if p.alerta_estoque_baixo]

    # Indicadores
    total_itens = len(produtos)
    itens_alerta = sum(1 for p in produtos if p.alerta_estoque_baixo)
    valor_total_custo = sum((p.quantidade_atual or 0) * (p.preco_custo or 0) for p in produtos)
    valor_total_venda = sum((p.quantidade_atual or 0) * (p.preco_venda_sugerido or 0) for p in produtos)

    # Últimas movimentações
    movimentacoes_recentes = MovimentacaoEstoque.query.filter_by(
        empresa_id=current_user.empresa_id
    ).order_by(MovimentacaoEstoque.data_movimento.desc()).limit(10).all()

    # Garante link público de requisição
    token_equipe = current_user.empresa.gerar_token_requisicao_se_necessario()
    db.session.commit()

    return render_template(
        'estoque.html',
        produtos=produtos,
        total_itens=total_itens,
        itens_alerta=itens_alerta,
        valor_total_custo=valor_total_custo,
        valor_total_venda=valor_total_venda,
        movimentacoes_recentes=movimentacoes_recentes,
        busca=busca,
        filtro_alerta=filtro_alerta,
        token_equipe=token_equipe
    )


@app.route('/estoque/produto/novo', methods=['POST'])
@login_required
def criar_produto_estoque():
    try:
        nome = request.form.get('nome', '').strip()
        sku = request.form.get('codigo_sku', '').strip()
        barras = request.form.get('codigo_barras', '').strip()
        unidade = request.form.get('unidade_medida', 'un').strip()
        tipo_item = request.form.get('tipo_item', 'misto')
        qtd_inicial = float(request.form.get('quantidade_inicial') or 0.0)
        qtd_min = float(request.form.get('quantidade_minima') or 5.0)
        p_custo = float(request.form.get('preco_custo') or 0.0)
        p_venda = float(request.form.get('preco_venda_sugerido') or 0.0)
        descricao = request.form.get('descricao', '').strip()

        novo_prod = ProdutoEstoque(
            empresa_id=current_user.empresa_id,
            nome=nome,
            codigo_sku=sku or None,
            codigo_barras=barras or None,
            unidade_medida=unidade,
            tipo_item=tipo_item,
            quantidade_atual=qtd_inicial,
            quantidade_minima=qtd_min,
            preco_custo=p_custo,
            preco_venda_sugerido=p_venda,
            descricao=descricao or None
        )

        foto = request.files.get('foto')
        if foto and foto.filename:
            novo_prod.foto_arquivo = salvar_arquivo_supabase(foto, 'produtos_estoque', current_user.empresa_id)

        db.session.add(novo_prod)
        db.session.flush()

        # Registro de saldo inicial no histórico (Kardex)
        if qtd_inicial > 0:
            mov = MovimentacaoEstoque(
                empresa_id=current_user.empresa_id,
                produto_id=novo_prod.id,
                tipo_movimento='entrada_manual',
                quantidade=qtd_inicial,
                saldo_anterior=0.0,
                saldo_posterior=qtd_inicial,
                motivo_observacao='Cadastro Inicial de Saldo',
                usuario_id=current_user.id
            )
            db.session.add(mov)

        db.session.commit()
        flash(f'Item "{nome}" cadastrado no estoque com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao cadastrar produto: {str(e)}', 'danger')

    return redirect(url_for('listar_estoque'))

@app.route('/estoque/produto/editar/<int:id>', methods=['POST'])
@login_required
def editar_produto_estoque(id):
    """Atualiza todos os dados cadastrais do produto e permite troca da foto otimizada."""
    produto = ProdutoEstoque.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()

    try:
        produto.nome = request.form.get('nome', '').strip()
        produto.codigo_sku = request.form.get('codigo_sku', '').strip() or None
        produto.codigo_barras = request.form.get('codigo_barras', '').strip() or None
        produto.unidade_medida = request.form.get('unidade_medida', 'un').strip()
        produto.tipo_item = request.form.get('tipo_item', 'misto')
        produto.quantidade_minima = float(request.form.get('quantidade_minima') or 5.0)
        produto.preco_custo = float(request.form.get('preco_custo') or 0.0)
        produto.preco_venda_sugerido = float(request.form.get('preco_venda_sugerido') or 0.0)
        produto.descricao = request.form.get('descricao', '').strip() or None

        # Otimização e compressão automática da imagem via storage_service
        foto = request.files.get('foto')
        if foto and foto.filename:
            if produto.foto_arquivo:
                excluir_arquivo_supabase(produto.foto_arquivo)
            produto.foto_arquivo = salvar_arquivo_supabase(foto, 'produtos_estoque', current_user.empresa_id)

        # Se o usuário também informou movimentação de saldo na aba rápida
        qtd_mov = float(request.form.get('quantidade_movimento') or 0.0)
        tipo_operacao = request.form.get('tipo_operacao')
        motivo_obs = request.form.get('motivo_observacao', '').strip() or 'Ajuste cadastral de saldo'

        if qtd_mov > 0:
            saldo_anterior = float(produto.quantidade_atual or 0.0)
            if tipo_operacao == 'entrada':
                saldo_posterior = saldo_anterior + qtd_mov
                tipo_mov = 'entrada_manual'
            else:
                if qtd_mov > saldo_anterior:
                    flash(f'Saldo insuficiente para saída! Disponível: {saldo_anterior} {produto.unidade_medida}.', 'danger')
                    return redirect(url_for('listar_estoque'))
                saldo_posterior = saldo_anterior - qtd_mov
                tipo_mov = 'saida_manual'

            produto.quantidade_atual = saldo_posterior
            mov = MovimentacaoEstoque(
                empresa_id=current_user.empresa_id,
                produto_id=produto.id,
                tipo_movimento=tipo_mov,
                quantidade=qtd_mov,
                saldo_anterior=saldo_anterior,
                saldo_posterior=saldo_posterior,
                motivo_observacao=motivo_obs,
                usuario_id=current_user.id
            )
            db.session.add(mov)

        db.session.commit()
        flash(f'Item "{produto.nome}" atualizado com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao atualizar produto: {str(e)}', 'danger')

    return redirect(url_for('listar_estoque'))


@app.route('/estoque/produto/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_produto_estoque(id):
    """Exclui o item do catálogo caso não esteja vinculado a pedidos de vendas ou propostas."""
    produto = ProdutoEstoque.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()

    # Validação de segurança: verificar vínculos
    tem_pedidos = ItemPedidoRequisicao.query.filter_by(produto_id=produto.id).first()
    tem_propostas = ItemProposta.query.filter_by(produto_id=produto.id).first()

    if tem_pedidos or tem_propostas:
        flash(f'O item "{produto.nome}" não pode ser excluído pois possui pedidos ou propostas vinculadas no histórico.', 'warning')
        return redirect(url_for('listar_estoque'))

    try:
        nome_removido = produto.nome
        if produto.foto_arquivo:
            excluir_arquivo_supabase(produto.foto_arquivo)

        db.session.delete(produto)
        db.session.commit()
        flash(f'Item "{nome_removido}" excluído com sucesso do almoxarifado.', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir produto: {str(e)}', 'danger')

    return redirect(url_for('listar_estoque'))


@app.route('/estoque/requisicoes')
@login_required
def listar_requisicoes_estoque():
    if not current_user.empresa.modulo_estoque and current_user.nivel_acesso != 'master':
        flash('Módulo não contratado.', 'warning')
        return redirect(url_for('perfil_empresa'))

    filtro_status = request.args.get('status', 'todos')
    query = PedidoRequisicao.query.filter_by(empresa_id=current_user.empresa_id)

    if filtro_status == 'pendentes':
        query = query.filter_by(status='pendente')
    elif filtro_status == 'separacao':
        query = query.filter_by(status='em_separacao')
    elif filtro_status == 'concluidas':
        query = query.filter_by(status='entregue')

    pedidos = query.order_by(PedidoRequisicao.data_solicitacao.desc()).all()

    return render_template(
        'requisicoes.html',
        pedidos=pedidos,
        filtro_status=filtro_status
    )


@app.route('/estoque/requisicoes/<int:id>/status', methods=['POST'])
@login_required
def atualizar_status_requisicao(id):
    pedido = PedidoRequisicao.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    novo_status = request.form.get('novo_status')

    status_anterior = pedido.status
    pedido.status = novo_status

    # Se mudar para ENTREGUE, dá baixa automática e definitiva no estoque
    if novo_status == 'entregue' and status_anterior != 'entregue':
        for item in pedido.itens:
            prod = item.produto
            qtd_baixa = float(item.quantidade_solicitada or 0.0)
            saldo_anterior = float(prod.quantidade_atual or 0.0)
            saldo_novo = max(0.0, saldo_anterior - qtd_baixa)

            prod.quantidade_atual = saldo_novo
            item.quantidade_atendida = qtd_baixa

            mov = MovimentacaoEstoque(
                empresa_id=current_user.empresa_id,
                produto_id=prod.id,
                tipo_movimento='saida_requisicao',
                quantidade=qtd_baixa,
                saldo_anterior=saldo_anterior,
                saldo_posterior=saldo_novo,
                motivo_observacao=f"Atendimento do Pedido #{pedido.numero_pedido} ({pedido.nome_solicitante})",
                usuario_id=current_user.id
            )
            db.session.add(mov)

        pedido.data_conclusao = datetime.now()
        flash(f'Pedido #{pedido.numero_pedido} baixado do estoque e entregue com sucesso!', 'success')

    db.session.commit()
    return redirect(url_for('listar_requisicoes_estoque'))


# -----------------------------------------------------------------------------
# CANAL PÚBLICO EXTERNO: REQUISIÇÃO DE ALMOXARIFADO DA EQUIPE (SEM LOGIN)
# -----------------------------------------------------------------------------
@app.route('/almoxarifado/requisicao/<token>', methods=['GET', 'POST'])
def requisicao_almoxarifado_externa(token):
    empresa = Empresa.query.filter_by(token_requisicao_equipe=token).first_or_404()

    if request.method == 'POST':
        try:
            solicitante = request.form.get('nome_solicitante', '').strip()
            contato = request.form.get('contato_solicitante', '').strip()
            setor_obra = request.form.get('setor_obra_destino', '').strip()
            obs = request.form.get('observacoes', '').strip()

            produtos_ids = request.form.getlist('produto_id[]')
            quantidades = request.form.getlist('quantidade[]')

            total_existentes = PedidoRequisicao.query.filter_by(empresa_id=empresa.id).count() + 1
            num_ped = f"REQ-{datetime.now().year}-{total_existentes:04d}"

            novo_pedido = PedidoRequisicao(
                empresa_id=empresa.id,
                numero_pedido=num_ped,
                tipo_origem='requisicao_interna',
                nome_solicitante=solicitante,
                contato_solicitante=contato,
                setor_obra_destino=setor_obra,
                observacoes=obs,
                status='pendente'
            )
            db.session.add(novo_pedido)
            db.session.flush()

            for p_id, qtd_str in zip(produtos_ids, quantidades):
                if p_id and qtd_str and float(qtd_str) > 0:
                    prod = ProdutoEstoque.query.get(int(p_id))
                    item_req = ItemPedidoRequisicao(
                        pedido_id=novo_pedido.id,
                        produto_id=int(p_id),
                        quantidade_solicitada=float(qtd_str),
                        preco_unitario=prod.preco_venda_sugerido if prod else 0.0,
                        valor_total=float(qtd_str) * (prod.preco_venda_sugerido if prod else 0.0)
                    )
                    db.session.add(item_req)

            db.session.commit()
            return render_template('publico/requisicao_concluida.html', empresa=empresa, pedido=novo_pedido)
        except Exception as e:
            db.session.rollback()
            return f"Erro ao submeter requisição: {str(e)}", 500

    produtos_disponiveis = ProdutoEstoque.query.filter_by(
        empresa_id=empresa.id,
        ativo=True
    ).filter(ProdutoEstoque.quantidade_atual > 0).order_by(ProdutoEstoque.nome.asc()).all()

    return render_template(
        'publico/requisicao_almoxarifado.html',
        empresa=empresa,
        produtos=produtos_disponiveis
    )

# =============================================================================
# MÓDULO DEDICADO: VENDAS DE PRODUTOS & MERCADORIAS
# =============================================================================

@app.route('/vendas')
@login_required
def listar_vendas():
    if not (current_user.empresa.modulo_estoque or current_user.empresa.modulo_vendas_externas) and current_user.nivel_acesso != 'master':
        flash('O Módulo de Vendas de Produtos não está ativo no seu plano. Habilite-o na aba de assinaturas.', 'warning')
        return redirect(url_for('perfil_empresa') + '#tab-planos')

    filtro = request.args.get('status', 'todos')
    query = PedidoRequisicao.query.filter_by(
        empresa_id=current_user.empresa_id
    ).filter(PedidoRequisicao.tipo_origem.in_(['venda_balcao', 'venda_web']))

    if filtro == 'pendente':
        query = query.filter_by(status='pendente')
    elif filtro == 'aprovado':
        query = query.filter(PedidoRequisicao.status.in_(['em_separacao', 'conferido']))
    elif filtro == 'concluido':
        query = query.filter_by(status='entregue')

    pedidos = query.order_by(PedidoRequisicao.data_solicitacao.desc()).all()

    # Indicadores
    total_vendas = sum(p.valor_total for p in pedidos if p.status == 'entregue')
    total_aberto = sum(p.valor_total for p in pedidos if p.status in ['pendente', 'em_separacao', 'conferido'])
    
    clientes = Cliente.query.filter_by(empresa_id=current_user.empresa_id).order_by(Cliente.nome.asc()).all()
    produtos = ProdutoEstoque.query.filter_by(empresa_id=current_user.empresa_id, ativo=True).order_by(ProdutoEstoque.nome.asc()).all()

    # Garante o slug da loja e cria o link externo completo
    empresa = current_user.empresa
    if not getattr(empresa, 'slug_loja', None):
        empresa.slug_loja = f"loja-{empresa.id}-{secrets.token_hex(4)}"
        db.session.commit()

    link_loja = url_for('portal_pedido_venda_cliente', slug_loja=empresa.slug_loja, _external=True)

    return render_template(
        'vendas.html',
        pedidos=pedidos,
        filtro=filtro,
        total_vendas=total_vendas,
        total_aberto=total_aberto,
        clientes=clientes,
        produtos=produtos,
        link_loja=link_loja
    )


@app.route('/vendas/nova', methods=['POST'])
@login_required
def criar_venda_produto():
    try:
        cliente_id = request.form.get('cliente_id')
        cli_obj = Cliente.query.get(int(cliente_id)) if cliente_id and cliente_id.isdigit() else None
        
        nome_comprador = cli_obj.nome if cli_obj else request.form.get('nome_solicitante', 'Venda Balcão').strip()
        contato = cli_obj.telefone if cli_obj else request.form.get('contato_solicitante', '').strip()
        endereco_entrega = request.form.get('endereco_entrega', '').strip()
        obs = request.form.get('observacoes', '').strip()
        
        # Regras Financeiras e Condições de Pagamento
        gerar_financeiro = bool(request.form.get('gerar_financeiro'))
        exige_entrada = request.form.get('exige_entrada') in ['1', 'true', 'on']
        valor_entrada = float(request.form.get('valor_entrada') or 0.0) if exige_entrada else 0.0
        forma_pagamento_entrada = request.form.get('forma_pagamento_entrada', 'PIX')
        qtd_parcelas = int(request.form.get('qtd_parcelas') or 1)
        forma_pagamento_parcelas = request.form.get('forma_pagamento_parcelas', 'Boleto Bancário')
        intervalo_dias = int(request.form.get('intervalo_dias') or 30)

        produtos_ids = request.form.getlist('produto_id[]')
        quantidades = request.form.getlist('quantidade[]')
        valores = request.form.getlist('valor_unitario[]')

        total_existentes = PedidoRequisicao.query.filter_by(empresa_id=current_user.empresa_id).count() + 1
        num_pedido = f"PED-{datetime.now().year}-{total_existentes:04d}"

        # Se exigir entrada maior que zero, nasce bloqueado aguardando o pagamento do sinal
        status_inicial_pedido = 'bloqueado_pagamento' if (exige_entrada and valor_entrada > 0) else 'em_separacao'

        novo_pedido = PedidoRequisicao(
            empresa_id=current_user.empresa_id,
            cliente_id=cli_obj.id if cli_obj else None,
            numero_pedido=num_pedido,
            tipo_origem='venda_balcao',
            nome_solicitante=nome_comprador,
            contato_solicitante=contato,
            setor_obra_destino=endereco_entrega,
            observacoes=obs,
            status=status_inicial_pedido,
            valor_total=0.0,
            exige_entrada=exige_entrada,
            valor_entrada=valor_entrada,
            forma_pagamento_entrada=forma_pagamento_entrada,
            qtd_parcelas=qtd_parcelas,
            forma_pagamento_parcelas=forma_pagamento_parcelas,
            intervalo_dias=intervalo_dias
        )
        db.session.add(novo_pedido)
        db.session.flush()

        valor_total_pedido = 0.0

        for p_id, q_str, v_str in zip(produtos_ids, quantidades, valores):
            if p_id and q_str and float(q_str) > 0:
                prod = ProdutoEstoque.query.get(int(p_id))
                qtd = float(q_str)
                unit = float(v_str or (prod.preco_venda_sugerido if prod else 0.0))
                subtotal = round(qtd * unit, 2)
                valor_total_pedido += subtotal

                item = ItemPedidoRequisicao(
                    pedido_id=novo_pedido.id,
                    produto_id=int(p_id),
                    quantidade_solicitada=qtd,
                    preco_unitario=unit,
                    valor_total=subtotal
                )
                db.session.add(item)

        novo_pedido.valor_total = round(valor_total_pedido, 2)

        # GERAÇÃO INTEGRADA NO MÓDULO FINANCEIRO (PARCELAS E ENTRADA)
        if gerar_financeiro and valor_total_pedido > 0:
            hoje = date.today()
            fatura = Fatura(
                empresa_id=current_user.empresa_id,
                cliente_id=cli_obj.id if cli_obj else None,
                descricao=f"Venda de Mercadorias - Pedido #{novo_pedido.numero_pedido}",
                valor_total=valor_total_pedido,
                data_emissao=hoje
            )
            db.session.add(fatura)
            db.session.flush()
            novo_pedido.fatura_id = fatura.id

            saldo_parcelar = max(0.0, valor_total_pedido - valor_entrada)
            total_titulos = (1 if (exige_entrada and valor_entrada > 0) else 0) + (qtd_parcelas if saldo_parcelar > 0 else 0)
            num_seq = 1

            # 1. Parcela de Entrada
            if exige_entrada and valor_entrada > 0:
                p_entrada = ParcelaFatura(
                    empresa_id=current_user.empresa_id,
                    fatura_id=fatura.id,
                    numero_parcela=num_seq,
                    total_parcelas=total_titulos,
                    descricao_parcela="Sinal / Entrada Venda",
                    is_entrada=True,
                    forma_pagamento=forma_pagamento_entrada,
                    valor=valor_entrada,
                    data_vencimento=hoje + timedelta(days=3),
                    status="A Faturar"
                )
                db.session.add(p_entrada)
                num_seq += 1

            # 2. Saldo Parcelado
            if saldo_parcelar > 0:
                valor_cada_parcela = round(saldo_parcelar / qtd_parcelas, 2)
                for i in range(1, qtd_parcelas + 1):
                    p_normal = ParcelaFatura(
                        empresa_id=current_user.empresa_id,
                        fatura_id=fatura.id,
                        numero_parcela=num_seq,
                        total_parcelas=total_titulos,
                        descricao_parcela=f"Parcela {i}/{qtd_parcelas}" if qtd_parcelas > 1 else "Parcela Única",
                        is_entrada=False,
                        forma_pagamento=forma_pagamento_parcelas,
                        valor=valor_cada_parcela,
                        data_vencimento=hoje + timedelta(days=i * intervalo_dias),
                        status="A Faturar"
                    )
                    db.session.add(p_normal)
                    num_seq += 1

        db.session.commit()
        
        if status_inicial_pedido == 'bloqueado_pagamento':
            flash(f'Pedido #{novo_pedido.numero_pedido} criado! Status: BLOQUEADO aguardando o pagamento do sinal de R$ {valor_entrada:,.2f}.', 'warning')
        else:
            flash(f'Pedido #{novo_pedido.numero_pedido} criado e liberado para a esteira de expedição!', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao registrar venda: {str(e)}', 'danger')

    return redirect(url_for('listar_vendas'))


@app.route('/vendas/<int:id>/aprovar-expedir', methods=['POST'])
@login_required
def aprovar_expedir_venda(id):
    pedido = PedidoRequisicao.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()

    # Validação de estoque para todos os itens antes da baixa
    for item in pedido.itens:
        prod = item.produto
        if float(prod.quantidade_atual or 0) < float(item.quantidade_solicitada or 0):
            flash(f'Estoque insuficiente para "{prod.nome}". Disponível: {prod.quantidade_atual} {prod.unidade_medida}, Solicitado: {item.quantidade_solicitada}.', 'danger')
            return redirect(url_for('listar_vendas'))

    # Efetua a baixa e gera histórico Kardex
    for item in pedido.itens:
        prod = item.produto
        qtd_baixa = float(item.quantidade_solicitada)
        saldo_anterior = float(prod.quantidade_atual or 0)
        saldo_novo = saldo_anterior - qtd_baixa

        prod.quantidade_atual = saldo_novo
        item.quantidade_atendida = qtd_baixa

        mov = MovimentacaoEstoque(
            empresa_id=current_user.empresa_id,
            produto_id=prod.id,
            tipo_movimento='saida_venda',
            quantidade=qtd_baixa,
            saldo_anterior=saldo_anterior,
            saldo_posterior=saldo_novo,
            motivo_observacao=f"Expedição Venda #{pedido.numero_pedido} ({pedido.nome_solicitante})",
            usuario_id=current_user.id
        )
        db.session.add(mov)

    pedido.status = 'entregue'
    pedido.data_conclusao = datetime.now()
    db.session.commit()

    flash(f'Venda #{pedido.numero_pedido} aprovada, despachada e estoque baixado!', 'success')
    return redirect(url_for('listar_vendas'))

# -----------------------------------------------------------------------------
# ANEXOS DO PEDIDO (NF E BOLETO NA MESMA LINHA)
# -----------------------------------------------------------------------------
@app.route('/vendas/pedido/<int:id>/anexos', methods=['POST'])
@login_required
def atualizar_anexos_pedido_venda(id):
    pedido = PedidoRequisicao.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    if 'arquivo_nf' in request.files:
        f_nf = request.files['arquivo_nf']
        if f_nf and f_nf.filename:
            if pedido.arquivo_nf:
                excluir_arquivo_supabase(pedido.arquivo_nf)
            pedido.arquivo_nf = salvar_arquivo_supabase(f_nf, 'notas_fiscais_vendas', current_user.empresa_id)

    if 'arquivo_boleto' in request.files:
        f_bol = request.files['arquivo_boleto']
        if f_bol and f_bol.filename:
            if pedido.arquivo_boleto:
                excluir_arquivo_supabase(pedido.arquivo_boleto)
            pedido.arquivo_boleto = salvar_arquivo_supabase(f_bol, 'boletos_vendas', current_user.empresa_id)

    db.session.commit()
    flash(f'Anexos do Pedido #{pedido.numero_pedido} atualizados com sucesso!', 'success')
    return redirect(request.referrer or url_for('listar_vendas'))


# -----------------------------------------------------------------------------
# CONFIRMAÇÃO DO PROTOCOLO DE ENTREGA COM ASSINATURA E CONFERÊNCIA
# -----------------------------------------------------------------------------
@app.route('/vendas/pedido/<int:id>/confirmar-entrega', methods=['POST'])
@login_required
def confirmar_protocolo_entrega(id):
    pedido = PedidoRequisicao.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()

    pedido.recebido_por_nome = request.form.get('recebido_por_nome', '').strip()
    pedido.recebido_por_documento = request.form.get('recebido_por_documento', '').strip()
    pedido.assinatura_entrega_base64 = request.form.get('assinatura_base64')
    pedido.data_entrega_realizada = datetime.now()

    foto = request.files.get('foto_comprovante')
    if foto and foto.filename:
        pedido.foto_comprovante_entrega = salvar_arquivo_supabase(foto, 'entregas_vendas', current_user.empresa_id)

    if pedido.status != 'entregue':
        for item in pedido.itens:
            prod = item.produto
            qtd_baixa = float(item.quantidade_solicitada or 0.0)
            saldo_ant = float(prod.quantidade_atual or 0.0)
            prod.quantidade_atual = max(0.0, saldo_ant - qtd_baixa)
            item.quantidade_atendida = qtd_baixa

            mov = MovimentacaoEstoque(
                empresa_id=current_user.empresa_id,
                produto_id=prod.id,
                tipo_movimento='saida_venda',
                quantidade=qtd_baixa,
                saldo_anterior=saldo_ant,
                saldo_posterior=prod.quantidade_atual,
                motivo_observacao=f"Entrega/Conferência Pedido #{pedido.numero_pedido} - Recebido por: {pedido.recebido_por_nome}",
                usuario_id=current_user.id
            )
            db.session.add(mov)

        pedido.status = 'entregue'
        pedido.data_conclusao = datetime.now()

    db.session.commit()
    flash(f'Protocolo de Entrega do Pedido #{pedido.numero_pedido} finalizado com sucesso!', 'success')
    return redirect(request.referrer or url_for('listar_vendas'))


# -----------------------------------------------------------------------------
# IMPRESSÃO 1: ROMANEIO DE SEPARAÇÃO INTERNA DO ESTOQUE (SEM PREÇOS / IMAGENS)
# -----------------------------------------------------------------------------
@app.route('/vendas/pedido/<int:id>/pdf-separacao')
@login_required
def gerar_pdf_romaneio_separacao(id):
    pedido = PedidoRequisicao.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    empresa = current_user.empresa
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    elementos = []
    styles = getSampleStyleSheet()

    cor_marca = colors.HexColor(empresa.cor_primaria or "#1e3a8a")
    estilo_tit = ParagraphStyle('TitSep', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=cor_marca)
    estilo_sub = ParagraphStyle('SubSep', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor("#475569"))
    estilo_corpo = ParagraphStyle('CorpoSep', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=12, textColor=colors.HexColor("#1e293b"))
    estilo_corpo_bold = ParagraphStyle('CorpoBSep', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=12, textColor=colors.HexColor("#0f172a"))

    topo = [
        [
            Paragraph(f"<b>{_limpar_texto(empresa.razao_social).upper()}</b><br/><font size='8'>CONTROLE INTERNO DE ESTOQUE & EXPEDIÇÃO</font>", estilo_tit),
            Paragraph(f"<b>GUIA DE SEPARAÇÃO: #{pedido.numero_pedido}</b><br/>Emissão: {datetime.now().strftime('%d/%m/%Y %H:%M')}", estilo_sub)
        ]
    ]
    tab_topo = Table(topo, colWidths=[4.5*inch, 3.0*inch])
    tab_topo.setStyle(TableStyle([('ALIGN', (1,0), (1,0), 'RIGHT'), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
    elementos.append(tab_topo)
    elementos.append(Spacer(1, 4))
    elementos.append(HRFlowable(width="100%", thickness=1.5, color=cor_marca, spaceAfter=10))

    origem_txt = "VENDA WEB / PORTAL B2B" if pedido.tipo_origem == 'venda_web' else "BALCÃO / PEDIDO INTERNO"
    dados_solic = [
        [Paragraph(f"<b>SOLICITANTE / CLIENTE:</b> {_limpar_texto(pedido.nome_solicitante)}", estilo_corpo_bold), Paragraph(f"<b>ORIGEM:</b> {origem_txt}", estilo_corpo)],
        [Paragraph(f"<b>SETOR / DESTINO:</b> {_limpar_texto(pedido.setor_obra_destino or 'Retirada no Balcão')}", estilo_corpo), Paragraph(f"<b>CONTATO:</b> {_limpar_texto(pedido.contato_solicitante or '--')}", estilo_corpo)],
        [Paragraph(f"<b>OBSERVAÇÕES:</b> {_limpar_texto(pedido.observacoes or 'Nenhuma recomendação registrada.')}", estilo_corpo), Paragraph("", estilo_corpo)]
    ]
    tab_dados = Table(dados_solic, colWidths=[4.8*inch, 2.7*inch])
    tab_dados.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#f1f5f9")),
        ('PADDING', (0,0), (-1,-1), 5)
    ]))
    elementos.append(tab_dados)
    elementos.append(Spacer(1, 10))

    elementos.append(Paragraph("<b>ITENS PARA CONFERÊNCIA E SEPARAÇÃO NO ESTOQUE</b>", estilo_tit))
    elementos.append(Spacer(1, 4))

    itens_tabela = [
        [
            Paragraph("<b>CONF.</b>", estilo_corpo_bold),
            Paragraph("<b>CÓDIGO / SKU</b>", estilo_corpo_bold),
            Paragraph("<b>DESCRIÇÃO DO MATERIAL / PRODUTO</b>", estilo_corpo_bold),
            Paragraph("<b>UNIDADE</b>", estilo_corpo_bold),
            Paragraph("<b>QTD SOLICITADA</b>", estilo_corpo_bold)
        ]
    ]

    for it in pedido.itens:
        prod = it.produto
        sku_txt = _limpar_texto(prod.codigo_sku or '--') if prod else '--'
        nome_prod = _limpar_texto(prod.nome) if prod else 'Produto Desconhecido'
        unid = _limpar_texto(prod.unidade_medida) if prod else 'un'

        itens_tabela.append([
            Paragraph("[  ]", estilo_corpo_bold),
            Paragraph(sku_txt, estilo_corpo),
            Paragraph(nome_prod, estilo_corpo),
            Paragraph(unid.upper(), estilo_corpo),
            Paragraph(f"<b>{it.quantidade_solicitada}</b>", estilo_corpo_bold)
        ])

    tab_itens = Table(itens_tabela, colWidths=[0.6*inch, 1.4*inch, 3.8*inch, 0.8*inch, 0.9*inch])
    tab_itens.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('ALIGN', (0,1), (0,-1), 'CENTER'),
        ('ALIGN', (3,1), (-1,-1), 'CENTER'),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    elementos.append(tab_itens)
    elementos.append(Spacer(1, 40))

    elementos.append(Table([
        [
            Paragraph("____________________________________________<br/><b>RESPONSÁVEL PELA SEPARAÇÃO</b><br/>Almoxarifado / Estoque", estilo_corpo),
            Paragraph("____________________________________________<br/><b>CONFERIDO POR (EXPEDIÇÃO)</b><br/>Data: ____/____/________", estilo_corpo)
        ]
    ], colWidths=[3.75*inch, 3.75*inch], style=[('ALIGN', (0,0), (-1,-1), 'CENTER')]))

    doc.build(elementos)
    buffer.seek(0)
    return send_file(buffer, as_attachment=False, download_name=f"Separacao_Pedido_{pedido.numero_pedido}.pdf", mimetype='application/pdf')


# -----------------------------------------------------------------------------
# IMPRESSÃO 2: NOTA DE ENTREGA & PROTOCOLO DO CLIENTE (COM VALORES E CANHOTO)
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# IMPRESSÃO DE ORÇAMENTO / PEDIDO DE VENDA COMERCIAL
# -----------------------------------------------------------------------------
@app.route('/vendas/pedido/<int:id>/pdf-orcamento')
@login_required
def gerar_pdf_orcamento_venda(id):
    pedido = PedidoRequisicao.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    empresa = current_user.empresa
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer, 
        pagesize=letter, 
        rightMargin=36, 
        leftMargin=36, 
        topMargin=36, 
        bottomMargin=36
    )
    elementos = []
    styles = getSampleStyleSheet()

    cor_marca = colors.HexColor(empresa.cor_primaria or "#1e3a8a")
    estilo_emp_nome = ParagraphStyle('EmpNome', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=cor_marca)
    estilo_emp_sub = ParagraphStyle('EmpSub', parent=styles['Normal'], fontName='Helvetica', fontSize=7.5, leading=10, textColor=colors.HexColor("#475569"))
    estilo_secao = ParagraphStyle('SecTit', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9.5, leading=13, textColor=cor_marca)
    estilo_corpo = ParagraphStyle('Corpo', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=12, textColor=colors.HexColor("#1e293b"))
    estilo_corpo_bold = ParagraphStyle('CorpoB', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=12, textColor=colors.HexColor("#0f172a"))
    
    # Estilo específico para o cabeçalho escuro da tabela (texto em branco)
    estilo_th = ParagraphStyle(
        'ThTabelaBranco',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.white
    )

    logo_elemento = _obter_logo_reportlab(empresa.logo_filename, width=1.5*inch, height=0.6*inch)
    info_emp = f"<b>{_limpar_texto(empresa.razao_social).upper()}</b><br/>CNPJ/CPF: {_limpar_texto(empresa.cnpj or '--')} | Tel: {_limpar_texto(empresa.telefone or '--')}<br/>{_limpar_texto(empresa.endereco_completo or '')}"
    
    if logo_elemento:
        tab_topo = Table([[logo_elemento, Paragraph(info_emp, estilo_emp_sub)]], colWidths=[1.8*inch, 5.7*inch])
    else:
        tab_topo = Table([[Paragraph(f"<b>{_limpar_texto(empresa.razao_social).upper()}</b>", estilo_emp_nome), Paragraph(info_emp, estilo_emp_sub)]], colWidths=[2.8*inch, 4.7*inch])
    
    tab_topo.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (1,0), (1,0), 'RIGHT')]))
    elementos.append(tab_topo)
    elementos.append(Spacer(1, 4))
    elementos.append(HRFlowable(width="100%", thickness=1.5, color=cor_marca, spaceAfter=8))

    elementos.append(Paragraph(f"<b>ORÇAMENTO / PEDIDO DE MERCADORIAS Nº #{pedido.numero_pedido}</b>", estilo_secao))
    elementos.append(Spacer(1, 4))

    dados_cli = [
        [
            Paragraph(f"<b>CLIENTE / COMPRADOR:</b> {_limpar_texto(pedido.nome_solicitante)}", estilo_corpo_bold),
            Paragraph(f"<b>DATA DO PEDIDO:</b> {pedido.data_solicitacao.strftime('%d/%m/%Y') if pedido.data_solicitacao else '--'}", estilo_corpo)
        ],
        [
            Paragraph(f"<b>DESTINO / ENTREGA:</b> {_limpar_texto(pedido.setor_obra_destino or 'Retirada no Balcão')}", estilo_corpo),
            Paragraph(f"<b>CONTATO / TEL:</b> {_limpar_texto(pedido.contato_solicitante or '--')}", estilo_corpo)
        ]
    ]
    tab_cli = Table(dados_cli, colWidths=[4.8*inch, 2.7*inch], style=[
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#f1f5f9")),
        ('PADDING', (0,0), (-1,-1), 5)
    ])
    elementos.append(tab_cli)
    elementos.append(Spacer(1, 10))

    elementos.append(Paragraph("<b>DISCRIMINAÇÃO DOS ITENS SOLICITADOS</b>", estilo_secao))
    elementos.append(Spacer(1, 4))

    dados_itens = [
        [
            Paragraph("<b>Item</b>", estilo_th),
            Paragraph("<b>Descrição do Produto</b>", estilo_th),
            Paragraph("<b>Qtd</b>", estilo_th),
            Paragraph("<b>Valor Unit.</b>", estilo_th),
            Paragraph("<b>Subtotal</b>", estilo_th)
        ]
    ]

    for idx, it in enumerate(pedido.itens, 1):
        nome_prod = _limpar_texto(it.produto.nome if it.produto else 'Item')
        unid = _limpar_texto(it.produto.unidade_medida if it.produto else 'un')
        dados_itens.append([
            Paragraph(f"{idx:02d}", estilo_corpo),
            Paragraph(nome_prod, estilo_corpo),
            Paragraph(f"{it.quantidade_solicitada} {unid}", estilo_corpo),
            Paragraph(f"R$ {it.preco_unitario:,.2f}", estilo_corpo),
            Paragraph(f"R$ {it.valor_total:,.2f}", estilo_corpo_bold)
        ])

    # Linha do Total Geral com mesclagem horizontal (SPAN)
    dados_itens.append([
        Paragraph("<b>TOTAL GERAL DO PEDIDO</b>", estilo_corpo_bold),
        "",
        "",
        "",
        Paragraph(f"<b>R$ {pedido.valor_total:,.2f}</b>", estilo_corpo_bold)
    ])

    tab_it = Table(dados_itens, colWidths=[0.5*inch, 4.0*inch, 1.0*inch, 1.0*inch, 1.0*inch])
    tab_it.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
        ('ALIGN', (2,0), (-1,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-2), 0.5, colors.HexColor("#cbd5e1")),
        ('PADDING', (0,0), (-1,-1), 5),
        
        # Unifica as 4 primeiras colunas da última linha para não esmagar o texto
        ('SPAN', (0, -1), (3, -1)),
        ('ALIGN', (0, -1), (3, -1), 'RIGHT'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
        ('LINEABOVE', (0, -1), (-1, -1), 1.2, colors.HexColor("#0f172a")),
        ('BOX', (0, -1), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
    ]))
    elementos.append(tab_it)
    elementos.append(Spacer(1, 14))

    # Condições de Pagamento
    elementos.append(Paragraph("<b>CONDIÇÕES COMERCIAIS & PAGAMENTO</b>", estilo_secao))
    cond_txt = f"• <b>Forma de Pagamento:</b> {'Sinal de R$ ' + ('%.2f' % pedido.valor_entrada) + ' + ' + str(pedido.qtd_parcelas) + 'x de saldo (' + pedido.forma_pagamento_parcelas + ')' if pedido.exige_entrada and pedido.valor_entrada > 0 else str(pedido.qtd_parcelas) + 'x via ' + (pedido.forma_pagamento_parcelas or 'Boleto')}"
    if pedido.observacoes:
        cond_txt += f"<br/>• <b>Observações:</b> {_limpar_texto(pedido.observacoes)}"
    
    tab_cond = Table([[Paragraph(cond_txt, estilo_corpo)]], colWidths=[7.5*inch])
    tab_cond.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('PADDING', (0,0), (-1,-1), 6)
    ]))
    elementos.append(tab_cond)
    elementos.append(Spacer(1, 40))

    elementos.append(Table([
        [
            Paragraph(f"____________________________________________<br/><b>{_limpar_texto(empresa.razao_social).upper()}</b><br/>Departamento Comercial", estilo_corpo),
            Paragraph("____________________________________________<br/><b>DE ACORDO DO CLIENTE</b><br/>Aprovação / Data: ____/____/________", estilo_corpo)
        ]
    ], colWidths=[3.75*inch, 3.75*inch], style=[('ALIGN', (0,0), (-1,-1), 'CENTER')]))

    doc.build(elementos)
    buffer.seek(0)
    return send_file(
        buffer, 
        as_attachment=False, 
        download_name=f"Orcamento_Pedido_{pedido.numero_pedido}.pdf", 
        mimetype='application/pdf'
    )

# =============================================================================
# FLUXO DE VENDAS (COMERCIAL)
# =============================================================================

@app.route('/vendas/pedido/<int:id>/enviar-expedicao', methods=['POST'])
@login_required
def enviar_pedido_para_expedicao(id):
    pedido = PedidoRequisicao.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    pedido.status = 'em_separacao'
    db.session.commit()
    flash(f'Pedido #{pedido.numero_pedido} enviado com sucesso para a fila de expedição!', 'success')
    return redirect(url_for('listar_vendas'))

@app.route('/vendas/pedido/<int:id>/excluir', methods=['POST'])
@login_required
def excluir_pedido_venda(id):
    pedido = PedidoRequisicao.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()

    # Trava de segurança: só permite excluir se estiver pendente/orçamento
    if pedido.status not in ['pendente', 'bloqueado_pagamento']:
        flash('Não é possível excluir este pedido pois ele já avançou para a expedição ou faturamento.', 'danger')
        return redirect(url_for('listar_vendas'))

    try:
        # Se houver fatura vinculada em aberto, remove também
        if pedido.fatura_vinculada:
            db.session.delete(pedido.fatura_vinculada)

        db.session.delete(pedido)
        db.session.commit()
        flash(f'Orçamento / Pedido #{pedido.numero_pedido} excluído com sucesso!', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir pedido: {str(e)}', 'danger')

    return redirect(url_for('listar_vendas'))

# -----------------------------------------------------------------------------
# COMPROVATIVO FORMAL DE ENTREGA ASSINADO (PDF REPORTLAB)
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# COMPROVATIVO FORMAL DE ENTREGA ASSINADO (PDF REPORTLAB)
# -----------------------------------------------------------------------------
@app.route('/vendas/pedido/<int:id>/pdf-comprovativo-entrega')
@login_required
def gerar_pdf_comprovativo_entrega(id):
    pedido = PedidoRequisicao.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    empresa = current_user.empresa
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer, 
        pagesize=letter, 
        rightMargin=36, 
        leftMargin=36, 
        topMargin=36, 
        bottomMargin=36
    )
    elementos = []
    styles = getSampleStyleSheet()

    cor_marca = colors.HexColor(empresa.cor_primaria or "#1e3a8a")
    estilo_emp_nome = ParagraphStyle('EmpNome', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=cor_marca)
    estilo_emp_sub = ParagraphStyle('EmpSub', parent=styles['Normal'], fontName='Helvetica', fontSize=7.5, leading=10, textColor=colors.HexColor("#475569"))
    estilo_sub = ParagraphStyle('SubLegenda', parent=styles['Normal'], fontName='Helvetica', fontSize=7.5, leading=10, textColor=colors.HexColor("#475569"), alignment=1)
    estilo_secao = ParagraphStyle('SecTit', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9.5, leading=13, textColor=cor_marca)
    estilo_corpo = ParagraphStyle('Corpo', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=12, textColor=colors.HexColor("#1e293b"))
    estilo_corpo_bold = ParagraphStyle('CorpoB', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=12, textColor=colors.HexColor("#0f172a"))
    estilo_th = ParagraphStyle('ThBranco', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=11, textColor=colors.white)

    # 1. Cabeçalho da Empresa
    logo_elemento = _obter_logo_reportlab(empresa.logo_filename, width=1.5*inch, height=0.6*inch)
    info_emp = f"<b>{_limpar_texto(empresa.razao_social).upper()}</b><br/>CNPJ/CPF: {_limpar_texto(empresa.cnpj or '--')} | Tel: {_limpar_texto(empresa.telefone or '--')}<br/>{_limpar_texto(empresa.endereco_completo or '')}"
    
    if logo_elemento:
        tab_topo = Table([[logo_elemento, Paragraph(info_emp, estilo_emp_sub)]], colWidths=[1.8*inch, 5.7*inch])
    else:
        tab_topo = Table([[Paragraph(f"<b>{_limpar_texto(empresa.razao_social).upper()}</b>", estilo_emp_nome), Paragraph(info_emp, estilo_emp_sub)]], colWidths=[2.8*inch, 4.7*inch])
    
    tab_topo.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (1,0), (1,0), 'RIGHT')]))
    elementos.append(tab_topo)
    elementos.append(Spacer(1, 4))
    elementos.append(HRFlowable(width="100%", thickness=1.5, color=cor_marca, spaceAfter=8))

    # 2. Título do Documento
    elementos.append(Paragraph(f"<b>COMPROVATIVO & PROTOCOLO DE ENTREGA • PEDIDO #{pedido.numero_pedido}</b>", estilo_secao))
    elementos.append(Spacer(1, 4))

    # 3. Painel de Dados da Entrega
    dt_entrega_str = pedido.data_entrega_realizada.strftime('%d/%m/%Y às %H:%M') if pedido.data_entrega_realizada else '--'
    dados_entrega = [
        [
            Paragraph(f"<b>DESTINATÁRIO:</b> {_limpar_texto(pedido.nome_solicitante)}", estilo_corpo_bold),
            Paragraph(f"<b>DATA DA ENTREGA:</b> {dt_entrega_str}", estilo_corpo)
        ],
        [
            Paragraph(f"<b>LOCAL / DESTINO:</b> {_limpar_texto(pedido.setor_obra_destino or 'Balcão')}", estilo_corpo),
            Paragraph(f"<b>MOTORISTA:</b> {_limpar_texto(pedido.motorista_responsavel.nome if pedido.motorista_responsavel else '--')}", estilo_corpo)
        ],
        [
            Paragraph(f"<b>RECEBIDO POR:</b> {_limpar_texto(pedido.recebido_por_nome or '--')}", estilo_corpo_bold),
            Paragraph(f"<b>DOCUMENTO / RG:</b> {_limpar_texto(pedido.recebido_por_documento or '--')}", estilo_corpo)
        ]
    ]
    tab_painel = Table(dados_entrega, colWidths=[4.8*inch, 2.7*inch], style=[
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#f1f5f9")),
        ('PADDING', (0,0), (-1,-1), 5)
    ])
    elementos.append(tab_painel)
    elementos.append(Spacer(1, 10))

    # 4. Tabela de Itens Entregues
    elementos.append(Paragraph("<b>MERCADORIAS CONFERIDAS E ENTREGUES</b>", estilo_secao))
    elementos.append(Spacer(1, 4))

    dados_itens = [
        [
            Paragraph("<b>Item</b>", estilo_th),
            Paragraph("<b>Descrição do Produto</b>", estilo_th),
            Paragraph("<b>Qtd Entregue</b>", estilo_th),
            Paragraph("<b>Subtotal</b>", estilo_th)
        ]
    ]

    for idx, it in enumerate(pedido.itens, 1):
        nome_prod = _limpar_texto(it.produto.nome if it.produto else 'Item')
        unid = _limpar_texto(it.produto.unidade_medida if it.produto else 'un')
        qtd_ent = it.quantidade_atendida or it.quantidade_solicitada
        dados_itens.append([
            Paragraph(f"{idx:02d}", estilo_corpo),
            Paragraph(nome_prod, estilo_corpo),
            Paragraph(f"{qtd_ent} {unid}", estilo_corpo),
            Paragraph(f"R$ {it.valor_total:,.2f}", estilo_corpo_bold)
        ])

    dados_itens.append([
        Paragraph("<b>VALOR TOTAL DA CARGA ENTREGUE</b>", estilo_corpo_bold),
        "",
        "",
        Paragraph(f"<b>R$ {pedido.valor_total:,.2f}</b>", estilo_corpo_bold)
    ])

    tab_it = Table(dados_itens, colWidths=[0.5*inch, 4.5*inch, 1.2*inch, 1.3*inch], style=[
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
        ('ALIGN', (2,0), (-1,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-2), 0.5, colors.HexColor("#cbd5e1")),
        ('SPAN', (0, -1), (2, -1)),
        ('ALIGN', (0, -1), (2, -1), 'RIGHT'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
        ('LINEABOVE', (0, -1), (-1, -1), 1.2, colors.HexColor("#0f172a")),
        ('PADDING', (0,0), (-1,-1), 5),
    ])
    elementos.append(tab_it)
    elementos.append(Spacer(1, 14))

    # 5. Assinatura Digital (Canvas Base64)
    if pedido.assinatura_entrega_base64 and 'base64,' in pedido.assinatura_entrega_base64:
        import base64
        try:
            raw_base64 = pedido.assinatura_entrega_base64.split('base64,')[1]
            img_bytes = BytesIO(base64.b64decode(raw_base64))
            img_assinatura = RLImage(img_bytes, width=2.5*inch, height=0.9*inch)
            img_assinatura.hAlign = 'CENTER'

            quadro_ass = [
                [Paragraph("<b>DECLARAÇÃO DE RECEBIMENTO & ASSINATURA DIGITAL</b>", estilo_corpo_bold)],
                [img_assinatura],
                [Paragraph(f"Recebido por: <b>{_limpar_texto(pedido.recebido_por_nome or 'Destinatário')}</b> — Doc: {_limpar_texto(pedido.recebido_por_documento or '--')}<br/><font size='7' color='#64748b'>Assinado digitalmente via Smartphone em {dt_entrega_str}</font>", estilo_sub)]
            ]
            tab_quadro_ass = Table(quadro_ass, colWidths=[7.5*inch], style=[
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
                ('PADDING', (0,0), (-1,-1), 6)
            ])
            elementos.append(tab_quadro_ass)
        except Exception as e:
            print(f"[AVISO ASSINATURA REPORTLAB]: {e}")
    else:
        elementos.append(Spacer(1, 20))
        elementos.append(Table([[
            Paragraph(f"____________________________________________<br/><b>{_limpar_texto(pedido.recebido_por_nome or 'RECEBEDOR')}</b><br/>Doc: {_limpar_texto(pedido.recebido_por_documento or '--')}", estilo_corpo)
        ]], colWidths=[7.5*inch], style=[('ALIGN', (0,0), (-1,-1), 'CENTER')]))

    doc.build(elementos)
    buffer.seek(0)
    nome_pdf = f"Comprovativo_Entrega_Pedido_{pedido.numero_pedido}.pdf"
    return send_file(buffer, as_attachment=False, download_name=nome_pdf, mimetype='application/pdf')

# =============================================================================
# FLUXO DE EXPEDIÇÃO & LOGÍSTICA (ALMOXARIFE / CHEFE DE EXPEDIÇÃO)
# =============================================================================

@app.route('/expedicao')
@login_required
def painel_expedicao():
    if not (current_user.nivel_acesso in ['admin', 'master'] or current_user.perm_expedicao or current_user.perm_estoque):
        flash('Acesso restrito ao setor de expedição e logística.', 'danger')
        return redirect(url_for('index'))

    status_filtro = request.args.get('status', 'todos')
    motorista_filtro = request.args.get('motorista_id', '')
    termo_busca = request.args.get('busca', '').strip()

    query = PedidoRequisicao.query.filter_by(empresa_id=current_user.empresa_id)

    # 1. Filtro por Estado
    if status_filtro == 'separacao':
        query = query.filter_by(status='em_separacao')
    elif status_filtro == 'em_rota':
        query = query.filter_by(status='em_rota')
    elif status_filtro == 'entregue':
        query = query.filter_by(status='entregue')
    else:
        query = query.filter(PedidoRequisicao.status.in_(['em_separacao', 'em_rota', 'entregue']))

    # 2. Filtro por Motorista
    if motorista_filtro == 'sem_motorista':
        query = query.filter(PedidoRequisicao.operador_id.is_(None))
    elif motorista_filtro.isdigit():
        query = query.filter_by(operador_id=int(motorista_filtro))

    # 3. Busca por Nome de Cliente, Nº Pedido ou Destino
    if termo_busca:
        from sqlalchemy import or_
        query = query.filter(
            or_(
                PedidoRequisicao.nome_solicitante.ilike(f'%{termo_busca}%'),
                PedidoRequisicao.numero_pedido.ilike(f'%{termo_busca}%'),
                PedidoRequisicao.setor_obra_destino.ilike(f'%{termo_busca}%')
            )
        )

    pedidos = query.order_by(PedidoRequisicao.ordem_entrega.asc(), PedidoRequisicao.data_solicitacao.desc()).all()
    motoristas = OperadorCampo.query.filter_by(empresa_id=current_user.empresa_id, ativo=True).all()

    for m in motoristas:
        m.gerar_token_se_necessario()
    db.session.commit()

    # Contadores globais da empresa
    pedidos_todos = PedidoRequisicao.query.filter_by(empresa_id=current_user.empresa_id).all()
    total_separacao = sum(1 for p in pedidos_todos if p.status == 'em_separacao')
    total_em_rota = sum(1 for p in pedidos_todos if p.status == 'em_rota')
    total_entregues = sum(1 for p in pedidos_todos if p.status == 'entregue')

    return render_template(
        'expedicao.html',
        pedidos=pedidos,
        motoristas=motoristas,
        status_filtro=status_filtro,
        motorista_filtro=motorista_filtro,
        termo_busca=termo_busca,
        total_separacao=total_separacao,
        total_em_rota=total_em_rota,
        total_entregues=total_entregues,
        hoje=date.today()
    )


@app.route('/expedicao/alocar-motorista/<int:id>', methods=['POST'])
@login_required
def alocar_motorista_pedido(id):
    pedido = PedidoRequisicao.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    motorista_id = request.form.get('motorista_id')
    data_entrega = request.form.get('data_agendada_entrega')
    ordem_entrega = request.form.get('ordem_entrega', 1)

    if motorista_id and motorista_id.isdigit():
        pedido.operador_id = int(motorista_id)
        pedido.status = 'em_rota'
    else:
        pedido.operador_id = None
        pedido.status = 'em_separacao'

    if data_entrega:
        pedido.data_agendada_entrega = datetime.strptime(data_entrega, '%Y-%m-%d').date()
    
    if ordem_entrega:
        pedido.ordem_entrega = int(ordem_entrega)

    db.session.commit()
    flash(f'Logística do Pedido #{pedido.numero_pedido} atualizada com sucesso!', 'success')
    return redirect(url_for('painel_expedicao'))


# =============================================================================
# ÁREA MOBILE DEDICADA DO ENTREGADOR / MOTORISTA (SEM LOGIN PESADO)
# =============================================================================

@app.route('/motorista/rota/<token>')
def painel_mobile_motorista(token):
    motorista = OperadorCampo.query.filter_by(token_acesso=token).first_or_404()
    empresa = motorista.empresa

    hoje = date.today()
    entregas = PedidoRequisicao.query.filter_by(
        empresa_id=empresa.id,
        operador_id=motorista.id
    ).filter(PedidoRequisicao.status.in_(['em_rota', 'entregue'])).order_by(
        PedidoRequisicao.ordem_entrega.asc(),
        PedidoRequisicao.id.asc()
    ).all()

    return render_template(
        'publico/painel_motorista.html',
        motorista=motorista,
        empresa=empresa,
        entregas=entregas,
        hoje=hoje
    )


@app.route('/motorista/reordenar-rota/<token>', methods=['POST'])
def reordenar_rota_motorista(token):
    motorista = OperadorCampo.query.filter_by(token_acesso=token).first_or_404()
    dados = request.get_json(silent=True) or {}
    ordem_pedidos = dados.get('ordem_pedidos', []) # Lista de IDs na nova ordem

    for index, p_id in enumerate(ordem_pedidos, 1):
        ped = PedidoRequisicao.query.filter_by(id=p_id, operador_id=motorista.id).first()
        if ped:
            ped.ordem_entrega = index

    db.session.commit()
    return jsonify({'status': 'success', 'mensagem': 'Ordem das entregas atualizada!'})


@app.route('/motorista/concluir-entrega/<int:id>', methods=['POST'])
def motorista_finalizar_entrega(id):
    pedido = PedidoRequisicao.query.get_or_404(id)

    pedido.recebido_por_nome = request.form.get('recebido_por_nome', '').strip()
    pedido.recebido_por_documento = request.form.get('recebido_por_documento', '').strip()
    pedido.assinatura_entrega_base64 = request.form.get('assinatura_base64')
    pedido.data_entrega_realizada = datetime.now()

    foto = request.files.get('foto_comprovante')
    if foto and foto.filename:
        pedido.foto_comprovante_entrega = salvar_arquivo_supabase(foto, 'entregas_vendas', pedido.empresa_id)

    # Baixa no estoque
    if pedido.status != 'entregue':
        for item in pedido.itens:
            prod = item.produto
            qtd_baixa = float(item.quantidade_solicitada or 0.0)
            saldo_ant = float(prod.quantidade_atual or 0.0)
            prod.quantidade_atual = max(0.0, saldo_ant - qtd_baixa)
            item.quantidade_atendida = qtd_baixa

            mov = MovimentacaoEstoque(
                empresa_id=pedido.empresa_id,
                produto_id=prod.id,
                tipo_movimento='saida_venda',
                quantidade=qtd_baixa,
                saldo_anterior=saldo_ant,
                saldo_posterior=prod.quantidade_atual,
                motivo_observacao=f"Entrega Rota Motorista - Pedido #{pedido.numero_pedido} (Recebido por: {pedido.recebido_por_nome})",
                usuario_id=None
            )
            db.session.add(mov)

        pedido.status = 'entregue'
        pedido.data_conclusao = datetime.now()

    db.session.commit()
    token = pedido.motorista_responsavel.token_acesso if pedido.motorista_responsavel else ''
    return redirect(url_for('painel_mobile_motorista', token=token))

# =============================================================================
# MÓDULO EXCLUSIVO: GESTÃO DE MOTORISTAS & FROTAS
# =============================================================================

@app.route('/motoristas', methods=['GET', 'POST'])
@login_required
def gestao_motoristas():
    if not (current_user.nivel_acesso in ['admin', 'master'] or current_user.perm_expedicao):
        flash('Acesso restrito ao setor de logística e expedição.', 'danger')
        return redirect(url_for('index'))

    # CADASTRO DE NOVO MOTORISTA
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        telefone = re.sub(r'\D', '', request.form.get('telefone', ''))
        placa = request.form.get('veiculo_placa', '').strip().upper()
        documento = request.form.get('documento_registro', '').strip()
        email = request.form.get('email', '').strip().lower()

        if not nome or not telefone:
            flash('Nome e WhatsApp do motorista são obrigatórios.', 'warning')
            return redirect(url_for('gestao_motoristas'))

        novo_motorista = OperadorCampo(
            empresa_id=current_user.empresa_id,
            nome=nome,
            cargo='Motorista / Entregador',
            telefone=telefone,
            tipo_operador='motorista',
            veiculo_placa=placa or None,
            documento_registro=documento or None,
            email=email or None
        )
        novo_motorista.gerar_token_se_necessario()
        db.session.add(novo_motorista)
        db.session.commit()

        flash(f'Motorista "{nome}" cadastrado com sucesso!', 'success')
        return redirect(url_for('gestao_motoristas'))

    motoristas = OperadorCampo.query.filter_by(
        empresa_id=current_user.empresa_id,
        tipo_operador='motorista'
    ).order_by(OperadorCampo.nome.asc()).all()

    for m in motoristas:
        m.gerar_token_se_necessario()
    db.session.commit()

    hoje = date.today()

    # 1. BUSCA RÁPIDA DE COMPROVANTE (POR CLIENTE, CPF/CNPJ OU NÚMERO DO PEDIDO)
    termo_busca = request.args.get('busca_entrega', '').strip()
    entregas_busca = []

    if termo_busca:
        doc_limpo = re.sub(r'\D', '', termo_busca)
        query_entregas = PedidoRequisicao.query.filter_by(
            empresa_id=current_user.empresa_id
        ).outerjoin(Cliente, PedidoRequisicao.cliente_id == Cliente.id)

        condicoes = [
            PedidoRequisicao.nome_solicitante.ilike(f'%{termo_busca}%'),
            PedidoRequisicao.numero_pedido.ilike(f'%{termo_busca}%'),
            PedidoRequisicao.recebido_por_nome.ilike(f'%{termo_busca}%')
        ]
        if doc_limpo:
            condicoes.append(Cliente.cnpj_cpf.ilike(f'%{doc_limpo}%'))
            condicoes.append(PedidoRequisicao.recebido_por_documento.ilike(f'%{doc_limpo}%'))

        from sqlalchemy import or_
        entregas_busca = query_entregas.filter(or_(*condicoes)).order_by(
            PedidoRequisicao.data_entrega_realizada.desc().nullslast(),
            PedidoRequisicao.id.desc()
        ).all()

    # 2. ENTREGAS DO DIA (MONITORIZAÇÃO EM DIRETO POR MOTORISTA)
    entregas_hoje_todas = PedidoRequisicao.query.filter_by(
        empresa_id=current_user.empresa_id
    ).filter(
        PedidoRequisicao.operador_id.isnot(None),
        (PedidoRequisicao.data_agendada_entrega == hoje) | 
        ((PedidoRequisicao.status == 'em_rota') & (PedidoRequisicao.data_agendada_entrega.is_(None)))
    ).order_by(PedidoRequisicao.ordem_entrega.asc(), PedidoRequisicao.id.asc()).all()

    monitoramento_motoristas = {}
    for m in motoristas:
        pedidos_motorista = [p for p in entregas_hoje_todas if p.operador_id == m.id]
        if pedidos_motorista:
            total_pedidos = len(pedidos_motorista)
            concluidos = sum(1 for p in pedidos_motorista if p.status in ['entregue', 'concluido'])
            monitoramento_motoristas[m.id] = {
                'motorista': m,
                'pedidos': pedidos_motorista,
                'total': total_pedidos,
                'concluidos': concluidos,
                'percentual': round((concluidos / total_pedidos * 100) if total_pedidos > 0 else 0)
            }

    # 3. HISTÓRICO AGRUPADO POR DIAS
    historico_por_dia = defaultdict(lambda: defaultdict(list))
    todas_entregas_passadas = PedidoRequisicao.query.filter_by(
        empresa_id=current_user.empresa_id
    ).filter(
        PedidoRequisicao.operador_id.isnot(None),
        PedidoRequisicao.status.in_(['entregue', 'concluido'])
    ).order_by(
        PedidoRequisicao.data_entrega_realizada.desc().nullslast(),
        PedidoRequisicao.data_solicitacao.desc()
    ).all()

    for p in todas_entregas_passadas:
        dt_ref = p.data_entrega_realizada.date() if p.data_entrega_realizada else (p.data_agendada_entrega or p.data_solicitacao.date())
        dt_str = dt_ref.strftime('%d/%m/%Y')
        historico_por_dia[p.operador_id][dt_str].append(p)

    return render_template(
        'motoristas.html',
        motoristas=motoristas,
        monitoramento_motoristas=monitoramento_motoristas,
        historico_por_dia=historico_por_dia,
        entregas_busca=entregas_busca,
        termo_busca=termo_busca,
        hoje=hoje
    )


@app.route('/motoristas/<int:id>/editar', methods=['POST'])
@login_required
def editar_motorista(id):
    if not (current_user.nivel_acesso in ['admin', 'master'] or current_user.perm_expedicao):
        flash('Acesso restrito.', 'danger')
        return redirect(url_for('gestao_motoristas'))

    mot = OperadorCampo.query.filter_by(id=id, empresa_id=current_user.empresa_id, tipo_operador='motorista').first_or_404()
    
    nome = request.form.get('nome', '').strip()
    telefone = re.sub(r'\D', '', request.form.get('telefone', ''))
    placa = request.form.get('veiculo_placa', '').strip().upper()
    documento = request.form.get('documento_registro', '').strip()
    email = request.form.get('email', '').strip().lower()

    if not nome or not telefone:
        flash('Nome e WhatsApp são obrigatórios para atualizar o motorista.', 'warning')
        return redirect(url_for('gestao_motoristas'))

    mot.nome = nome
    mot.telefone = telefone
    mot.veiculo_placa = placa or None
    mot.documento_registro = documento or None
    mot.email = email or None

    db.session.commit()
    flash(f'Dados do motorista "{mot.nome}" atualizados com sucesso!', 'success')
    return redirect(url_for('gestao_motoristas'))


@app.route('/motoristas/<int:id>/status', methods=['POST'])
@login_required
def alternar_status_motorista(id):
    mot = OperadorCampo.query.filter_by(id=id, empresa_id=current_user.empresa_id, tipo_operador='motorista').first_or_404()
    mot.ativo = not mot.ativo
    db.session.commit()
    flash(f'Status do motorista "{mot.nome}" atualizado!', 'info')
    return redirect(url_for('gestao_motoristas'))


@app.route('/motoristas/<int:id>/excluir', methods=['POST'])
@login_required
def excluir_motorista(id):
    mot = OperadorCampo.query.filter_by(id=id, empresa_id=current_user.empresa_id, tipo_operador='motorista').first_or_404()
    db.session.delete(mot)
    db.session.commit()
    flash('Motorista removido da equipe com sucesso.', 'info')
    return redirect(url_for('gestao_motoristas'))



# =============================================================================
# PORTAL DE AUTOATENDIMENTO B2B: REQUISIÇÃO DE COMPRA DO CLIENTE
# =============================================================================

@app.route('/api/portal-vendas/consultar-cliente/<int:empresa_id>', methods=['POST'])
def api_consultar_cliente_portal(empresa_id):
    """Verifica se o cliente existe pelo CPF ou CNPJ cadastrado na empresa."""
    dados = request.get_json(silent=True) or {}
    documento_raw = dados.get('documento', '')
    doc_limpo = re.sub(r'\D', '', documento_raw)

    if not doc_limpo:
        return jsonify({'encontrado': False, 'mensagem': 'Informe um CPF ou CNPJ válido.'}), 400

    # Busca clientes da empresa cujo documento limpo coincida
    clientes = Cliente.query.filter_by(empresa_id=empresa_id).all()
    cliente_encontrado = None
    for c in clientes:
        if re.sub(r'\D', '', c.cnpj_cpf or '') == doc_limpo:
            cliente_encontrado = c
            break

    if not cliente_encontrado:
        return jsonify({
            'encontrado': False, 
            'mensagem': 'CPF/CNPJ não localizado na nossa base. Entre em contato conosco para realizar o seu cadastro antes de submeter o pedido.'
        })

    end_completo = f"{cliente_encontrado.logradouro or ''}, {cliente_encontrado.numero or 'S/N'} {cliente_encontrado.complemento or ''} - {cliente_encontrado.bairro or ''}, {cliente_encontrado.cidade or ''}/{cliente_encontrado.estado or ''}".strip(" ,-/")

    return jsonify({
        'encontrado': True,
        'id': cliente_encontrado.id,
        'nome': cliente_encontrado.nome,
        'nome_fantasia': cliente_encontrado.nome_fantasia or '',
        'documento': cliente_encontrado.cnpj_cpf,
        'telefone': cliente_encontrado.telefone or '',
        'email': cliente_encontrado.email or cliente_encontrado.email_financeiro or '',
        'endereco': end_completo or 'Retirada no Balcão'
    })


@app.route('/pedido-venda/<slug_loja>', methods=['GET', 'POST'])
def portal_pedido_venda_cliente(slug_loja):
    """Tela externa acessada pelo cliente para fazer a requisição de compra com validação de estoque."""
    empresa = Empresa.query.filter_by(slug_loja=slug_loja).first_or_404()

    # Se a loja estiver desativada pelo plano, renderiza a tela com fallback seguro
    if not (empresa.modulo_vendas_externas or empresa.modulo_estoque):
        try:
            return render_template('publico/modulo_indisponivel.html', empresa=empresa), 403
        except Exception:
            return f"<div style='font-family:sans-serif;text-align:center;padding:50px;'><h2>Canal Indisponível</h2><p>O catálogo de compras de <b>{empresa.razao_social}</b> está temporariamente desativado.</p></div>", 403

    if request.method == 'POST':
        try:
            cliente_id = request.form.get('cliente_id')
            if not cliente_id or not cliente_id.isdigit():
                flash('É obrigatório validar seu cadastro via CNPJ/CPF antes de enviar o pedido.', 'danger')
                return redirect(url_for('portal_pedido_venda_cliente', slug_loja=slug_loja))

            cliente = Cliente.query.filter_by(id=int(cliente_id), empresa_id=empresa.id).first_or_404()

            produtos_ids = request.form.getlist('produto_id[]')
            quantidades = request.form.getlist('quantidade[]')
            observacoes = request.form.get('observacoes', '').strip()
            endereco_entrega = request.form.get('endereco_entrega', '').strip()

            if not produtos_ids:
                flash('Inclua ao menos um produto no pedido.', 'warning')
                return redirect(url_for('portal_pedido_venda_cliente', slug_loja=slug_loja))

            total_existentes = PedidoRequisicao.query.filter_by(empresa_id=empresa.id).count() + 1
            num_pedido = f"WEB-{datetime.now().year}-{total_existentes:04d}"

            novo_pedido = PedidoRequisicao(
                empresa_id=empresa.id,
                cliente_id=cliente.id,
                numero_pedido=num_pedido,
                tipo_origem='venda_web',
                nome_solicitante=cliente.nome,
                contato_solicitante=cliente.telefone or '',
                setor_obra_destino=endereco_entrega or 'Endereço Cadastrado',
                observacoes=observacoes,
                status='pendente',
                valor_total=0.0
            )
            db.session.add(novo_pedido)
            db.session.flush()
            valor_total_acumulado = 0.0

            for p_id, qtd_str in zip(produtos_ids, quantidades):
                if p_id and qtd_str and float(qtd_str) > 0:
                    prod = ProdutoEstoque.query.filter_by(id=int(p_id), empresa_id=empresa.id, ativo=True).first()
                    if prod:
                        qtd = float(qtd_str)
                        # Garante que não ultrapasse o saldo físico atual
                        qtd_atendivel = min(qtd, float(prod.quantidade_atual or 0.0))
                        if qtd_atendivel > 0:
                            unit = float(prod.preco_venda_sugerido or 0.0)
                            subtotal = round(qtd_atendivel * unit, 2)
                            valor_total_acumulado += subtotal

                            item = ItemPedidoRequisicao(
                                pedido_id=novo_pedido.id,
                                produto_id=prod.id,
                                quantidade_solicitada=qtd_atendivel,
                                preco_unitario=unit,
                                valor_total=subtotal
                            )
                            db.session.add(item)

            novo_pedido.valor_total = round(valor_total_acumulado, 2)
            db.session.commit()

            return render_template('publico/pedido_venda_sucesso.html', empresa=empresa, pedido=novo_pedido)

        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao processar o seu pedido: {str(e)}", "danger")
            return redirect(url_for('portal_pedido_venda_cliente', slug_loja=slug_loja))

    # Lista apenas produtos ativos e com saldo positivo em estoque
    produtos_disponiveis = ProdutoEstoque.query.filter_by(
        empresa_id=empresa.id,
        ativo=True
    ).filter(ProdutoEstoque.quantidade_atual > 0).order_by(ProdutoEstoque.nome.asc()).all()

    return render_template(
        'publico/portal_venda_cliente.html',
        empresa=empresa,
        produtos=produtos_disponiveis
    )

# -----------------------------------------------------------------------------
# RELATÓRIO CONTÁBIL CONSOLIDADO: RECEBIMENTOS & CUSTOS (SERVIÇOS + VENDAS)
# -----------------------------------------------------------------------------
@app.route('/relatorios/contabil')
@login_required
def relatorio_contabil():
    if current_user.nivel_acesso not in ['admin', 'master'] and not current_user.perm_financeiro:
        flash('Acesso restrito ao setor financeiro e contábil.', 'danger')
        return redirect(url_for('index'))

    empresa_id = current_user.empresa_id
    hoje = date.today()

    # Filtros de Período (Padrão: Mês atual)
    data_inicio_str = request.args.get('data_inicio')
    data_fim_str = request.args.get('data_fim')

    if data_inicio_str and data_fim_str:
        dt_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
        dt_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
    else:
        dt_inicio = date(hoje.year, hoje.month, 1)
        dt_fim = (dt_inicio + relativedelta(months=1)) - timedelta(days=1)

    # 1. RECEBIMENTOS EFETIVADOS (PARCELAS PAGAS NO PERÍODO)
    parcelas_pagas = ParcelaFatura.query.join(Fatura).filter(
        ParcelaFatura.empresa_id == empresa_id,
        ParcelaFatura.status == 'Pago',
        ParcelaFatura.data_vencimento >= dt_inicio,
        ParcelaFatura.data_vencimento <= dt_fim
    ).order_by(ParcelaFatura.data_vencimento.desc()).all()

    recebimentos_consolidados = []
    total_servicos_recebido = 0.0
    total_vendas_recebido = 0.0

    for p in parcelas_pagas:
        fat = p.fatura
        cli = fat.cliente
        origem_tipo = 'Venda de Mercadoria' if fat.pedido_venda else 'Prestação de Serviços'

        if fat.pedido_venda:
            total_vendas_recebido += p.valor
        else:
            total_servicos_recebido += p.valor

        recebimentos_consolidados.append({
            'data': p.data_vencimento,
            'cliente_nome': cli.nome if cli else 'Consumidor Final',
            'cliente_doc': cli.cnpj_cpf if cli else '--',
            'origem': origem_tipo,
            'documento_ref': fat.descricao,
            'forma_pagamento': p.forma_pagamento or 'Boleto/Transferência',
            'valor': p.valor,
            'arquivo_nf': fat.arquivo_nf,
            'arquivo_comprovante': p.arquivo_comprovante_boleto
        })

    # 2. APURAÇÃO DE CUSTOS DIRETOS (CMV VENDAS + CUSTOS SERVIÇOS)
    # Custos de Vendas (CMV) concluídas no período
    vendas_periodo = PedidoRequisicao.query.filter_by(empresa_id=empresa_id).filter(
        PedidoRequisicao.status == 'entregue',
        PedidoRequisicao.data_solicitacao >= datetime.combine(dt_inicio, datetime.min.time()),
        PedidoRequisicao.data_solicitacao <= datetime.combine(dt_fim, datetime.max.time())
    ).all()

    cmv_vendas = sum(
        (it.quantidade_solicitada * (it.produto.preco_custo or 0.0))
        for v in vendas_periodo for it in v.itens if it.produto
    )

    # Custos Analíticos de Serviços de Propostas Aprovadas no período
    propostas_periodo = Proposta.query.filter_by(empresa_id=empresa_id, status='Aprovado').filter(
        Proposta.data_criacao >= dt_inicio,
        Proposta.data_criacao <= dt_fim
    ).all()

    custo_servicos = sum(p.custo_total_previsto for p in propostas_periodo)

    total_recebido = total_servicos_recebido + total_vendas_recebido
    total_custos = cmv_vendas + custo_servicos
    resultado_liquido = total_recebido - total_custos

    return render_template(
        'relatorio_contabil.html',
        dt_inicio=dt_inicio,
        dt_fim=dt_fim,
        recebimentos=recebimentos_consolidados,
        total_servicos=total_servicos_recebido,
        total_vendas=total_vendas_recebido,
        total_recebido=total_recebido,
        cmv_vendas=cmv_vendas,
        custo_servicos=custo_servicos,
        total_custos=total_custos,
        resultado_liquido=resultado_liquido
    )

# -----------------------------------------------------------------------------
# EXPORTAÇÃO CSV PARA O SOFTWARE DO CONTADOR (DOMÍNIO / ALTERDATA / CONTMATIC)
# -----------------------------------------------------------------------------
@app.route('/relatorios/contabil/exportar-csv')
@login_required
def exportar_contabil_csv():
    if current_user.nivel_acesso not in ['admin', 'master'] and not current_user.perm_financeiro:
        abort(403)

    empresa_id = current_user.empresa_id
    data_inicio_str = request.args.get('data_inicio')
    data_fim_str = request.args.get('data_fim')

    dt_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date() if data_inicio_str else date(date.today().year, date.today().month, 1)
    dt_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date() if data_fim_str else date.today()

    parcelas_pagas = ParcelaFatura.query.join(Fatura).filter(
        ParcelaFatura.empresa_id == empresa_id,
        ParcelaFatura.status == 'Pago',
        ParcelaFatura.data_vencimento >= dt_inicio,
        ParcelaFatura.data_vencimento <= dt_fim
    ).order_by(ParcelaFatura.data_vencimento.asc()).all()

    si = StringIO()
    cw = csv.writer(si, delimiter=';')
    cw.writerow(['DATA_LIQUIDACAO', 'CLIENTE', 'CNPJ_CPF', 'TIPO_RECEITA', 'DOCUMENTO_REFERENCIA', 'FORMA_PAGAMENTO', 'VALOR_BRUTO_RECEBIDO'])

    for p in parcelas_pagas:
        fat = p.fatura
        cli = fat.cliente
        origem = 'Mercadorias' if fat.pedido_venda else 'Servicos'
        cw.writerow([
            p.data_vencimento.strftime('%d/%m/%Y'),
            cli.nome if cli else 'Consumidor',
            cli.cnpj_cpf if cli else '--',
            origem,
            fat.descricao,
            p.forma_pagamento or 'Transferencia',
            f"{p.valor:.2f}".replace('.', ',')
        ])

    output = make_response(si.getvalue().encode('latin-1', 'replace'))
    output.headers["Content-Disposition"] = f"attachment; filename=extrato_contabil_{dt_inicio.strftime('%Y%m')}.csv"
    output.headers["Content-type"] = "text/csv; charset=latin-1"
    return output

@app.route('/relatorios/contabil/pdf')
@login_required
def gerar_pdf_relatorio_contabil():
    if current_user.nivel_acesso not in ['admin', 'master'] and not current_user.perm_financeiro:
        abort(403)

    empresa = current_user.empresa
    hoje = date.today()

    data_inicio_str = request.args.get('data_inicio')
    data_fim_str = request.args.get('data_fim')

    if data_inicio_str and data_fim_str:
        dt_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
        dt_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
    else:
        dt_inicio = date(hoje.year, hoje.month, 1)
        dt_fim = (dt_inicio + relativedelta(months=1)) - timedelta(days=1)

    # 1. Parcelas Pagas
    parcelas_pagas = ParcelaFatura.query.join(Fatura).filter(
        ParcelaFatura.empresa_id == empresa.id,
        ParcelaFatura.status == 'Pago',
        ParcelaFatura.data_vencimento >= dt_inicio,
        ParcelaFatura.data_vencimento <= dt_fim
    ).order_by(ParcelaFatura.data_vencimento.asc()).all()

    total_servicos = sum(p.valor for p in parcelas_pagas if not p.fatura.pedido_venda)
    total_vendas = sum(p.valor for p in parcelas_pagas if p.fatura.pedido_venda)
    total_recebido = total_servicos + total_vendas

    # 2. Custos
    vendas_periodo = PedidoRequisicao.query.filter_by(empresa_id=empresa.id).filter(
        PedidoRequisicao.status == 'entregue',
        PedidoRequisicao.data_solicitacao >= datetime.combine(dt_inicio, datetime.min.time()),
        PedidoRequisicao.data_solicitacao <= datetime.combine(dt_fim, datetime.max.time())
    ).all()
    cmv_vendas = sum((it.quantidade_solicitada * (it.produto.preco_custo or 0.0)) for v in vendas_periodo for it in v.itens if it.produto)

    propostas_periodo = Proposta.query.filter_by(empresa_id=empresa.id, status='Aprovado').filter(
        Proposta.data_criacao >= dt_inicio, Proposta.data_criacao <= dt_fim
    ).all()
    custo_servicos = sum(p.custo_total_previsto for p in propostas_periodo)
    total_custos = cmv_vendas + custo_servicos
    lucro_liquido = total_recebido - total_custos

    # GERAÇÃO DO PDF REPORTLAB
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    elementos = []
    styles = getSampleStyleSheet()

    cor_marca = colors.HexColor(empresa.cor_primaria or "#1e3a8a")
    estilo_emp = ParagraphStyle('PdfEmp', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=cor_marca)
    estilo_sub = ParagraphStyle('PdfSub', parent=styles['Normal'], fontName='Helvetica', fontSize=7.5, leading=10, textColor=colors.HexColor("#475569"))
    estilo_secao = ParagraphStyle('PdfSec', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9.5, leading=13, textColor=cor_marca)
    estilo_corpo = ParagraphStyle('PdfCorpo', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor("#1e293b"))
    estilo_corpo_bold = ParagraphStyle('PdfCorpoB', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=11, textColor=colors.HexColor("#0f172a"))

    logo_elemento = _obter_logo_reportlab(empresa.logo_filename, width=1.5*inch, height=0.6*inch)
    info_emp = f"<b>{_limpar_texto(empresa.razao_social).upper()}</b><br/>CNPJ/CPF: {_limpar_texto(empresa.cnpj or '--')} | Tel: {_limpar_texto(empresa.telefone or '--')}<br/>{_limpar_texto(empresa.endereco_completo or '')}"

    if logo_elemento:
        tab_topo = Table([[logo_elemento, Paragraph(info_emp, estilo_sub)]], colWidths=[1.8*inch, 5.7*inch])
    else:
        tab_topo = Table([[Paragraph(f"<b>{_limpar_texto(empresa.razao_social).upper()}</b>", estilo_emp), Paragraph(info_emp, estilo_sub)]], colWidths=[2.8*inch, 4.7*inch])
    tab_topo.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (1,0), (1,0), 'RIGHT')]))
    elementos.append(tab_topo)
    elementos.append(Spacer(1, 4))
    elementos.append(HRFlowable(width="100%", thickness=1.5, color=cor_marca, spaceAfter=8))

    # Título do Relatório
    periodo_formatado = f"{dt_inicio.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')}"
    elementos.append(Paragraph(f"<b>DEMONSTRATIVO CONTÁBIL DE ENTRADAS & CUSTOS (REGIME DE CAIXA)</b>", estilo_secao))
    elementos.append(Paragraph(f"<font color='#64748b' size='8'>Período de Apuração: {periodo_formatado} | Emissão: {datetime.now().strftime('%d/%m/%Y %H:%M')}</font>", estilo_corpo))
    elementos.append(Spacer(1, 8))

    # Tabela Síntese Financeira
    resumo_dados = [
        [Paragraph("<b>TOTAL SERVIÇOS</b>", estilo_corpo_bold), Paragraph("<b>TOTAL MERCADORIAS</b>", estilo_corpo_bold), Paragraph("<b>CUSTOS DIRETOS (CMV/MAT)</b>", estilo_corpo_bold), Paragraph("<b>RESULTADO LÍQUIDO</b>", estilo_corpo_bold)],
        [Paragraph(f"R$ {total_servicos:,.2f}", estilo_corpo), Paragraph(f"R$ {total_vendas:,.2f}", estilo_corpo), Paragraph(f"R$ {total_custos:,.2f}", estilo_corpo), Paragraph(f"<b>R$ {lucro_liquido:,.2f}</b>", estilo_corpo_bold)]
    ]
    tab_res = Table(resumo_dados, colWidths=[1.87*inch, 1.87*inch, 1.87*inch, 1.87*inch])
    tab_res.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f1f5f9")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('PADDING', (0,0), (-1,-1), 5),
        ('ALIGN', (0,0), (-1,-1), 'CENTER')
    ]))
    elementos.append(tab_res)
    elementos.append(Spacer(1, 10))

    elementos.append(Paragraph("<b>DISCRIMINAÇÃO DOS ITENS SOLICITADOS</b>", estilo_secao))
    elementos.append(Spacer(1, 4))

    # Estilo específico em branco puro para o cabeçalho da tabela
    estilo_th = ParagraphStyle(
        'ThTabelaBranco',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.white
    )

    itens_tabela = [
        [Paragraph("<b>Data</b>", estilo_corpo_bold), Paragraph("<b>Cliente / Fonte Pagadora</b>", estilo_corpo_bold), Paragraph("<b>CNPJ / CPF</b>", estilo_corpo_bold), Paragraph("<b>Origem</b>", estilo_corpo_bold), Paragraph("<b>Meio Pgto</b>", estilo_corpo_bold), Paragraph("<b>Valor (R$)</b>", estilo_corpo_bold)]
    ]

    for p in parcelas_pagas:
        cli = p.fatura.cliente
        origem = 'Mercadoria' if p.fatura.pedido_venda else 'Serviço'
        itens_tabela.append([
            Paragraph(p.data_vencimento.strftime('%d/%m/%Y'), estilo_corpo),
            Paragraph(_limpar_texto(cli.nome if cli else 'Consumidor')[:26], estilo_corpo),
            Paragraph(_limpar_texto(cli.cnpj_cpf if cli else '--'), estilo_corpo),
            Paragraph(origem, estilo_corpo),
            Paragraph(_limpar_texto(p.forma_pagamento or 'Boleto')[:12], estilo_corpo),
            Paragraph(f"{p.valor:,.2f}", estilo_corpo_bold)
        ])

    itens_tabela.append([
        Paragraph("<b>TOTAL GERAL RECEBIDO</b>", estilo_corpo_bold), Paragraph("", estilo_corpo), Paragraph("", estilo_corpo), Paragraph("", estilo_corpo), Paragraph("", estilo_corpo),
        Paragraph(f"<b>R$ {total_recebido:,.2f}</b>", estilo_corpo_bold)
    ])

    tab_itens = Table(itens_tabela, colWidths=[0.8*inch, 2.5*inch, 1.3*inch, 0.9*inch, 1.0*inch, 1.0*inch])
    tab_itens.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (5,0), (5,-1), 'RIGHT'),
        ('GRID', (0,0), (-1,-2), 0.5, colors.HexColor("#cbd5e1")),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#f8fafc")),
        ('LINEABOVE', (0,-1), (-1,-1), 1.2, colors.HexColor("#0f172a")),
        ('PADDING', (0,0), (-1,-1), 4)
    ]))
    elementos.append(tab_itens)
    elementos.append(Spacer(1, 35))

    # Assinaturas
    tab_ass = Table([
        [
            Paragraph(f"____________________________________________<br/><b>{_limpar_texto(empresa.razao_social).upper()}</b><br/>Responsável Legal", estilo_corpo),
            Paragraph("____________________________________________<br/><b>RESPONSÁVEL CONTÁBIL</b><br/>CRC / Declaração de Conferência", estilo_corpo)
        ]
    ], colWidths=[3.75*inch, 3.75*inch], style=[('ALIGN', (0,0), (-1,-1), 'CENTER')])
    elementos.append(tab_ass)

    doc.build(elementos)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Demonstrativo_Contabil_{dt_inicio.strftime('%Y%m')}.pdf", mimetype='application/pdf')

# -----------------------------------------------------------------------------
# PACOTE ZIP DE AUDITORIA CONTÁBIL / FISCAL (NOTAS FISCAIS RENOMEADAS + CSV)
# -----------------------------------------------------------------------------
@app.route('/relatorios/contabil/baixar-pacote-nf-zip')
@login_required
def baixar_pacote_nf_zip():
    if current_user.nivel_acesso not in ['admin', 'master'] and not current_user.perm_financeiro:
        abort(403)

    empresa_id = current_user.empresa_id
    hoje = date.today()

    data_inicio_str = request.args.get('data_inicio')
    data_fim_str = request.args.get('data_fim')

    if data_inicio_str and data_fim_str:
        dt_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
        dt_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
    else:
        dt_inicio = date(hoje.year, hoje.month, 1)
        dt_fim = (dt_inicio + relativedelta(months=1)) - timedelta(days=1)

    # 1. NOTAS FISCAIS DE SERVIÇOS (Faturas com NF anexada)
    faturas_com_nf = Fatura.query.filter(
        Fatura.empresa_id == empresa_id,
        Fatura.arquivo_nf.isnot(None),
        Fatura.data_emissao >= dt_inicio,
        Fatura.data_emissao <= dt_fim
    ).all()

    # 2. NOTAS FISCAIS DE VENDAS DE MERCADORIAS (Pedidos com NF anexada)
    pedidos_com_nf = PedidoRequisicao.query.filter(
        PedidoRequisicao.empresa_id == empresa_id,
        PedidoRequisicao.arquivo_nf.isnot(None),
        PedidoRequisicao.data_solicitacao >= datetime.combine(dt_inicio, datetime.min.time()),
        PedidoRequisicao.data_solicitacao <= datetime.combine(dt_fim, datetime.max.time())
    ).all()

    if not faturas_com_nf and not pedidos_com_nf:
        flash('Nenhum anexo de Nota Fiscal localizado no período selecionado.', 'warning')
        return redirect(url_for('relatorio_contabil', data_inicio=dt_inicio.strftime('%Y-%m-%d'), data_fim=dt_fim.strftime('%Y-%m-%d')))

    # Buffer em memória para montar o arquivo ZIP sem gravar no disco
    zip_buffer = BytesIO()

    # Lista para o CSV sumário de conferência
    linhas_relatorio = [
        ['TIPO', 'NUMERO_REF', 'DATA_DOCUMENTO', 'CLIENTE', 'CNPJ_CPF', 'VALOR_TOTAL', 'NOME_ARQUIVO_NO_ZIP']
    ]

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        
        # A) Processa NFs de Serviços
        for fat in faturas_com_nf:
            stream_arquivo = obter_arquivo_bytes(fat.arquivo_nf)
            if not stream_arquivo:
                continue

            cli_nome = re.sub(r'[^a-zA-Z0-9]', '_', (fat.cliente.nome if fat.cliente else 'Cliente')[:30]).strip('_')
            cli_doc = fat.cliente.cnpj_cpf if fat.cliente else '--'
            dt_ref = (fat.data_emissao or hoje).strftime('%Y-%m-%d')
            extensao = fat.arquivo_nf.rsplit('.', 1)[-1].lower() if '.' in fat.arquivo_nf else 'pdf'
            
            nome_amigavel = f"{dt_ref}_NF_Servico_{cli_nome}_FAT{fat.id:04d}.{extensao}"

            # Grava no ZIP
            zip_file.writestr(f"Notas_Fiscais/{nome_amigavel}", stream_arquivo.getvalue())

            linhas_relatorio.append([
                'Serviço',
                f"FAT-{fat.id:04d}",
                dt_ref,
                fat.cliente.nome if fat.cliente else 'Consumidor',
                cli_doc,
                f"{fat.valor_total:.2f}".replace('.', ','),
                nome_amigavel
            ])

        # B) Processa NFs de Vendas de Mercadorias
        for ped in pedidos_com_nf:
            stream_arquivo = obter_arquivo_bytes(ped.arquivo_nf)
            if not stream_arquivo:
                continue

            cli_nome = re.sub(r'[^a-zA-Z0-9]', '_', (ped.nome_solicitante or 'Cliente')[:30]).strip('_')
            dt_ref = (ped.data_solicitacao.date() if ped.data_solicitacao else hoje).strftime('%Y-%m-%d')
            extensao = ped.arquivo_nf.rsplit('.', 1)[-1].lower() if '.' in ped.arquivo_nf else 'pdf'

            nome_amigavel = f"{dt_ref}_NF_Venda_{cli_nome}_{ped.numero_pedido}.{extensao}"

            zip_file.writestr(f"Notas_Fiscais/{nome_amigavel}", stream_arquivo.getvalue())

            linhas_relatorio.append([
                'Venda Mercadoria',
                ped.numero_pedido,
                dt_ref,
                ped.nome_solicitante,
                getattr(ped.cliente, 'cnpj_cpf', '--') if ped.cliente else '--',
                f"{ped.valor_total:.2f}".replace('.', ','),
                nome_amigavel
            ])

        # C) Cria e anexa o Sumário em CSV dentro da raiz do ZIP
        csv_buffer = StringIO()
        csv_writer = csv.writer(csv_buffer, delimiter=';')
        csv_writer.writerows(linhas_relatorio)
        zip_file.writestr("RELATORIO_SUMARIO_AUDITORIA.csv", csv_buffer.getvalue().encode('latin-1', 'replace'))

    zip_buffer.seek(0)
    nome_zip = f"Auditoria_NFs_{dt_inicio.strftime('%Y%m%d')}_a_{dt_fim.strftime('%Y%m%d')}.zip"

    return send_file(
        zip_buffer,
        as_attachment=True,
        download_name=nome_zip,
        mimetype='application/zip'
    )

# -----------------------------------------------------------------------------
# 9. INICIALIZAÇÃO DO SERVIDOR
# -----------------------------------------------------------------------------

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)