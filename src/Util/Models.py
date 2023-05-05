class UserLogin:
    def __init__(self, user_session: str,
                 user_session_length: int,
                 user_hash: str,
                 user_collection: str):
        self.user_session = user_session
        self.user_session_length = user_session_length
        self.user_hash = user_hash
        self.user_collection = user_collection
