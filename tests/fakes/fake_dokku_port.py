"""Fake Dokku adapter for testing."""
from typing import Any, Callable, Generator

from applications.ports.i_dokku import IDokkuPort, InteractiveChannel


class FakeInteractiveChannel:
    """Scripted duplex channel for testing `open_interactive_channel` callers.

    `scripted_outputs` is a queue of canned `read_output()` results. Each `write()` call
    (simulating an answer being sent to the remote process) advances the queue by exposing
    the next scripted output — mirrors a real interactive process producing new output only
    in response to input. `exit_status_ready()` becomes true once the queue is exhausted.
    """

    def __init__(self, scripted_outputs: list[str] | None = None, exit_status: int = 0):
        scripted_outputs = list(scripted_outputs or [])
        self.pending_outputs = [scripted_outputs[0]] if scripted_outputs else []
        self.future_outputs = scripted_outputs[1:]
        self._exit_status = exit_status
        self.written_inputs: list[str] = []
        self.timeout: float | None = None
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def write(self, data: str) -> None:
        self.written_inputs.append(data.rstrip('\n'))
        if self.future_outputs:
            self.pending_outputs.append(self.future_outputs.pop(0))

    def read_output(self) -> str:
        if not self.pending_outputs:
            return ''
        return self.pending_outputs.pop(0)

    def exit_status_ready(self) -> bool:
        return not self.pending_outputs and not self.future_outputs

    def exit_status(self) -> int:
        return self._exit_status

    def close(self) -> None:
        self.closed = True


class FakeDokkuPort(IDokkuPort):  # noqa: PLR0904
    """In-memory implementation of IDokkuPort for testing."""

    def __init__(self):
        """Initialize fake Dokku port."""
        self.apps: dict[str, dict[str, Any]] = {}
        self.databases: dict[str, dict[str, Any]] = {}
        self.redis_instances: dict[str, dict[str, Any]] = {}
        self.call_log: list[dict] = []
        self.interactive_channel_factory: Callable[[str], InteractiveChannel] | None = None

    def _require_app(self, app_name: str) -> dict:
        if app_name not in self.apps:
            raise ValueError(f'App {app_name} not found')
        return self.apps[app_name]

    def create_app(self, app_name: str) -> str:
        self._log_call('create_app', {'app_name': app_name})
        if app_name in self.apps:
            raise ValueError(f'App {app_name} already exists')
        self.apps[app_name] = {
            'status': 'created',
            'env_vars': {},
            'domain': None,
            'letsencrypt': False,
            'git_url': None,
            'branch': None,
            'processes': {},
        }
        return f'App {app_name} created'

    def delete_app(self, app_name: str) -> str:
        self._log_call('delete_app', {'app_name': app_name})
        self._require_app(app_name)
        del self.apps[app_name]
        return f'App {app_name} deleted'

    def exists_app(self, app_name: str) -> bool:
        self._log_call('exists_app', {'app_name': app_name})
        return app_name in self.apps

    def rename_app(self, old_name: str, new_name: str) -> str:
        self._log_call('rename_app', {'old_name': old_name, 'new_name': new_name})
        self.apps[new_name] = self.apps.pop(self._key_or_raise(old_name))
        return f'App {old_name} renamed to {new_name}'

    def _key_or_raise(self, app_name: str) -> str:
        self._require_app(app_name)
        return app_name

    def start_app(self, app_name: str) -> str:
        self._log_call('start_app', {'app_name': app_name})
        self._require_app(app_name)['status'] = 'running'
        return f'App {app_name} started'

    def stop_app(self, app_name: str) -> str:
        self._log_call('stop_app', {'app_name': app_name})
        self._require_app(app_name)['status'] = 'stopped'
        return f'App {app_name} stopped'

    def restart_app(self, app_name: str) -> str:
        self._log_call('restart_app', {'app_name': app_name})
        self._require_app(app_name)['status'] = 'running'
        return f'App {app_name} restarted'

    def get_app_status(self, app_name: str) -> str:
        self._log_call('get_app_status', {'app_name': app_name})
        return self._require_app(app_name)['status']

    def sync_git_streaming(
        self,
        app_name: str,
        git_url: str,
        branch: str = 'main',
        on_line: Callable[[str], None] | None = None,
    ) -> str:
        self._log_call('sync_git_streaming', {'app_name': app_name, 'git_url': git_url, 'branch': branch})
        app = self._require_app(app_name)
        app['git_url'] = git_url
        app['branch'] = branch
        app['status'] = 'running'
        if on_line:
            on_line(f'Deploying {app_name} from {git_url}@{branch}')
        return f'App {app_name} synced'

    def set_git_remote(self, app_name: str, git_url: str) -> str:
        self._log_call('set_git_remote', {'app_name': app_name, 'git_url': git_url})
        self._require_app(app_name)['git_url'] = git_url
        return f'App {app_name} remote set'

    def set_config(self, app_name: str, env_vars: dict[str, str], no_restart: bool = False) -> str:
        self._log_call('set_config', {'app_name': app_name, 'env_vars': env_vars, 'no_restart': no_restart})
        self._require_app(app_name)['env_vars'].update(env_vars)
        return f'Config set for {app_name}'

    def unset_config(self, app_name: str, keys: list[str], no_restart: bool = False) -> str:
        self._log_call('unset_config', {'app_name': app_name, 'keys': keys, 'no_restart': no_restart})
        env_vars = self._require_app(app_name)['env_vars']
        for key in keys:
            env_vars.pop(key, None)
        return f'Config unset for {app_name}'

    def get_config(self, app_name: str, key: str) -> str:
        self._log_call('get_config', {'app_name': app_name, 'key': key})
        return self._require_app(app_name)['env_vars'].get(key, '')

    def show_config(self, app_name: str) -> str:
        self._log_call('show_config', {'app_name': app_name})
        env_vars = self._require_app(app_name)['env_vars']
        return '\n'.join(f'{k}: {v}' for k, v in env_vars.items())

    def get_app_domain(self, app_name: str) -> str | None:
        self._log_call('get_app_domain', {'app_name': app_name})
        return self._require_app(app_name)['domain']

    def enable_letsencrypt(self, app_name: str) -> str:
        self._log_call('enable_letsencrypt', {'app_name': app_name})
        self._require_app(app_name)['letsencrypt'] = True
        return f'Let\'s Encrypt enabled for {app_name}'

    def run_in_app(self, app_name: str, command: str) -> str:
        self._log_call('run_in_app', {'app_name': app_name, 'command': command})
        self._require_app(app_name)
        return f'[FAKE OUTPUT] command "{command}" executed in {app_name}'

    def run_in_app_streaming(self, app_name: str, command: str) -> Generator[str, None, int]:
        self._log_call('run_in_app_streaming', {'app_name': app_name, 'command': command})
        self._require_app(app_name)
        yield f'[FAKE OUTPUT] command "{command}" executed in {app_name}'
        return 0

    def ps_scale(self, app_name: str, processes: dict[str, int], skip_deploy: bool = False) -> str:
        self._log_call('ps_scale', {'app_name': app_name, 'processes': processes, 'skip_deploy': skip_deploy})
        self._require_app(app_name)['processes'].update(processes)
        return f'App {app_name} scaled'

    def ps_scale_report(self, app_name: str) -> str:
        self._log_call('ps_scale_report', {'app_name': app_name})
        processes = self._require_app(app_name)['processes']
        return '\n'.join(f'{k}={v}' for k, v in processes.items())

    def start_database(self, db_name: str) -> str:
        self._log_call('start_database', {'db_name': db_name})
        return f'Database {db_name} started'

    def stop_database(self, db_name: str) -> str:
        self._log_call('stop_database', {'db_name': db_name})
        return f'Database {db_name} stopped'

    def remove_postgres_container(self, db_name: str) -> str:
        self._log_call('remove_postgres_container', {'db_name': db_name})
        return f'Container for {db_name} removed'

    def create_database(
        self,
        db_name: str,
        password: str,
        *,
        image: str | None = None,
        image_version: str | None = None,
    ) -> str:
        self._log_call(
            'create_database', {'db_name': db_name, 'image': image, 'image_version': image_version}
        )
        if db_name in self.databases:
            raise ValueError(f'Database {db_name} already exists')
        self.databases[db_name] = {'password': password, 'linked_apps': {}}
        return f'Database {db_name} created'

    def delete_database(self, db_name: str) -> str:
        self._log_call('delete_database', {'db_name': db_name})
        self.databases.pop(db_name, None)
        return f'Database {db_name} deleted'

    def link_database(
        self, db_name: str, app_name: str, no_restart: bool = False, alias: str | None = None
    ) -> str:
        self._log_call(
            'link_database', {'db_name': db_name, 'app_name': app_name, 'no_restart': no_restart, 'alias': alias}
        )
        if db_name not in self.databases:
            raise ValueError(f'Database {db_name} not found')
        self.databases[db_name]['linked_apps'][app_name] = alias
        url = f'postgres://fake/{db_name}'
        if app_name in self.apps:
            env_key = f'{alias}_URL' if alias else 'DATABASE_URL'
            self.apps[app_name]['env_vars'][env_key] = url
        return f'DATABASE_URL: {url}'

    def unlink_database(self, db_name: str, app_name: str) -> str:
        self._log_call('unlink_database', {'db_name': db_name, 'app_name': app_name})
        if db_name in self.databases:
            self.databases[db_name]['linked_apps'].pop(app_name, None)
        url = f'postgres://fake/{db_name}'
        if app_name in self.apps:
            env_vars = self.apps[app_name]['env_vars']
            for key in [k for k, v in env_vars.items() if v == url]:
                del env_vars[key]
        return f'Database {db_name} unlinked from {app_name}'

    def promote_database(self, db_name: str, app_name: str) -> str:
        self._log_call('promote_database', {'db_name': db_name, 'app_name': app_name})
        return f'Database {db_name} promoted for {app_name}'

    def enable_postgis(self, db_name: str) -> str:
        self._log_call('enable_postgis', {'db_name': db_name})
        return 'postgis_version\n----------------\n3.4 USE_GEOS=1'

    def create_redis(self, service_name: str) -> str:
        self._log_call('create_redis', {'service_name': service_name})
        if service_name in self.redis_instances:
            raise ValueError(f'Redis {service_name} already exists')
        self.redis_instances[service_name] = {'linked_apps': {}}
        return f'Redis {service_name} created'

    def delete_redis(self, service_name: str) -> str:
        self._log_call('delete_redis', {'service_name': service_name})
        self.redis_instances.pop(service_name, None)
        return f'Redis {service_name} deleted'

    def link_redis(
        self, service_name: str, app_name: str, no_restart: bool = False, alias: str | None = None
    ) -> str:
        self._log_call(
            'link_redis',
            {'service_name': service_name, 'app_name': app_name, 'no_restart': no_restart, 'alias': alias},
        )
        if service_name not in self.redis_instances:
            raise ValueError(f'Redis {service_name} not found')
        self.redis_instances[service_name]['linked_apps'][app_name] = alias
        url = f'redis://fake/{service_name}'
        if app_name in self.apps:
            env_key = f'{alias}_URL' if alias else 'REDIS_URL'
            self.apps[app_name]['env_vars'][env_key] = url
        return f'REDIS_URL: {url}'

    def unlink_redis(self, service_name: str, app_name: str) -> str:
        self._log_call('unlink_redis', {'service_name': service_name, 'app_name': app_name})
        if service_name in self.redis_instances:
            self.redis_instances[service_name]['linked_apps'].pop(app_name, None)
        url = f'redis://fake/{service_name}'
        if app_name in self.apps:
            env_vars = self.apps[app_name]['env_vars']
            for key in [k for k, v in env_vars.items() if v == url]:
                del env_vars[key]
        return f'Redis {service_name} unlinked from {app_name}'

    def start_redis(self, service_name: str) -> str:
        self._log_call('start_redis', {'service_name': service_name})
        return f'Redis {service_name} started'

    def open_interactive_channel(self, command: str) -> InteractiveChannel:
        self._log_call('open_interactive_channel', {'command': command})
        if self.interactive_channel_factory is None:
            raise RuntimeError(
                'FakeDokkuPort.interactive_channel_factory must be set before calling '
                'open_interactive_channel() in a test.'
            )
        return self.interactive_channel_factory(command)

    def _log_call(self, method_name: str, args: dict) -> None:
        """Log method calls for testing and debugging."""
        self.call_log.append({'method': method_name, 'args': args})

    def get_calls(self) -> list[dict]:
        """Get list of all logged calls."""
        return self.call_log.copy()

    def clear_logs(self) -> None:
        """Clear the call log."""
        self.call_log.clear()
