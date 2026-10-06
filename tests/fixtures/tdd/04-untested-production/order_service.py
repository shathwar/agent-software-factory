class OrderService:
    def __init__(self, repo):
        self.repo = repo

    def process_order(self, order_id: str, amount: float) -> bool:
        if amount <= 0:
            raise ValueError("Amount must be positive")
        return self.repo.charge_and_save(order_id, amount)
