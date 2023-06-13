"""
This module will be responsible for the dokku commands
"""
# Dokku commands that we will use:
# dokku apps:list
# dokku apps:create <app-name>
# dokku apps:destroy <app-name>
# dokku apps:rename <app-name> <new-name>
from modules.ssh.ssh_connector import SSHConnector
from shared.clear import Clear


def apps_list() -> dict[str, list[str]]:
    """Get the list of apps from dokku"""
    clearer = Clear()
    client = SSHConnector()
    # only generate connection if it's not active
    if not client.verify_connection():
        print("Not generating connection")
        client.generate_connection()

    data: list[str] = client.run_command("dokku apps:list")

    if len(data) > 0:
        data.pop(0)  # Remove the first element, which is an message from dokku
        data = clearer.clear_response(data)
        return {"Apps": data}

    return {"Apps": []}
