import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REFRESH_TOKEN = os.getenv('REFRESH_TOKEN')

if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
    raise EnvironmentError(
        "❌ Fehlende Strava-Keys! Bitte CLIENT_ID, CLIENT_SECRET und REFRESH_TOKEN in der .env-Datei setzen."
    )

def get_fresh_access_token():
    print("🔑 Hole neue Eintrittskarte (Access Token) von Strava...")
    
    auth_url = "https://www.strava.com/oauth/token"
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'refresh_token': REFRESH_TOKEN,
        'grant_type': 'refresh_token',
        'f': 'json'
    }
    
    response = requests.post(auth_url, data=payload, verify=False)
    
    if response.status_code == 200:
        new_token = response.json().get('access_token')
        print("✅ Neues Access Token erfolgreich geholt!")
        return new_token
    else:
        print(f"❌ Fehler beim Token-Holen: {response.status_code} - {response.text}")
        return None

def extract_latest_activities(access_token):
    print("🏃‍♂️ Lade deine letzten Trainingsdaten herunter...")
    
    # Endpunkt für die Aktivitäten
    activities_url = "https://www.strava.com/api/v3/athlete/activities"
    
    # Wir übergeben unser Token im Header (Der Türsteher kontrolliert die Karte)
    headers = {'Authorization': f'Bearer {access_token}'}
    
    # Wir sagen: Gib uns die letzten 5 Aktivitäten (per_page=5)
    params = {'per_page': 5, 'page': 1}
    
    response = requests.get(activities_url, headers=headers, params=params)
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Erfolgreich {len(data)} Aktivitäten geladen!\n")
        
        # Gebe eine kleine Übersicht der Rohdaten aus
        for activity in data:
            name = activity['name']
            entfernung_km = activity['distance'] / 1000  # Strava liefert Meter
            typ = activity['type']
            print(f"- {typ}: {name} ({entfernung_km:.2f} km)")
            
        return data
    else:
        print(f"❌ Fehler beim Datenladen: {response.status_code} - {response.text}")
        return None

# Hauptprogramm starten
if __name__ == '__main__':
    # 1. Neuen Schlüssel besorgen
    token = get_fresh_access_token()
    
    if token:
        # 2. Mit dem Schlüssel die Daten extrahieren
        roh_daten = extract_latest_activities(token)
        
        # Ab hier würde später der "Transform" Schritt beginnen!
