release: python src/manage.py migrate --noinput
web: daphne -b 0.0.0.0 -p $PORT config.asgi:application
worker: celery -A src.config worker -l info --concurrency=4
flower: celery -A src.config flower --address=0.0.0.0 --port=${PORT:-5000} --url_prefix=/flower --basic_auth=${FLOWER_BASIC_AUTH} --broker_api=${FLOWER_BROKER_API}
interactive: python src/manage.py run_interactive_sessions
logstream: python src/manage.py run_log_streams
