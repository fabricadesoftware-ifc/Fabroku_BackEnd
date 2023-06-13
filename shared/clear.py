"""
Module for clearing the response from the server
"""


class Clear:
    """
    Class for clearing the response from the server
    """

    def clear_response(self, data: list[str]) -> list[str]:
        """Clear the response from the server"""
        # remove /n from the strings in the list
        to_be_cleared: list[str] = data
        to_be_cleared: list[str] = [x.replace("\n", "") for x in to_be_cleared]

        # remove empty spaces
        to_be_cleared = [x.strip() for x in to_be_cleared]

        # remove empty strings
        to_be_cleared = list(filter(None, to_be_cleared))

        return to_be_cleared

    def clear_response_string(self, data: str) -> str:
        """Clear the response from the server"""
        # remove /n from the strings in the list
        to_be_cleared: str = data
        to_be_cleared: str = to_be_cleared.replace("\n", "")

        # remove empty spaces
        to_be_cleared = to_be_cleared.strip()

        return to_be_cleared
