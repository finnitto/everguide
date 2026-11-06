from app.celery_app import celery_app

@celery_app.task(name="everguide.system.ping")
def ping():
    # Diagnostic task proving that the Celery worker can execute jobs.
    return {"status": "ok", "task": "everguide.system.ping"}
