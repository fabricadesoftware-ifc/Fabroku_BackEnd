"""Tests for FakeDokkuPort implementation."""
from applications.ports.i_dokku import IDokkuPort
from tests.fakes import FakeDokkuPort


class TestFakeDokkuPortImplementsInterface:
    """Verify FakeDokkuPort properly implements IDokkuPort."""

    def test_fake_dokku_is_instance_of_interface(self):
        """FakeDokkuPort should be an instance of IDokkuPort."""
        fake = FakeDokkuPort()
        assert isinstance(fake, IDokkuPort)

    def test_create_app(self):
        """Test create_app method."""
        fake = FakeDokkuPort()
        fake.create_app('test-app')

        assert 'test-app' in fake.apps
        assert fake.apps['test-app']['status'] == 'created'
        assert 'create_app' in [call['method'] for call in fake.get_calls()]

    def test_delete_app(self):
        """Test delete_app method."""
        fake = FakeDokkuPort()
        fake.create_app('test-app')
        fake.delete_app('test-app')

        assert 'test-app' not in fake.apps

    def test_exists_app(self):
        """Test exists_app method."""
        fake = FakeDokkuPort()
        assert fake.exists_app('test-app') is False

        fake.create_app('test-app')
        assert fake.exists_app('test-app') is True

    def test_rename_app(self):
        """Test rename_app method."""
        fake = FakeDokkuPort()
        fake.create_app('old-name')
        fake.rename_app('old-name', 'new-name')

        assert 'old-name' not in fake.apps
        assert 'new-name' in fake.apps

    def test_sync_git_streaming(self):
        """Test sync_git_streaming method."""
        fake = FakeDokkuPort()
        fake.create_app('test-app')

        lines = []
        fake.sync_git_streaming('test-app', 'https://github.com/user/repo.git', 'main', on_line=lines.append)

        assert fake.apps['test-app']['status'] == 'running'
        assert fake.apps['test-app']['git_url'] == 'https://github.com/user/repo.git'
        assert lines

    def test_start_stop_restart(self):
        """Test start, stop, and restart methods."""
        fake = FakeDokkuPort()
        fake.create_app('test-app')

        fake.stop_app('test-app')
        assert fake.get_app_status('test-app') == 'stopped'

        fake.start_app('test-app')
        assert fake.get_app_status('test-app') == 'running'

        fake.restart_app('test-app')
        assert fake.get_app_status('test-app') == 'running'

    def test_env_vars(self):
        """Test set, get and unset environment variables."""
        fake = FakeDokkuPort()
        fake.create_app('test-app')

        fake.set_config('test-app', {'DATABASE_URL': 'postgres://localhost', 'SECRET_KEY': 'secret123'})

        assert fake.get_config('test-app', 'DATABASE_URL') == 'postgres://localhost'
        assert fake.get_config('test-app', 'SECRET_KEY') == 'secret123'
        assert 'DATABASE_URL' in fake.show_config('test-app')

        fake.unset_config('test-app', ['SECRET_KEY'])
        assert fake.get_config('test-app', 'SECRET_KEY') == ''

    def test_domain_and_letsencrypt(self):
        """Test get_app_domain and enable_letsencrypt."""
        fake = FakeDokkuPort()
        fake.create_app('test-app')

        assert fake.get_app_domain('test-app') is None
        fake.enable_letsencrypt('test-app')
        assert fake.apps['test-app']['letsencrypt'] is True

    def test_scale_process(self):
        """Test ps_scale and ps_scale_report methods."""
        fake = FakeDokkuPort()
        fake.create_app('test-app')

        fake.ps_scale('test-app', {'web': 3, 'worker': 2})

        assert fake.apps['test-app']['processes']['web'] == 3
        assert fake.apps['test-app']['processes']['worker'] == 2
        assert 'web=3' in fake.ps_scale_report('test-app')

    def test_start_database(self):
        """Test start_database method."""
        fake = FakeDokkuPort()

        output = fake.start_database('my-postgres')
        assert 'my-postgres' in output
        assert 'start_database' in [call['method'] for call in fake.get_calls()]

    def test_database_lifecycle(self):
        """Test create/link/unlink/delete_database and enable_postgis."""
        fake = FakeDokkuPort()

        fake.create_database('my-db', 'secret')
        assert 'my-db' in fake.databases

        link_output = fake.link_database('my-db', 'my-app')
        assert 'my-db' in link_output
        assert fake.databases['my-db']['linked_apps'] == {'my-app': None}

        fake.unlink_database('my-db', 'my-app')
        assert fake.databases['my-db']['linked_apps'] == {}

        assert 'postgis' in fake.enable_postgis('my-db').lower()

        fake.delete_database('my-db')
        assert 'my-db' not in fake.databases

    def test_redis_lifecycle(self):
        """Test create/link/unlink/delete_redis and start_redis."""
        fake = FakeDokkuPort()

        fake.create_redis('my-redis')
        assert 'my-redis' in fake.redis_instances

        fake.link_redis('my-redis', 'my-app')
        assert fake.redis_instances['my-redis']['linked_apps'] == {'my-app': None}

        fake.unlink_redis('my-redis', 'my-app')
        assert fake.redis_instances['my-redis']['linked_apps'] == {}

        fake.start_redis('my-redis')
        fake.delete_redis('my-redis')
        assert 'my-redis' not in fake.redis_instances

    def test_run_command(self):
        """Test run_in_app and run_in_app_streaming methods."""
        fake = FakeDokkuPort()
        fake.create_app('test-app')

        output = fake.run_in_app('test-app', 'python manage.py migrate')
        assert 'test-app' in output

        streamed = list(fake.run_in_app_streaming('test-app', 'python manage.py migrate'))
        assert streamed

    def test_call_logging(self):
        """Test that method calls are logged."""
        fake = FakeDokkuPort()
        fake.create_app('test-app')
        fake.get_app_status('test-app')

        calls = fake.get_calls()
        assert len(calls) == 2
        assert calls[0]['method'] == 'create_app'
        assert calls[1]['method'] == 'get_app_status'

        fake.clear_logs()
        assert len(fake.get_calls()) == 0
