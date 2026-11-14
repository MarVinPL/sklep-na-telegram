import logging
import time

from app.db import SessionLocal
from app.services.recovery_notifications import dispatch_due_notifications

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    while True:
        try:
            with SessionLocal() as db:
                delivered = dispatch_due_notifications(db)
            if delivered:
                logger.info("Delivered %s recovery notifications", delivered)
        except Exception:
            # Never log payloads, addresses, tokens, or provider diagnostics.
            logger.exception("Recovery notification worker cycle failed")
        time.sleep(5)


if __name__ == "__main__":
    main()
