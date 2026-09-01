from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask import current_app

def gerar_token_ativacao(email):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(email, salt='trivium-ativacao-conta-salt')

def validar_token_ativacao(token, max_age_segundos=86400):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = serializer.loads(token, salt='trivium-ativacao-conta-salt', max_age=max_age_segundos)
        return email
    except (SignatureExpired, BadSignature):
        return None

def gerar_token_recuperacao(email):
    """Gera um token com validade curta para redefinição de senha."""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(email, salt='trivium-reset-senha-salt')

def validar_token_recuperacao(token, max_age_segundos=1800):
    """Valida o token de redefinição de senha em até 30 minutos (1800s)."""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = serializer.loads(token, salt='trivium-reset-senha-salt', max_age=max_age_segundos)
        return email
    except (SignatureExpired, BadSignature):
        return None