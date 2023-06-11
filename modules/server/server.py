# Dokku commands that we will use:
# dokku apps:list
# dokku apps:create <app-name>
# dokku apps:destroy <app-name>
# dokku apps:rename <app-name> <new-name>
from modules.ssh import sshConnector

def appsList():
    #only generate connection if it's not active
    if(not sshConnector.verifyConnection()):
        print("Not generating connection")
        sshConnector.generateConnection()
    
    Data = sshConnector.runCommand("dokku apps:list")
    Data.pop(0) # Remove the first element, which is an message from dokku
    Data = clearResponse(Data)
 
    return {"Apps": Data}

def clearResponse(data):
    #remove /n from the strings in the list
    data = [x.replace("\n", "") for x in data]

    #remove empty spaces
    data = [x.strip() for x in data]

    #remove empty strings
    data = list(filter(None, data))

    return data