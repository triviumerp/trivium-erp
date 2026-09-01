from app import app
from extensions import db
from models import Empresa, Cliente

with app.app_context():
    empresa = Empresa.query.first()

    if not empresa:
        print("ERRO: Nenhuma empresa encontrada. Crie sua conta primeiro em /auth/registro")
    else:
        clientes_dados = [
            {
                "nome": "Condomínio Residencial Parque das Flores",
                "nome_fantasia": "Residencial Parque das Flores",
                "cnpj_cpf": "12.345.678/0001-90",
                "inscricao_estadual": "Isento",
                "responsavel": "Carlos Eduardo (Síndico)",
                "telefone": "(11) 98765-4321",
                "telefone_secundario": "(11) 4748-0000",
                "email": "contato@parquedasflores.com.br",
                "email_financeiro": "financeiro@parquedasflores.com.br",
                "cep": "08674-000",
                "logradouro": "Rua das Palmeiras",
                "numero": "150",
                "complemento": "Portaria Principal",
                "bairro": "Jardim América",
                "cidade": "Suzano",
                "estado": "SP",
                "observacoes": "Contrato de assessoria técnica mensal com vistoria periódica."
            },
            {
                "nome": "Logística & Transportes Horizonte Ltda",
                "nome_fantasia": "Horizonte Log",
                "cnpj_cpf": "23.456.789/0001-01",
                "inscricao_estadual": "671.234.567.890",
                "responsavel": "Mariana Souza (Gerente Operacional)",
                "telefone": "(11) 97654-3210",
                "telefone_secundario": "(11) 4748-1122",
                "email": "operacoes@horizontelog.com.br",
                "email_financeiro": "contabilidade@horizontelog.com.br",
                "cep": "08685-100",
                "logradouro": "Avenida Industrial",
                "numero": "2400",
                "complemento": "Galpão 03 - Setor de Cargas",
                "bairro": "Distrito Industrial",
                "cidade": "Suzano",
                "estado": "SP",
                "observacoes": "Demanda laudos periciais e vistorias semestrais nas empilhadeiras."
            },
            {
                "nome": "Marcelo Henrique da Silva",
                "nome_fantasia": None,
                "cnpj_cpf": "390.548.218-05",
                "inscricao_estadual": None,
                "responsavel": "Marcelo",
                "telefone": "(11) 97412-8899",
                "telefone_secundario": None,
                "email": "marcelo.silva.consultoria@gmail.com",
                "email_financeiro": "marcelo.pagamentos@gmail.com",
                "cep": "08670-200",
                "logradouro": "Rua General Francisco Glicério",
                "numero": "420",
                "complemento": "Sala 12",
                "bairro": "Centro",
                "cidade": "Suzano",
                "estado": "SP",
                "observacoes": "Solicitou proposta de treinamento técnico para sua equipe de campo."
            },
            {
                "nome": "Auto Posto Estrela de Suzano Ltda",
                "nome_fantasia": "Posto Estrela",
                "cnpj_cpf": "34.567.890/0001-12",
                "inscricao_estadual": "671.998.776.554",
                "responsavel": "Roberto Alcantara",
                "telefone": "(11) 93210-9876",
                "telefone_secundario": None,
                "email": "gerencia@postoestrelasuzano.com.br",
                "email_financeiro": "financeiro@postoestrelasuzano.com.br",
                "cep": "08675-010",
                "logradouro": "Rua Baruel",
                "numero": "850",
                "complemento": None,
                "bairro": "Vila Costa",
                "cidade": "Suzano",
                "estado": "SP",
                "observacoes": "Renovação anual de licenças ambientais e laudos de SPDA."
            },
            {
                "nome": "Centro Médico e Diagnósticos São Camilo Ltda",
                "nome_fantasia": "Clínica São Camilo",
                "cnpj_cpf": "45.678.901/0001-23",
                "inscricao_estadual": "Isento",
                "responsavel": "Dra. Fabiana Toledo",
                "telefone": "(11) 4744-8800",
                "telefone_secundario": "(11) 98111-2233",
                "email": "administracao@clinicasaocamilo.com.br",
                "email_financeiro": "nfe@clinicasaocamilo.com.br",
                "cep": "08674-110",
                "logradouro": "Avenida Armando Salles de Oliveira",
                "numero": "310",
                "complemento": "Andar 2 - Recepção",
                "bairro": "Jardim Suzano",
                "cidade": "Suzano",
                "estado": "SP",
                "observacoes": "Prestação de serviços contínuos de assessoria e ergonomia."
            }
        ]

        for item in clientes_dados:
            novo_cliente = Cliente(
                empresa_id=empresa.id,
                nome=item["nome"],
                nome_fantasia=item["nome_fantasia"],
                cnpj_cpf=item["cnpj_cpf"],
                inscricao_estadual=item["inscricao_estadual"],
                responsavel=item["responsavel"],
                telefone=item["telefone"],
                telefone_secundario=item["telefone_secundario"],
                email=item["email"],
                email_financeiro=item["email_financeiro"],
                cep=item["cep"],
                logradouro=item["logradouro"],
                numero=item["numero"],
                complemento=item["complemento"],
                bairro=item["bairro"],
                cidade=item["cidade"],
                estado=item["estado"],
                observacoes=item["observacoes"]
            )
            db.session.add(novo_cliente)

        db.session.commit()
        print(f">> Sucesso! 5 clientes cadastrados para a empresa: {empresa.razao_social} (ID: {empresa.id})")