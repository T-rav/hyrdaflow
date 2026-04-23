def run():
    return None


class RateLimiter:
    def __init__(self, per_second):
        self.per_second = per_second

    def allow(self):
        return True
