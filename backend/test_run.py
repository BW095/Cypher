from app.ingestion.pipeline import IngestionPipeline
import os
import sys

pipeline = IngestionPipeline()
test_dir = "/home/bw/CODES/test"
for f in os.listdir(test_dir):
    full_path = os.path.join(test_dir, f)
    if os.path.isfile(full_path):
        print(f"Testing {full_path}...")
        pipeline.process_file(full_path)
        break # just test one
