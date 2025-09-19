import logging, logging.handlers
from uvicorn import run
from main_api import app

def setup_logging():
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    # error ???????
    eh = logging.handlers.RotatingFileHandler("logs/error.log", mode="a",
                                              maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
    eh.setLevel(logging.INFO); eh.setFormatter(fmt)
    logging.getLogger("uvicorn.error").handlers = [eh]
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    # access ???????
    ah = logging.handlers.RotatingFileHandler("logs/access.log", mode="a",
                                              maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
    afmt = logging.Formatter('%(asctime)s - %(client_addr)s - "%(request_line)s" %(status_code)s')
    ah.setLevel(logging.INFO); ah.setFormatter(afmt)
    logging.getLogger("uvicorn.access").handlers = [ah]
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

if __name__ == "__main__":
    setup_logging()
    run(app, host="127.0.0.1", port=8000, reload=True)
