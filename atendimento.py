from flask import Blueprint, request, render_template
import html
from datetime import datetime, timezone, timedelta

atendimento_bp = Blueprint(
    "atendimento",
    __name__
)
def configurar_atendimento(dependencias):
    pass
