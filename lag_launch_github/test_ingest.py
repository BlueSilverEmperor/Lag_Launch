import requests

res = requests.post("http://127.0.0.1:9000/api/ingest", json={
    "source": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "interval_sec": 2.0,
    "overwrite": True
})
print("Started job:")
print(res.json())
