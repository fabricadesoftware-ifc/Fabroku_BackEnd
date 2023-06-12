# Dokku commands that we will use:
# dokku apps:list
# dokku apps:create <app-name>
# dokku apps:destroy <app-name>
# dokku apps:rename <app-name> <new-name>
from modules.ssh.sshConnector import SSHConnector
from shared.clear import Clear


def appsList():
    clearer = Clear()
    client = SSHConnector()
    # only generate connection if it's not active
    if not client.verifyConnection():
        print("Not generating connection")
        client.generateConnection()

    data = client.runCommand("dokku apps:list")
    data.pop(0)  # Remove the first element, which is an message from dokku
    data = clearer.clearResponse(data)

    return {"Apps": data}
