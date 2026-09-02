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
    endereco_completo = db.Column(db.String(255))
    
    # White-label
    logo_filename = db.Column(db.String(200))
    cor_primaria = db.Column(db.String(7), default="#1e3a8a")
    cor_secundaria = db.Column(db.String(7), default="#059669")
    cor_sidebar = db.Column(db.String(7), default="#ffffff")

    # Assinatura
    plano = db.Column(db.String(30), default="Founder")
    status_assinatura = db.Column(db.String(20), default="ativo")
    data_vencimento = db.Column(db.Date, nullable=True)
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


class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)
    cargo = db.Column(db.String(50), default="Administrador")
    nivel_acesso = db.Column(db.String(20), default="admin")
    ativo = db.Column(db.Boolean, default=True)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

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
    observacoes = db.Column(db.Text, nullable=True)

    # Relacionamentos
    documentos = db.relationship('Documento', backref='cliente', lazy=True, cascade="all, delete-orphan")
    servicos = db.relationship('ServicoCliente', backref='cliente', lazy=True, cascade="all, delete-orphan")
    contratos = db.relationship('ContratoRecorrente', backref='cliente', lazy=True, cascade="all, delete-orphan")
    propostas = db.relationship('Proposta', backref='cliente', lazy=True, cascade="all, delete-orphan")
    faturas = db.relationship('Fatura', backref='cliente', lazy=True, cascade="all, delete-orphan")

    # Cálculos dinâmicos para a tela de Detalhes
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

    execucoes = db.relationship('ServicoCliente', backref='tipo_servico', lazy=True)


class ServicoCliente(db.Model):
    __tablename__ = 'servicos_cliente'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    tipo_servico_id = db.Column(db.Integer, db.ForeignKey('tipos_servico.id'), nullable=False)
    contrato_id = db.Column(db.Integer, db.ForeignKey('contratos_recorrentes.id'), nullable=True)
    fatura_id = db.Column(db.Integer, db.ForeignKey('faturas.id'), nullable=True)
    
    valor_cobrado = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(30), default='Em Andamento') # 'Em Andamento', 'Pendente', 'Bloqueado', 'Concluido', 'Cancelado'
    data_solicitacao = db.Column(db.Date, default=date.today)
    data_previsao = db.Column(db.Date, nullable=True)
    observacoes = db.Column(db.Text, nullable=True)

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

    # Regras Comerciais de Parcelamento & Entrada
    exige_entrada = db.Column(db.Boolean, default=False)
    valor_entrada = db.Column(db.Float, default=0.0)
    forma_pagamento_entrada = db.Column(db.String(50), default='PIX')
    qtd_parcelas = db.Column(db.Integer, default=1)
    forma_pagamento_parcelas = db.Column(db.String(50), default='Boleto Bancário')
    intervalo_dias = db.Column(db.Integer, default=30)

    itens = db.relationship('ItemProposta', backref='proposta', lazy=True, cascade="all, delete-orphan")
    faturas = db.relationship('Fatura', backref='proposta', lazy=True)

    @property
    def valor_total(self):
        return sum(item.valor_unitario for item in self.itens)


class ItemProposta(db.Model):
    __tablename__ = 'itens_proposta'
    id = db.Column(db.Integer, primary_key=True)
    proposta_id = db.Column(db.Integer, db.ForeignKey('propostas.id'), nullable=False)
    tipo_servico_id = db.Column(db.Integer, db.ForeignKey('tipos_servico.id'), nullable=False)
    valor_unitario = db.Column(db.Float, nullable=False, default=0.0)
    descricao_personalizada = db.Column(db.Text, nullable=True)

    tipo_servico = db.relationship('TipoServico')


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
    
    status = db.Column(db.String(30), default='A Faturar') # 'A Faturar', 'Boleto Emitido', 'Pago', 'Em Atraso'
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