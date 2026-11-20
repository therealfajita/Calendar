# Gunicorn settings used on Render (see render.yaml startCommand).

# One worker process so only one background feed-sync thread runs.
# Threads let that worker handle several requests at once.
workers = 1
threads = 4


def post_worker_init(worker):
    """Start the 15-minute calendar feed sync once the worker is up.

    Gunicorn imports app.py instead of running it, so the code under
    `if __name__ == "__main__"` never runs in production.
    """
    import app

    app.start_background_sync()
