release: python src/manage.py migrate
web: gunicorn --pythonpath src config.wsgi:application --timeout 120
worker: celery -A src.config worker -l info
flower: celery -A src.config flower --address=0.0.0.0 --port=${PORT:-5000} --url_prefix=/flower --basic_auth=${FLOWER_BASIC_AUTH}
