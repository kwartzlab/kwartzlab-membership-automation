import config
import db
import time
import slack

if __name__ == "__main__":
    cfg = config.load_config()
    engine = db.create_db_engine(cfg)
    print("Database engine created successfully:", engine)
    
    # main loop
    while(True):
        try:
            work_done = db.process_one(engine)
            if work_done:
                print("Processed outbox item.")
            else:
                print("No outbox items to process.")
        except Exception as e:
            print("Error processing outbox item:", e)
            
        time.sleep(10)  # wait before polling again
