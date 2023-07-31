"""
@snow-sr
This module is used to create a connection to the database
and create the common methods to use it.
"""
from prisma import Prisma


def main() -> None:
    """
    Connection to the database
    """
    db_con = Prisma()
    db_con.connect()

    db_con.disconnect()


if __name__ == "__main__":
    main()
