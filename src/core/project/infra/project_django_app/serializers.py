from rest_framework import serializers
from core.project.infra.project_django_app.models import Network, Projeto


class NetworkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Network
        fields = ['id', 'name', 'description']


class ProjetoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Projeto
        fields = [
            'id',
            'usuario',
            'nome',
            'descricao',
            'tecnologia',
            'source_type',
            'source_url',
            'network',
            'porta',
            'variaveis_ambiente',
            'dominio',
            'status',
            'data_criacao',
            'data_ultima_atualizacao',
            'url_deploy',
        ]
        read_only_fields = ['usuario', 'dominio', 'status', 'data_criacao', 'data_ultima_atualizacao', 'url_deploy'] 