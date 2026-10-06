# Speculative factory and shallow wrapper for a single concrete class
class ConcreteUserService:
    def get_user(self, user_id: str) -> dict:
        return {"id": user_id, "name": "Alice"}


class UserServiceFactory:
    @staticmethod
    def create() -> ConcreteUserService:
        return ConcreteUserService()


class ShallowUserWrapper:
    def __init__(self, inner: ConcreteUserService):
        self.inner = inner

    def get_user(self, user_id: str) -> dict:
        return self.inner.get_user(user_id)

    def find_user(self, user_id: str) -> dict:
        return self.inner.get_user(user_id)
