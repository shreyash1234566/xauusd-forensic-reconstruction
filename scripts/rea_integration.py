import json, urllib.request

def setup_rea():
    url = "https://raw.githubusercontent.com/morluto/rea/main/package.json"
    try:
        req = urllib.request.urlopen(url)
        data = json.loads(req.read().decode())
        print(f"REA repository connected: {data.get('name', 'rea')}")
    except Exception as e:
        print(f"REA connection stub active: {e}")

if __name__ == "__main__":
    setup_rea()
