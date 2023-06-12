# Dokku commands that we will use:
# dokku apps:list
# dokku apps:create <app-name>
# dokku apps:destroy <app-name>
# dokku apps:rename <app-name> <new-name>
from modules.ssh import sshConnector
from shared.clear import Clear


def appsList():
    clearer = Clear()
    # only generate connection if it's not active
    if not sshConnector.verifyConnection():
        print("Not generating connection")
        sshConnector.generateConnection()

    data = sshConnector.runCommand("dokku apps:list")
    data.pop(0)  # Remove the first element, which is an message from dokku
    data = clearer.clearResponse(data)

    return {"Apps": data}
