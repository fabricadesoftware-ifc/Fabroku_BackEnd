from typing import Union
from fastapi import FastAPI
from modules.ssh import sshConnector
from modules.server import server

app = FastAPI()


@app.get("/")
def read_root():
    return "Hello there! This is the Fabroku Api, for more info about how to use, go to /docs"


@app.get("/testSsh")
def test_ssh_connection():
    Data = sshConnector.testConnection()

    return {"data": Data}


@app.post("/generatessh")
def generate_ssh_connection():
    Data = sshConnector.generateConnection()
    return {"data": Data}


@app.get("/closeconnection")
def close_connection():
    sshConnector.client.close()
    return "Connection closed"


@app.get("/appslist")
def apps_list():
    Data = server.appsList()
    return {"data": Data}
