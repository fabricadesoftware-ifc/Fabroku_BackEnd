class Clear:
    def __init__(self, success: bool):
        self.success = success

    def clearResponse(self, data):
        # remove /n from the strings in the list
        data = [x.replace("\n", "") for x in data]

        # remove empty spaces
        data = [x.strip() for x in data]

        # remove empty strings
        data = list(filter(None, data))

        return data
