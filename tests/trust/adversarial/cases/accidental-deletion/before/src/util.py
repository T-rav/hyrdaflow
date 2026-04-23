def load_config(path):
    with open(path) as f:
        return f.read()


def save_config(path, data):
    with open(path, "w") as f:
        f.write(data)
