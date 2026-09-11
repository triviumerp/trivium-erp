from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from extensions import db

class Empresa(db.Model):
    __tablename__ = 'empresas'
    id = db.Column(db.Integer, primary_key=True)
    razao_social = db.Column(db.String(150), nullable=False)
    nome_fantasia = db.Column(db.String(150))
    cnpj = db.Column(db.String(30))
    telefone = db.Column(db.String(50))
    email = db.Column(db.String(120))
    site = db.Column(db.String(120))
    
    # Endereço Estruturado (Padronizado com a tabela Cliente)
    cep = db.Column(db.String(10), nullable=True)
    logradouro = db.Column(db.String(150), nullable=True)
    numero = db.Column(db.String(20), nullable=True)
    complemento = db.Column(db.String(100), nullable=True)
    bairro = db.Column(db.String(100), nullable=True)
    cidade = db.Column(db.String(100), nullable=True)
    estado = db.Column(db.String(2), nullable=True)
    endereco_completo = db.Column(db.String(255), nullable=True)
    
    # White-label
    logo_filename = db.Column(db.String(200))
    cor_primaria = db.Column(db.String(7), default="#1e3a8a")
    cor_secundaria = db.Column(db.String(7), default="#059669")
    cor_sidebar = db.Column(db.String(7), default="#ffffff")

    # Assinatura & Controle Master
    plano = db.Column(db.String(30), default="Founder")
    status_assinatura = db.Column(db.String(20), default="trial")
    valor_mensalidade = db.Column(db.Float, default=0.0)
    forma_pagamento_asaas = db.Column(db.String(30), nullable=True)
    asaas_customer_id = db.Column(db.String(50), nullable=True)
    asaas_subscription_id = db.Column(db.String(50), nullable=True)
    data_vencimento = db.Column(db.Date, nullable=True)
    data_ultimo_pagamento = db.Column(db.Date, nullable=True)
    observacoes_master = db.Column(db.Text, nullable=True)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

    # Relacionamentos
    usuarios = db.relationship('Usuario', backref='empresa', lazy=True, cascade="all, delete-orphan")
    clientes = db.relationship('Cliente', backref='empresa', lazy=True, cascade="all, delete-orphan")
    tipos_servico = db.relationship('TipoServico', backref='empresa', lazy=True, cascade="all, delete-orphan")
    servicos = db.relationship('ServicoCliente', backref='empresa', lazy=True, cascade="all, delete-orphan")
    propostas = db.relationship('Proposta', backref='empresa', lazy=True, cascade="all, delete-orphan")
    contratos = db.relationship('ContratoRecorrente', backref='empresa', lazy=True, cascade="all, delete-orphan")
    faturas = db.relationship('Fatura', backref='empresa', lazy=True, cascade="all, delete-orphan")
    parcelas = db.relationship('ParcelaFatura', backref='empresa', lazy=True, cascade="all, delete-orphan")

    cupom_utilizado = db.Column(db.String(30), nullable=True)
    afiliado_id = db.Column(db.Integer, db.ForeignKey('cupons_desconto.id'), nullable=True)
    data_expiracao_cupom = db.Column(db.Date, nullable=True)
    cupom_aplicavel_recorrente = db.Column(db.Boolean, default=False)

    @property
    def dias_cadastrado(self):
        if not self.data_criacao:
            return 0
        return (date.today() - self.data_criacao.date()).days

    @property
    def dias_restantes_trial(self):
        if not self.data_vencimento:
            return 0
        return (self.data_vencimento - date.today()).days


class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)
    cargo = db.Column(db.String(100), nullable=True)
    nivel_acesso = db.Column(db.String(20), default='operador')  # 'admin', 'operador', 'master', 'afiliado'
    ativo = db.Column(db.Boolean, default=True)
    
    # Permissões do ERP Operacional
    perm_clientes = db.Column(db.Boolean, default=False)
    perm_propostas = db.Column(db.Boolean, default=False)
    perm_servicos = db.Column(db.Boolean, default=False)
    perm_financeiro = db.Column(db.Boolean, default=False)
    perm_configuracoes = db.Column(db.Boolean, default=False)
    aceitou_termos_beta = db.Column(db.Boolean, default=True)
    data_aceite_termos = db.Column(db.DateTime, nullable=True)

    # Dados e Conformidade do Afiliado / Parceiro
    cpf_cnpj = db.Column(db.String(20), nullable=True)
    chave_pix = db.Column(db.String(150), nullable=True)
    whatsapp = db.Column(db.String(50), nullable=True)
    rede_social_principal = db.Column(db.String(150), nullable=True)
    tipo_parceiro = db.Column(db.String(50), nullable=True)
    status_aprovacao = db.Column(db.String(30), default='aprovado')  # 'pendente', 'aprovado', 'rejeitado'
    motivo_rejeicao = db.Column(db.Text, nullable=True)
    aceitou_termos_afiliado = db.Column(db.Boolean, default=False)
    data_aceite_termos_afiliado = db.Column(db.DateTime, nullable=True)

    # Relacionamento 1 -> N com Cupons
    cupons = db.relationship('CupomDesconto', backref='parceiro', lazy=True)

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)


class Cliente(db.Model):
    __tablename__ = 'clientes'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    nome = db.Column(db.String(150), nullable=False)
    nome_fantasia = db.Column(db.String(150), nullable=True)
    cnpj_cpf = db.Column(db.String(20), nullable=False)
    inscricao_estadual = db.Column(db.String(30), nullable=True)
    responsavel = db.Column(db.String(100), nullable=True)
    telefone = db.Column(db.String(20), nullable=False)
    telefone_secundario = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    email_financeiro = db.Column(db.String(120), nullable=True)
    cep = db.Column(db.String(10), nullable=True)
    logradouro = db.Column(db.String(150), nullable=True)
    numero = db.Column(db.String(20), nullable=True)
    complemento = db.Column(db.String(100), nullable=True)
    bairro = db.Column(db.String(100), nullable=True)
    cidade = db.Column(db.String(100), nullable=True)
    estado = db.Column(db.String(2), nullable=True)
    endereco_completo = db.Column(db.String(255), nullable=True)
    observacoes = db.Column(db.Text, nullable=True)

    # Relacionamentos
    documentos = db.relationship('Documento', backref='cliente', lazy=True, cascade="all, delete-orphan")
    servicos = db.relationship('ServicoCliente', backref='cliente', lazy=True, cascade="all, delete-orphan")
    contratos = db.relationship('ContratoRecorrente', backref='cliente', lazy=True, cascade="all, delete-orphan")
    propostas = db.relationship('Proposta', backref='cliente', lazy=True, cascade="all, delete-orphan")
    faturas = db.relationship('Fatura', backref='cliente', lazy=True, cascade="all, delete-orphan")
    contratos_gerados = db.relationship('ContratoGerado', backref='cliente', lazy=True, cascade="all, delete-orphan")

    @property
    def total_concluido(self):
        return sum(s.valor_cobrado for s in self.servicos if s.status == 'Concluido')

    @property
    def total_em_aberto(self):
        return sum(s.valor_cobrado for s in self.servicos if s.status in ['Em Andamento', 'Pendente', 'Bloqueado'])


class Documento(db.Model):
    __tablename__ = 'documentos'
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    tipo_documento = db.Column(db.String(50), nullable=False)
    nome_arquivo = db.Column(db.String(255), nullable=False)
    data_upload = db.Column(db.DateTime, default=datetime.utcnow)


class TipoServico(db.Model):
    __tablename__ = 'tipos_servico'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    nome = db.Column(db.String(150), nullable=False)
    descricao_padrao = db.Column(db.Text, nullable=True)
    valor_sugerido = db.Column(db.Float, default=0.0)
    modelo_cobranca = db.Column(db.String(20), default='pontual')
    unidade_medida = db.Column(db.String(30), default='un')
    margem_lucro_alvo = db.Column(db.Float, default=30.0)

    execucoes = db.relationship('ServicoCliente', backref='tipo_servico', lazy=True)
    custos_padrao = db.relationship('ServicoCustoPadrao', backref='tipo_servico', lazy=True, cascade="all, delete-orphan")

    @property
    def custo_total_estimado(self):
        return sum(c.custo_total for c in self.custos_padrao)


class ServicoCustoPadrao(db.Model):
    __tablename__ = 'servicos_custos_padrao'
    id = db.Column(db.Integer, primary_key=True)
    tipo_servico_id = db.Column(db.Integer, db.ForeignKey('tipos_servico.id'), nullable=False)
    tipo_custo = db.Column(db.String(30), nullable=False)
    descricao = db.Column(db.String(150), nullable=False)
    unidade = db.Column(db.String(30), default='un')
    quantidade = db.Column(db.Float, default=1.0)
    custo_unitario = db.Column(db.Float, default=0.0)

    @property
    def custo_total(self):
        return round((self.quantidade or 0.0) * (self.custo_unitario or 0.0), 2)


class ServicoCliente(db.Model):
    __tablename__ = 'servicos_cliente'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    tipo_servico_id = db.Column(db.Integer, db.ForeignKey('tipos_servico.id'), nullable=False)
    contrato_id = db.Column(db.Integer, db.ForeignKey('contratos_recorrentes.id'), nullable=True)
    fatura_id = db.Column(db.Integer, db.ForeignKey('faturas.id'), nullable=True)
    
    valor_cobrado = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(30), default='Em Andamento')
    data_solicitacao = db.Column(db.Date, default=date.today)
    data_previsao = db.Column(db.Date, nullable=True)
    observacoes = db.Column(db.Text, nullable=True)

    detalhamento_execucao = db.Column(db.Text, nullable=True)
    orientacoes_cliente = db.Column(db.Text, nullable=True)
    arquivo_evidencia = db.Column(db.String(255), nullable=True)

    data_vencimento_boleto = db.Column(db.Date, nullable=True)
    status_pagamento = db.Column(db.String(30), default='A Faturar')
    arquivo_boleto = db.Column(db.String(255), nullable=True)
    arquivo_nf = db.Column(db.String(255), nullable=True)
    historico_cobranca = db.Column(db.Text, nullable=True)


class Proposta(db.Model):
    __tablename__ = 'propostas'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    numero_proposta = db.Column(db.String(50), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    data_criacao = db.Column(db.Date, default=date.today)
    validade_dias = db.Column(db.Integer, default=15)
    condicoes_pagamento = db.Column(db.String(255), nullable=False)
    observacoes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default='Aguardando Aprovação')
    tipo_cobranca = db.Column(db.String(20), default='pontual')
    periodicidade = db.Column(db.String(20), default='mensal')
    dia_vencimento = db.Column(db.Integer, default=10)

    # Gestão de Termos Aditivos
    proposta_origem_id = db.Column(db.Integer, db.ForeignKey('propostas.id'), nullable=True)
    tipo_documento = db.Column(db.String(20), default='proposta')
    numero_aditivo = db.Column(db.Integer, default=0)

    # Condições de Parcelamento e Entrada
    exige_entrada = db.Column(db.Boolean, default=False)
    valor_entrada = db.Column(db.Float, default=0.0)
    forma_pagamento_entrada = db.Column(db.String(50), default='PIX')
    qtd_parcelas = db.Column(db.Integer, default=1)
    forma_pagamento_parcelas = db.Column(db.String(50), default='Boleto Bancário')
    intervalo_dias = db.Column(db.Integer, default=30)

    # Relacionamentos
    itens = db.relationship('ItemProposta', backref='proposta', lazy='select', cascade="all, delete-orphan")
    faturas = db.relationship('Fatura', backref='proposta', lazy='select')
    contratos_gerados = db.relationship('ContratoGerado', backref='proposta', lazy='select')

    @property
    def valor_total(self):
        if not self.itens:
            return 0.0
        return sum((item.valor_total or 0.0) for item in self.itens)

    @property
    def custo_total_previsto(self):
        if not self.itens:
            return 0.0
        return sum((item.custo_total or 0.0) for item in self.itens)

    @property
    def lucro_bruto_previsto(self):
        return round(self.valor_total - self.custo_total_previsto, 2)

    @property
    def margem_lucro_real(self):
        vt = self.valor_total
        if vt <= 0:
            return 0.0
        return round((self.lucro_bruto_previsto / vt) * 100.0, 1)


class ItemProposta(db.Model):
    __tablename__ = 'itens_proposta'
    id = db.Column(db.Integer, primary_key=True)
    proposta_id = db.Column(db.Integer, db.ForeignKey('propostas.id'), nullable=False)
    tipo_servico_id = db.Column(db.Integer, db.ForeignKey('tipos_servico.id'), nullable=False)
    
    unidade = db.Column(db.String(30), default='un')
    quantidade = db.Column(db.Float, default=1.0)
    valor_unitario = db.Column(db.Float, nullable=False, default=0.0)
    descricao_personalizada = db.Column(db.Text, nullable=True)
    exibir_detalhamento_proposta = db.Column(db.Boolean, default=False)

    tipo_servico = db.relationship('TipoServico', lazy='joined')
    custos = db.relationship('ItemPropostaCusto', backref='item_proposta', lazy='select', cascade="all, delete-orphan")

    @property
    def valor_total(self):
        qtd = float(self.quantidade) if self.quantidade is not None else 1.0
        val = float(self.valor_unitario) if self.valor_unitario is not None else 0.0
        return round(qtd * val, 2)

    @property
    def custo_total(self):
        if not self.custos:
            return 0.0
        return sum((c.custo_total or 0.0) for c in self.custos)


class ItemPropostaCusto(db.Model):
    __tablename__ = 'itens_proposta_custos'
    id = db.Column(db.Integer, primary_key=True)
    item_proposta_id = db.Column(db.Integer, db.ForeignKey('itens_proposta.id'), nullable=False)
    tipo_custo = db.Column(db.String(30), nullable=False)
    descricao = db.Column(db.String(150), nullable=False)
    unidade = db.Column(db.String(30), default='un')
    quantidade = db.Column(db.Float, default=1.0)
    custo_unitario = db.Column(db.Float, default=0.0)
    visivel_proposta = db.Column(db.Boolean, default=False)

    @property
    def custo_total(self):
        qtd = float(self.quantidade) if self.quantidade is not None else 1.0
        unit = float(self.custo_unitario) if self.custo_unitario is not None else 0.0
        return round(qtd * unit, 2)


class ContratoGerado(db.Model):
    __tablename__ = 'contratos_gerados'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    proposta_id = db.Column(db.Integer, db.ForeignKey('propostas.id'), nullable=True)
    
    numero_documento = db.Column(db.String(50), nullable=False)
    titulo = db.Column(db.String(150), nullable=False)
    conteudo_html = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default='minuta')
    
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    data_atualizacao = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    data_assinatura = db.Column(db.DateTime, nullable=True)


class ContratoRecorrente(db.Model):
    __tablename__ = 'contratos_recorrentes'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    tipo_servico_id = db.Column(db.Integer, db.ForeignKey('tipos_servico.id'), nullable=True)
    proposta_origem_id = db.Column(db.Integer, db.ForeignKey('propostas.id'), nullable=True)
    
    titulo = db.Column(db.String(150), nullable=False)
    valor_periodo = db.Column(db.Float, nullable=False, default=0.0)
    periodicidade = db.Column(db.String(20), default='mensal')
    dia_vencimento = db.Column(db.Integer, default=10)
    status = db.Column(db.String(20), default='Ativo')
    data_inicio = db.Column(db.Date, default=date.today)
    observacoes = db.Column(db.Text, nullable=True)

    tipo_servico = db.relationship('TipoServico')
    proposta = db.relationship('Proposta')
    lancamentos = db.relationship('ServicoCliente', backref='contrato', lazy=True)
    faturas = db.relationship('Fatura', backref='contrato', lazy=True)


class Fatura(db.Model):
    __tablename__ = 'faturas'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    proposta_id = db.Column(db.Integer, db.ForeignKey('propostas.id'), nullable=True)
    contrato_id = db.Column(db.Integer, db.ForeignKey('contratos_recorrentes.id'), nullable=True)

    descricao = db.Column(db.String(255), nullable=False)
    valor_total = db.Column(db.Float, default=0.0)
    data_emissao = db.Column(db.Date, default=date.today)
    arquivo_nf = db.Column(db.String(255), nullable=True)

    servicos = db.relationship('ServicoCliente', backref='fatura_vinculada', lazy=True)
    parcelas = db.relationship('ParcelaFatura', backref='fatura', lazy=True, cascade="all, delete-orphan")

    @property
    def total_parcelas(self):
        return len(self.parcelas)

    @property
    def total_pagas(self):
        return len([p for p in self.parcelas if p.status == 'Pago'])

    @property
    def status_geral(self):
        if not self.parcelas:
            return 'A Faturar'
        if all(p.status == 'Pago' for p in self.parcelas):
            return 'Pago'
        hoje = date.today()
        if any(p.status != 'Pago' and p.data_vencimento and p.data_vencimento < hoje for p in self.parcelas):
            return 'Em Atraso'
        if any(p.status == 'Boleto Emitido' for p in self.parcelas):
            return 'Aguardando Pagamento'
        return 'A Faturar'


class ParcelaFatura(db.Model):
    __tablename__ = 'parcelas_fatura'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    fatura_id = db.Column(db.Integer, db.ForeignKey('faturas.id'), nullable=False)
    
    numero_parcela = db.Column(db.Integer, default=1)
    total_parcelas = db.Column(db.Integer, default=1)
    descricao_parcela = db.Column(db.String(100), default='Parcela Única')
    is_entrada = db.Column(db.Boolean, default=False)
    
    forma_pagamento = db.Column(db.String(50), default='Boleto Bancário')
    valor = db.Column(db.Float, default=0.0)
    data_vencimento = db.Column(db.Date, nullable=False)
    
    status = db.Column(db.String(30), default='A Faturar')
    arquivo_comprovante_boleto = db.Column(db.String(255), nullable=True)
    historico_cobranca = db.Column(db.Text, nullable=True)


class ChamadoSuporte(db.Model):
    __tablename__ = 'chamados_suporte'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    
    numero_protocolo = db.Column(db.String(30), unique=True, nullable=False)
    assunto = db.Column(db.String(150), nullable=False)
    categoria = db.Column(db.String(50), default='Dúvida')
    prioridade = db.Column(db.String(20), default='Média')
    status = db.Column(db.String(30), default='Aberto')
    data_abertura = db.Column(db.DateTime, default=datetime.utcnow)
    data_fechamento = db.Column(db.DateTime, nullable=True)

    empresa = db.relationship('Empresa', backref='chamados')
    usuario = db.relationship('Usuario', backref='chamados_abertos')
    mensagens = db.relationship('MensagemChamado', backref='chamado', lazy=True, cascade="all, delete-orphan")


class MensagemChamado(db.Model):
    __tablename__ = 'mensagens_chamado'
    id = db.Column(db.Integer, primary_key=True)
    chamado_id = db.Column(db.Integer, db.ForeignKey('chamados_suporte.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    
    conteudo = db.Column(db.Text, nullable=False)
    is_suporte = db.Column(db.Boolean, default=False)
    anexo_filename = db.Column(db.String(255), nullable=True)
    data_envio = db.Column(db.DateTime, default=datetime.utcnow)

    usuario = db.relationship('Usuario')

class ServicoEtapaRastreio(db.Model):
    __tablename__ = 'servicos_etapas_rastreio'
    id = db.Column(db.Integer, primary_key=True)
    servico_cliente_id = db.Column(db.Integer, db.ForeignKey('servicos_cliente.id'), nullable=False)
    
    titulo_fase = db.Column(db.String(150), nullable=False)
    descricao_detalhes = db.Column(db.Text, nullable=True) # Insumos / Materiais
    data_inicio = db.Column(db.Date, nullable=True)
    data_fim = db.Column(db.Date, nullable=True)
    status_fase = db.Column(db.String(30), default='pendente') # 'pendente', 'em_andamento', 'concluido'
    ordem = db.Column(db.Integer, default=0)

    servico = db.relationship('ServicoCliente', backref=db.backref('etapas_rastreio', lazy=True, cascade="all, delete-orphan"))


class CupomDesconto(db.Model):
    __tablename__ = 'cupons_desconto'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    
    # Parâmetros Comerciais
    percentual_desconto = db.Column(db.Float, nullable=False, default=10.0)
    percentual_comissao = db.Column(db.Float, default=20.0)
    limite_usos = db.Column(db.Integer, default=100)
    usos_atuais = db.Column(db.Integer, default=0)
    data_validade = db.Column(db.Date, nullable=True)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    ativo = db.Column(db.Boolean, default=True)

    @property
    def is_valido(self):
        if not self.ativo:
            return False
        if self.limite_usos and self.usos_atuais >= self.limite_usos:
            return False
        if self.data_validade and self.data_validade < date.today():
            return False
        return True

class ComissaoAfiliado(db.Model):
    __tablename__ = 'comissoes_afiliados'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    cupom_id = db.Column(db.Integer, db.ForeignKey('cupons_desconto.id'), nullable=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    
    numero_parcela_parceiro = db.Column(db.Integer, nullable=False) # Ex: 2 (de 3)
    total_parcelas_permitidas = db.Column(db.Integer, default=3)   # Ex: 3
    
    valor_mensalidade = db.Column(db.Float, nullable=False)
    percentual_comissao = db.Column(db.Float, nullable=False)
    valor_comissao = db.Column(db.Float, nullable=False)
    mes_competencia = db.Column(db.String(7), nullable=False) # '2026-09'
    status = db.Column(db.String(30), default='pendente')     # 'pendente', 'liberado', 'pago'
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    data_pagamento = db.Column(db.DateTime, nullable=True)
    repasse_id = db.Column(db.Integer, db.ForeignKey('repasses_afiliados.id'), nullable=True)

    empresa = db.relationship('Empresa', lazy=True)
    parceiro = db.relationship('Usuario', foreign_keys=[usuario_id], lazy=True)

class RepasseAfiliado(db.Model):
    __tablename__ = 'repasses_afiliados'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    mes_competencia = db.Column(db.String(7), nullable=False)
    valor_total_pago = db.Column(db.Float, nullable=False)
    qtd_faturas_inclusas = db.Column(db.Integer, default=0)
    chave_pix_utilizada = db.Column(db.String(150), nullable=True)
    arquivo_comprovante = db.Column(db.String(255), nullable=True)
    data_pagamento = db.Column(db.DateTime, default=datetime.utcnow)
    observacoes = db.Column(db.Text, nullable=True)

    comissoes = db.relationship('ComissaoAfiliado', backref='repasse', lazy=True)