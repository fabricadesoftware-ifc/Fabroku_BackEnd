from typing import Union
from fastapi import FastAPI
from modules.ssh.sshConnector import SSHConnector
from modules.server import server

app = FastAPI()

sshClient = SSHConnector()


@app.get("/")
def read_root():
    return "Hello there! This is the Fabroku Api, for more info about how to use, go to /docs"


@app.get("/testSsh")
def test_ssh_connection():
    Data = sshClient.testConnection()

    return {"data": Data}


@app.post("/generatessh")
def generate_ssh_connection():
    Data = sshClient.generateConnection()
    return {"data": Data}


@app.get("/closeconnection")
def close_connection():
    sshClient.closeConnection()
    return "Connection closed"


@app.get("/appslist")
def apps_list():
    Data = server.appsList()
    return {"data": Data}
