import io
import os
import uuid
import boto3
from botocore.config import Config
from werkzeug.utils import secure_filename

EXTENSOES_PERMITIDAS = {'pdf', 'png', 'jpg', 'jpeg', 'webp'}
MAX_TAMANHO_BYTES = 2 * 1024 * 1024  # 2 MB por arquivo

def obter_cliente_s3():
    """Conecta ao Supabase Storage via protocolo S3."""
    return boto3.client(
        's3',
        endpoint_url=os.getenv('SUPABASE_S3_ENDPOINT'),
        aws_access_key_id=os.getenv('SUPABASE_S3_ACCESS_KEY'),
        aws_secret_access_key=os.getenv('SUPABASE_S3_SECRET_KEY'),
        region_name=os.getenv('SUPABASE_S3_REGION', 'sa-east-1'),
        config=Config(signature_version='s3v4')
    )

def salvar_arquivo_supabase(file_storage, pasta_destino, empresa_id):
    """
    Valida extensão e tamanho (máx 2MB), renomeia com UUID e faz o upload.
    Retorna a chave única: emp_<id>/<pasta>/<uuid>.<ext>
    """
    if not file_storage or not getattr(file_storage, 'filename', None):
        return None

    nome_seguro = secure_filename(file_storage.filename)
    if '.' not in nome_seguro:
        raise ValueError("Arquivo sem extensão válida.")

    extensao = nome_seguro.rsplit('.', 1)[-1].lower()
    if extensao not in EXTENSOES_PERMITIDAS:
        raise ValueError(f"Extensão '.{extensao}' não é permitida por motivos de segurança.")

    # Validação rigorosa do tamanho (Máx 2 MB)
    file_storage.seek(0, os.SEEK_END)
    tamanho = file_storage.tell()
    file_storage.seek(0)

    if tamanho > MAX_TAMANHO_BYTES:
        raise ValueError("O arquivo excede o limite máximo permitido de 2 MB.")

    chave_bucket = f"emp_{empresa_id}/{pasta_destino}/{uuid.uuid4().hex}.{extensao}"
    bucket = os.getenv('SUPABASE_BUCKET_NAME', 'trivium-documentos')
    
    s3 = obter_cliente_s3()
    s3.upload_fileobj(
        file_storage,
        bucket,
        chave_bucket,
        ExtraArgs={
            'ContentType': file_storage.content_type or 'application/octet-stream'
        }
    )
    return chave_bucket

def excluir_arquivo_supabase(chave_bucket):
    """Remove o arquivo do bucket S3."""
    if not chave_bucket:
        return False
    try:
        bucket = os.getenv('SUPABASE_BUCKET_NAME', 'trivium-documentos')
        s3 = obter_cliente_s3()
        s3.delete_object(Bucket=bucket, Key=chave_bucket)
        return True
    except Exception as e:
        print(f"[ERRO AO EXCLUIR ARQUIVO S3]: {e}")
        return False

def gerar_url_temporaria(chave_bucket, tempo_segundos=900):
    """Gera link pré-assinado com validade de 15 minutos (900s)."""
    if not chave_bucket:
        return None

    bucket = os.getenv('SUPABASE_BUCKET_NAME', 'trivium-documentos')
    s3 = obter_cliente_s3()

    return s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': chave_bucket},
        ExpiresIn=tempo_segundos
    )

def obter_arquivo_bytes(chave_bucket):
    """
    Baixa os bytes do arquivo em memória (BytesIO).
    Ideal para alimentar o ReportLab (geração de PDF de logo) sem gravar no disco.
    """
    if not chave_bucket:
        return None
    try:
        bucket = os.getenv('SUPABASE_BUCKET_NAME', 'trivium-documentos')
        s3 = obter_cliente_s3()
        resposta = s3.get_object(Bucket=bucket, Key=chave_bucket)
        return io.BytesIO(resposta['Body'].read())
    except Exception as e:
        print(f"[ERRO AO BAIXAR BYTES S3]: {e}")
        return None