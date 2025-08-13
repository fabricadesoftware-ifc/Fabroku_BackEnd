web: gunicorn django_project.wsgi --chdir src --bind 0.0.0.0:$PORT
release: python src/manage.py migrate --noinput && python src/manage.py collectstatic --noinput