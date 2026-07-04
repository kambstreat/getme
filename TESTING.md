# Testing Guide for GetME!

This guide covers how to test the GetME! application, including the new polling and incremental processing features.

## Prerequisites

1. **Python Environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Google Drive Setup**
   - Create a service account in Google Cloud Console
   - Enable Google Drive API
   - Download the service account JSON key
   - Share a test Drive folder with the service account email (read permission)

3. **Configuration**
   ```bash
   cp .env.example .env
   # Edit .env and set:
   # - ADMIN_TOKEN=your-secret-token
   # - GOOGLE_SERVICE_ACCOUNT_FILE=path/to/service_account.json
   ```

4. **Test Data**
   - Prepare a Google Drive folder with 5-10 test images containing faces
   - Have additional images ready to test incremental processing

## Running the Application

```bash
# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# The app will be available at:
# - Admin interface: http://localhost:8000/admin
# - Guest interface: http://localhost:8000/
# - API docs: http://localhost:8000/docs
```

## Test Scenarios

### Test 1: Basic Full Processing

**Objective**: Verify the app can process a folder of images and detect faces.

1. Open http://localhost:8000/admin in your browser
2. Enter your admin token
3. Paste your Google Drive folder link
4. Click "Process Folder"
5. Monitor the status updates
6. Verify:
   - Status progresses through: pending → listing → processing → clustering → done
   - `processed_files` count increases
   - `faces_found` count increases
   - `clusters` count shows the number of detected people

**Expected Result**: All images processed, faces clustered by person.

### Test 2: Guest Selfie Matching

**Objective**: Verify guests can upload a selfie and find their photos.

1. Open http://localhost:8000/ (guest page)
2. Upload a selfie of someone who appears in the processed photos
3. Verify:
   - Match is successful
   - Confidence score is shown
   - Photo count is correct
   - Thumbnail gallery displays
   - "Download All" button works

**Expected Result**: Correct photos returned for the person in the selfie.

### Test 3: Manual Incremental Processing

**Objective**: Test incremental processing without polling.

1. Complete Test 1 (initial full processing)
2. Add 2-3 NEW images to the Google Drive folder
3. Use curl or Postman to trigger incremental processing:

```bash
curl -X POST http://localhost:8000/api/drive/process \
  -H "x-admin-token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "drive_link": "YOUR_DRIVE_LINK",
    "incremental": true
  }'
```

4. Check the job status:
```bash
curl http://localhost:8000/api/drive/status/JOB_ID
```

5. Verify:
   - Only new images are processed (check `total_files` in status)
   - Existing clusters are preserved
   - New faces are added to appropriate clusters
   - `processed_files` table updated

**Expected Result**: Only new images processed, clusters updated incrementally.

### Test 4: Polling - Start and Monitor

**Objective**: Test continuous polling for new images.

1. Start polling:
```bash
curl -X POST http://localhost:8000/api/drive/polling/start \
  -H "x-admin-token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "drive_link": "YOUR_DRIVE_LINK",
    "interval_seconds": 120
  }'
```

2. Check polling status:
```bash
curl http://localhost:8000/api/drive/polling/status
```

3. Verify response shows:
   - `"active": true`
   - `"folder_id": "..."`

4. Add a new image to the Drive folder

5. Wait for the polling interval (2 minutes in this example)

6. Check the database or use the health endpoint:
```bash
curl http://localhost:8000/health
```

7. Verify the cluster count increased if a new person was detected

**Expected Result**: Polling runs automatically, new images are processed incrementally.

### Test 5: Polling - Stop

**Objective**: Verify polling can be stopped.

1. Ensure polling is active (from Test 4)

2. Stop polling:
```bash
curl -X POST http://localhost:8000/api/drive/polling/stop \
  -H "x-admin-token: YOUR_TOKEN"
```

3. Check status:
```bash
curl http://localhost:8000/api/drive/polling/status
```

4. Verify:
   - `"active": false`
   - `"folder_id": null`

5. Add a new image to Drive folder

6. Wait 5 minutes

7. Verify the new image is NOT processed (cluster count unchanged)

**Expected Result**: Polling stops, no new images are processed automatically.

### Test 6: Edge Cases

#### 6.1 Empty Folder
```bash
# Process an empty folder
curl -X POST http://localhost:8000/api/drive/process \
  -H "x-admin-token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"drive_link": "EMPTY_FOLDER_LINK"}'
```
**Expected**: Error message "No images found in the Drive folder."

#### 6.2 Incremental with No New Images
```bash
# Run incremental processing twice without adding new images
curl -X POST http://localhost:8000/api/drive/process \
  -H "x-admin-token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "drive_link": "YOUR_DRIVE_LINK",
    "incremental": true
  }'
```
**Expected**: Status "done" with message "No new images to process."

#### 6.3 Invalid Drive Link
```bash
curl -X POST http://localhost:8000/api/drive/process \
  -H "x-admin-token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"drive_link": "invalid-link"}'
```
**Expected**: 400 Bad Request with error message.

#### 6.4 Start Polling While Already Active
```bash
# Start polling twice
curl -X POST http://localhost:8000/api/drive/polling/start \
  -H "x-admin-token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "drive_link": "YOUR_DRIVE_LINK",
    "interval_seconds": 300
  }'
```
**Expected**: Error "Polling is already active. Stop it first before starting a new one."

## Database Inspection

Check what's in the database:

```bash
# Install sqlite3 if not available
# Then inspect the database:

sqlite3 data/getme.db  # Or wherever DATABASE_PATH points

# Check processed files
SELECT COUNT(*) FROM processed_files;
SELECT file_id, file_name FROM processed_files LIMIT 5;

# Check clusters
SELECT COUNT(*) FROM clusters;
SELECT face_id, face_count FROM clusters;

# Check cluster-file associations
SELECT face_id, COUNT(*) as photo_count 
FROM cluster_files 
GROUP BY face_id;

.exit
```

## Testing with the Interactive API Docs

FastAPI provides interactive API documentation:

1. Open http://localhost:8000/docs
2. Click on any endpoint to expand it
3. Click "Try it out"
4. Fill in the parameters
5. Click "Execute"
6. View the response

This is great for:
- Testing API endpoints quickly
- Seeing request/response schemas
- Debugging without writing curl commands

## Automated Testing Script

Here's a quick Python script to test the basic workflow:

```python
#!/usr/bin/env python3
"""Quick test script for GetME! API"""
import time
import requests

BASE_URL = "http://localhost:8000"
ADMIN_TOKEN = "your-admin-token"  # Change this
DRIVE_LINK = "your-drive-link"    # Change this

headers = {"x-admin-token": ADMIN_TOKEN}

# 1. Start full processing
print("Starting full processing...")
resp = requests.post(
    f"{BASE_URL}/api/drive/process",
    headers=headers,
    json={"drive_link": DRIVE_LINK, "incremental": False}
)
job_id = resp.json()["job_id"]
print(f"Job ID: {job_id}")

# 2. Poll job status
while True:
    resp = requests.get(f"{BASE_URL}/api/drive/status/{job_id}")
    status = resp.json()
    print(f"Status: {status['status']} - {status['processed_files']}/{status['total_files']} files")
    
    if status["status"] in ["done", "error"]:
        print(f"Final status: {status}")
        break
    
    time.sleep(5)

# 3. Check health
resp = requests.get(f"{BASE_URL}/health")
print(f"Health check: {resp.json()}")

print("\nTest completed!")
```

Save as `test_api.py` and run:
```bash
python test_api.py
```

## Performance Testing

For a real event with thousands of photos:

1. **Timing**: Note how long processing takes
   - ~2k photos typically takes 15-25 minutes
   - Depends on CPU, face count per image

2. **Memory**: Monitor memory usage during processing
   ```bash
   # On Linux:
   watch -n 5 'ps aux | grep uvicorn'
   ```

3. **Incremental Efficiency**: Compare times:
   - Full processing of 100 images
   - Add 10 more images, run incremental
   - Incremental should be ~10x faster

## Troubleshooting

### Issue: "Service account file missing"
- Check `GOOGLE_SERVICE_ACCOUNT_FILE` path in `.env`
- Verify the file exists and is valid JSON

### Issue: "Permission denied" on Drive folder
- Ensure the Drive folder is shared with the service account email
- Check that the folder ID is correct

### Issue: No faces detected
- Verify images contain clear faces
- Check `MIN_FACE_CONFIDENCE` and `MIN_FACE_WIDTH_FRACTION` settings
- Try processing higher resolution images

### Issue: Polling doesn't process new images
- Check polling status: `GET /api/drive/polling/status`
- Verify the interval hasn't elapsed yet
- Check server logs for errors

### Issue: Incremental processing re-processes everything
- Verify `processed_files` table is populated
- Check that file IDs match between runs
- Ensure `incremental: true` is set in the request

## Logs and Debugging

Enable debug logging:
```bash
# Run with more verbose output
uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level debug
```

Check terminal output for:
- API requests and responses
- Processing progress
- Error messages and stack traces

## Success Criteria

✅ Full processing completes without errors  
✅ Faces are correctly clustered by person  
✅ Guests can match their selfies and see photos  
✅ Incremental processing only handles new images  
✅ Polling starts, runs automatically, and stops correctly  
✅ Database tables are populated correctly  
✅ No memory leaks during extended polling  

## Next Steps

After successful testing:
1. Test with your actual event photos
2. Set appropriate polling interval for your event
3. Configure match threshold for your quality requirements
4. Set up a tunnel (ngrok/Cloudflare) for guest access
5. Monitor during the actual event
