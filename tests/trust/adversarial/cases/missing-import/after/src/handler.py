def handle(event):
    logger.info("handling %s", event)
    return event.get("data")
